import argparse
import json
import logging
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
QUERY_COLS = [
    "nameWithOwner",
    "url",
    "isArchived",
    "isFork",
    "stargazerCount",
    "forkCount",
    "updatedAt",
    "pushedAt",
    "description",
    "homepageUrl",
]


def sanitize_alias(name, index):
    return "repo_" + re.sub(r"[^a-zA-Z0-9_]", "_", name) + f"{index:03d}"


def build_graphql_query(alias, owner, name):
    # https://docs.github.com/en/graphql/reference/objects#repository
    columns = QUERY_COLS
    reamde = """
        readme: object(expression: "HEAD:README.md") {
          ... on Blob {
            text
          }
        }
    """
    query = [
        f'{alias}: repository(owner: "{owner}", name: "{name}")',
        "{",
        " ".join(columns),
        reamde,
        "}",
    ]
    return "\n".join(query)


def fetch_batch(batch_repos, token):
    url = "https://api.github.com/graphql"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    query_blocks = []
    for alias, repo in batch_repos:
        parts = repo.split("/")
        if len(parts) != 2:
            continue
        block = build_graphql_query(alias, parts[0], parts[1])
        query_blocks.append(block)
    query = "query { " + " ".join(query_blocks) + " }"

    response = requests.post(url, json={"query": query}, headers=headers, timeout=15)

    if response.ok:
        return response.json().get("data", {})
    else:
        logging.warning(f"Request failed: {response.status_code}")
    return {}


def extract_readme_title(readme_text: str) -> str:
    """extract head1 (ATX / SetText) from README Markdown"""
    if not readme_text:
        return ""
    content = readme_text.strip()
    pattern = re.compile(r"^# (.+)$|(.+)[\r\n]=+[\r\n]", re.MULTILINE)
    match = pattern.search(content)
    if match:
        title = match.group(1) or match.group(2)
        return title.strip()
    return ""


def crawl(file: str, token: str, save_file: str, batch_size: int):
    repo_list = read_data(file, ignore=True)
    if not repo_list:
        logging.warning("No repos")
        return
    logging.info(f"Total repo count = {len(repo_list)}")

    save_dir = Path(save_file).parent
    if not save_dir.exists():
        logging.info(f"Create dir {save_dir}")
        save_dir.mkdir(parents=True)
    if "," in token:
        token = token.split(",")[0]

    output_data = []
    for i in range(0, len(repo_list), batch_size):
        batch = repo_list[i : i + batch_size]
        logging.info(f"Process repo: {i + 1} ~ {i + len(batch)}: {batch[0]}")

        batch_data = [(sanitize_alias(repo, i), repo) for i, repo in enumerate(batch)]
        raw_data = fetch_batch(batch_data, token)
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
    parser.add_argument("-t", "--token", required=True, type=str, help="Github tokens")
    parser.add_argument("-f", "--file", default="data.tsv", type=str, help="Github repo file")
    parser.add_argument("-o", "--output", default="repo_data.json", type=str, help="Json data dir")
    parser.add_argument("-b", "--batch-size", default=20, type=int)

    args = parser.parse_args()
    crawl(args.file, args.token, args.output, args.batch_size)
