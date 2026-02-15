import argparse
import json
import logging
import random
import re
import time
from pathlib import Path
import os

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


def sanitize_alias(index, name=None):
    return f"r{index:03d}"


def build_graphql_query(repos):
    query_blocks = []
    for repo_id, _, repo_owner, repo_name in repos:
        block = f'{repo_id}: repository(owner: "{repo_owner}", name: "{repo_name}")'
        block += "{...F}"
        query_blocks.append(block)

    query = "query{\n" + "\n".join(query_blocks) + "\n}" + GRAPHQL_FRAGMENT
    query = re.sub(r"\n+", "\n", query)
    return query


def fetch_batch(batch_repos, token):
    url = "https://api.github.com/graphql"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    batch_repos2 = []
    for alias, repo in batch_repos:
        parts = repo.split("/")
        if len(parts) != 2:
            continue
        batch_repos2.append((alias, repo, parts[0], parts[1]))

    query = build_graphql_query(batch_repos2)
    with open("temp-query.txt", "w") as f:
        f.write(query)
    response = requests.post(url, json={"query": query}, headers=headers, timeout=15)

    if response.ok:
        return response.json().get("data", {})
    else:
        logging.warning(f"Request failed: {response.status_code}")
    return {}


def _clean_markdown(content):
    # 删除不必要部分
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


def extract_readme_title(readme_text: str) -> str:
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


def crawl(file: str, token: str, save_file: str, batch_size: int):
    repo_list = read_data(file, ignore=True)
    if not repo_list:
        logging.warning("No repos")
        return
    total = len(repo_list)
    logging.info(f"Total repo count = {total}")

    save_dir = Path(save_file).parent
    if not save_dir.exists():
        logging.info(f"Create dir {save_dir}")
        save_dir.mkdir(parents=True)

    output_data = []
    for i in range(0, total, batch_size):
        batch = repo_list[i : i + batch_size]
        logging.info(f"Process repo: {i + 1} ~ {i + len(batch)}: {batch[0]}")

        batch_data = [(sanitize_alias(i, repo), repo) for i, repo in enumerate(batch)]
        raw_data = fetch_batch(batch_data, token)
        if i + batch_size < total:
            time.sleep(random.random())

        for alias, repo in batch_data:
            repo_data = raw_data.get(alias)
            if not repo_data:
                logging.warning(f"Ignore error repo = {repo}")
                continue

            result = {"request_repo": repo}
            for k, v in RENAMED_COLS.items():
                result[v] = repo_data.get(k)
            readme_text = None
            if repo_data["readme"] and repo_data["readme"]["text"]:
                readme_text = repo_data["readme"]["text"]
            result["readme_title"] = extract_readme_title(readme_text)
            output_data.append(result)

        if output_data:
            logging.debug(f"Save data (count = {len(output_data)})")
            with open(save_file, "w", encoding="utf-8") as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)

    logging.info(f"Total data = {len(output_data)}")
    logging.info("Done")


def read_data(file: str, sep: str = "\t", ignore: bool = True) -> list:
    GITHUB_STEM = "https://github.com/"
    if not Path(file).exists():
        logging.warning(f"{file} does not exist")
        return []

    repo_set = set()
    with open(file, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if line == "":
                continue
            parts = line.split(sep)
            if len(parts) > 1 and GITHUB_STEM in parts[1]:
                if ignore and parts[0] != "":
                    continue
                repo_name = parts[1].split(GITHUB_STEM)[-1].strip(" /")
                repo_set.add(repo_name)

    repo_list = sorted(repo_set)
    return repo_list


if __name__ == "__main__":
    fmt = "%(asctime)s %(levelname)s %(message)s"
    logging.basicConfig(level=logging.INFO, format=fmt)

    parser = argparse.ArgumentParser()
    parser.add_argument("-f", "--file", default="data.tsv", type=str, help="Github repo file")
    parser.add_argument("-o", "--output", default="repo_data.json", type=str, help="Json data dir")
    parser.add_argument("-b", "--batch-size", default=20, type=int)
    args = parser.parse_args()

    token = os.getenv("TOKEN")
    crawl(args.file, token, args.output, args.batch_size)
