import argparse
import json
import logging
import os
import random
import re
import time
from pathlib import Path

import requests

RENAMED_COLS = {
    "nameWithOwner": "full_name",
    "url": "html_url",
    "isArchived": "archived",
    "isFork": "fork",
    "stargazerCount": "stargazers_count",
    "forkCount": "forks_count",
    "updatedAt": "updated_at",
    "pushedAt": "pushed_at",
    "description": "description",
    "homepageUrl": "homepage",
}

GRAPHQL_FRAGMENT = """
fragment F on Repository{
  nameWithOwner
  url
  isArchived
  isFork
  stargazerCount
  forkCount
  updatedAt
  pushedAt
  description
  homepageUrl
  readme: object(expression: "HEAD:README.md") {
    ... on Blob { text }
  }
}
"""


GITHUB_STEM = "https://github.com/"


def sanitize_alias(index: int, name: str | None = None):
    return f"r{index:03d}"


def random_sleep(max_time: float = 5.0, min_time: float = 1.0):
    delay = round(min_time + random.random() * max_time, 3)
    logging.info(f"Sleep {delay} seconds ...")
    time.sleep(delay)


def save_to_json(data: list, save_file: str, is_temp: bool = False):
    if not data:
        logging.warning("No save data; skip saving")
        return

    save_path = Path(save_file)
    save_dir = save_path.parent
    if not save_dir.exists():
        logging.debug(f"Create dir {save_dir}")
        save_dir.mkdir(parents=True)

    if is_temp:
        save_path = Path(save_dir, "temp-" + save_path.name)

    logging.info(f"Save data (count = {len(data)})")
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _get_repo_path(repo_url: str) -> str:
    if GITHUB_STEM not in repo_url:
        return ""
    return repo_url.split(GITHUB_STEM)[-1].strip(" /")


