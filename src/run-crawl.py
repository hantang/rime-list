import argparse
import base64
import concurrent.futures
import json
import logging
import random
import re
import time
from pathlib import Path

# import urllib.request
# import urllib.error
import requests


# GitHub API
GITHUB_API_URL = "https://api.github.com/repos"
GITHUB_STEM = "github.com/"


def _random_sleep(idx, min_time=0.5, max_time=3):
    if idx % 5 == 0:
        time.sleep(random.uniform(min_time, max_time))
    elif idx % 17 == 0:
        time.sleep(random.uniform(min_time, max_time) * 2)
    else:
        time.sleep(min_time)


def _get_json(url, headers):
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()
    logging.warning(f"Error {response.status_code}, url = {url}")
    return None


def _fetch_repo_info(idx, save_file, repo, tokens):
    repo_name = repo.split(GITHUB_STEM)[-1].strip("/") if GITHUB_STEM in repo else repo
    url = f"{GITHUB_API_URL}/{repo_name}"
    url_readme = f"{GITHUB_API_URL}/{repo_name}/readme"

    token = random.choice(tokens)
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }

    try:
        logging.info(f"--- Request = {url}")
        repo_info = _get_json(url, headers)
        header = None
        _random_sleep(1)
        logging.info(f"--- Request = {url_readme}")
        readme = _get_json(url_readme, headers)
        if readme:
            content = readme["content"]
            readme_text = base64.b64decode(content).decode("utf-8")
            readme_text = "\n".join(readme_text.strip().split("\n")[:5])
            match = re.search(r"(^|\n)# (\S.*)", readme_text)
            header = match.group(2) if match else None
        _random_sleep(idx)
        return idx, save_file, header, repo_info
    except Exception as e:
        print(f"Exception fetching {repo}: {e}")
        return idx, save_file, None, None


def _save_repo_info(idx, save_file, repo, repo_info, header):
    if repo_info:
        result = {
            "repo": repo,
            "header": header,
            "data": repo_info,
        }
        with open(save_file, "w") as file:
            json.dump(result, file, indent=2, ensure_ascii=False)


def crawl(repo_list, tokens, save_dir, max_workers=5, overwrite=False):
    save_dir = Path(save_dir)
    if not save_dir.exists():
        logging.info(f"Create {save_dir}")
        save_dir.mkdir(parents=True)
    max_workers = min(max_workers, len(repo_list))

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for idx, repo in enumerate(repo_list):
            save_file = Path(save_dir, f"{idx:04d}.json")
            if not overwrite and save_file.exists():
                continue
            futures.append(executor.submit(_fetch_repo_info, idx, save_file, repo, tokens))
        logging.info(f"futures = {len(futures)}")

        for future in concurrent.futures.as_completed(futures):
            idx, save_file, header, repo_info = future.result()
            logging.info(f"Get idx = {idx:03d}, url = {repo_list[idx]}")
            if header is None and repo_info is None:
                logging.warning(f"Failed to fetch info for {repo}")
            else:
                _save_repo_info(idx, save_file, repo_list[idx], repo_info, header)


def read_data(data_file: str, sep="\t") -> list:
    if not Path(data_file).exists():
        logging.warning(f"{data_file} does not exist")
        return []

    repo_list = []
    with open(data_file) as f:
        for line in f:
            line = line.rstrip("\n")
            if line == "":
                continue
            parts = line.split(sep)
            if len(parts) > 1 and GITHUB_STEM in parts[1]:
                repo_list.append(parts[1].strip().strip("/"))

    out = sorted(set(repo_list))
    return out


if __name__ == "__main__":
    fmt = "%(asctime)s %(levelname)s %(message)s"
    logging.basicConfig(level=logging.INFO, format=fmt)

    parser = argparse.ArgumentParser()
    parser.add_argument("-g", "--github_token", required=True, type=str, help="Github tokens")
    parser.add_argument("-f", "--data_file", required=True, type=str, help="Github repo file")
    # parser.add_argument("-o", "--output_file", default="README.md", type=str, help="Save file")
    parser.add_argument("-t", "--temp_dir", default="temp", type=str, help="Json data dir")

    args = parser.parse_args()
    gh_token = args.github_token.split(",")
    data_file = args.data_file
    # output_file = args.output_file
    temp_dir = args.temp_dir

    repo_list = read_data(data_file)
    logging.info(f"repo_list = {len(repo_list)}")

    if len(repo_list) > 0:
        crawl(repo_list, gh_token, save_dir=temp_dir)