def read_data(file: str, sep: str = "\t", ignore: bool = True) -> list[str]:
    if not Path(file).exists():
        logging.warning(f"{file} does not exist")
        return []

    repo_set: set[str] = set()
    with open(file, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if line == "" or line.startswith("#"):
                continue
            parts = line.split(sep)
            if len(parts) <= 1:
                continue
            tag, url = parts[:2]
            # ignore deleted repo or not repo url
            if ignore and tag.strip() in ["-", "%"]:
                continue
            repo_path = _get_repo_path(url)
            if repo_path:
                repo_set.add(repo_path)

    repo_list = sorted(repo_set)
    return repo_list


def _build_graphql_query(repos: list[tuple[str, str, str, str]]) -> str:
    query_blocks = []
    for repo_id, _, repo_owner, repo_name in repos:
        block = f'{repo_id}: repository(owner: "{repo_owner}", name: "{repo_name}")'
        block += "{...F}"
        query_blocks.append(block)

    query = "query{\n" + "\n".join(query_blocks) + "\n}" + GRAPHQL_FRAGMENT
    query = re.sub(r"\n+", "\n", query)
    return query


def fetch_batch(batch_repos: list[tuple[str, str]], token: str, timeout: int = 15) -> dict:
    url = "https://api.github.com/graphql"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    batch_repos2 = []
    for alias, repo in batch_repos:
        parts = repo.split("/")  # owner_name, repo_name
        if len(parts) != 2:
            continue
        batch_repos2.append((alias, repo, parts[0], parts[1]))

    if not batch_repos2:
        return {}

    query = _build_graphql_query(batch_repos2)
    try:
        response = requests.post(url, json={"query": query}, headers=headers, timeout=timeout)
        # response.raise_for_status()
        if response:
            payload = response.json()
            if isinstance(payload, dict) and (data := payload.get("data")):
                return data
        else:
            logging.warning(f"Error status = {response.status_code}")
    except requests.RequestException as exc:
        logging.warning(f"GitHub GraphQL request failed: {exc}")
    except ValueError:
        logging.warning("GitHub GraphQL response is not valid JSON")

    return {}


def _clean_markdown(content):
    """
    only keep name/introduction part of project, remove details in readme
    """
    content = re.sub(r"<[^>]+>", "", content, flags=re.MULTILINE)  # html tag
    content = re.sub(r"^\s+.*\n", "", content)
    content = re.sub(r"^[-+_=]{3,}", "", content, flags=re.MULTILINE)  # hr
    content = re.sub(r"^([*+\-]|\d+\.)\s+.*", "", content, flags=re.MULTILINE)  # list
    content = re.sub(r"^>+ .*", "", content, flags=re.MULTILINE)  # Blockquote
    content = re.sub(r"^\|.*\|\s*\n", "", content, flags=re.MULTILINE)  # table
    content = re.sub(r"!\[[^\]]*\]\([^\)]*\)", "", content, flags=re.MULTILINE)  # image
    content = re.sub(r"\[([^\]]*)\]\([^\)]*\)", r"\1", content, flags=re.MULTILINE)  # link

    content = re.sub(r"^```.*?```\n", "", content, flags=re.MULTILINE | re.DOTALL)  # code block
    content = content.strip()
    return content


def extract_readme_title(readme_text: str | None) -> str:
    """extract head1 (ATX / SetText) from README Markdown"""
    if not readme_text:
        return ""

    content = _clean_markdown(readme_text)
    pattern = re.compile(r"^# (.+)$|(.+)[\r\n]=+[\r\n]", flags=re.MULTILINE)
    match = pattern.search(content)
    out = ""
    if match:
        out = match.group(1) or match.group(2)
    elif content:
        out = content.split("\n")[0]
    out = re.sub(r"^#+\s*|\s+#+$", "", out)
    out = re.sub(r"[\u200d\ufeff\s]+", " ", out)
    out = out.strip()
    return out


def crawl(file: str, token: str | None, save_file: str, batch_size: int, alert: bool = True):
    if not token or not token.strip():
        logging.error("TOKEN is required for GitHub GraphQL requests")
        return

    if batch_size <= 0:
        logging.warning("batch_size must be greater than 0; use default 20")
        batch_size = 20

    repo_list = read_data(file, ignore=True)
    total = len(repo_list)
    logging.info(f"All repositories= {total}")
    if not repo_list:
        logging.warning("No repository data")
        return

    random.shuffle(repo_list)

    output_data = []
    for i in range(0, total, batch_size):
        batch = repo_list[i : i + batch_size]
        count = len(batch)
        logging.info(f"Process repo: {i + 1} ~ {i + count}: {batch[0]}")

        batch_data = [(sanitize_alias(i, repo), repo) for i, repo in enumerate(batch)]
        raw_data = fetch_batch(batch_data, token)
        if i + batch_size < total:
            random_sleep()

        if alert and count >= 10 and (not raw_data or len(raw_data) <= count // 2):
            logging.error("Too many repositories query failed in one batch")
            return

        for alias, repo in batch_data:
            repo_data = raw_data.get(alias)
            if not repo_data:
                logging.warning(f"Ignore error repo = {repo}")
                continue

            result = {"request_repo": repo}
            for k, v in RENAMED_COLS.items():
                result[v] = repo_data.get(k)

            readme_text = None
            readme_raw = repo_data.get("readme") or {}
            if readme_raw and readme_raw.get("text"):
                readme_text = readme_raw["text"]
            result["readme_title"] = extract_readme_title(readme_text)
            output_data.append(result)

    if alert and len(output_data) < int(total * 0.8):
        logging.error("Too many repositories failed")
        # save to temp file
        save_to_json(output_data, save_file, is_temp=True)
        return

    save_to_json(output_data, save_file)
    logging.info("Done")


if __name__ == "__main__":
    fmt = "%(asctime)s %(levelname)s %(message)s"
    logging.basicConfig(level=logging.INFO, format=fmt)

    parser = argparse.ArgumentParser()
    parser.add_argument("-f", "--file", default="data.tsv", type=str, help="Github repo file")
    parser.add_argument("-o", "--output", default="repo_data.json", type=str, help="Temporary JSON data file")
    parser.add_argument("-b", "--batch-size", default=20, type=int)
    args = parser.parse_args()

    token = os.getenv("TOKEN")
    crawl(args.file, token, args.output, args.batch_size)
