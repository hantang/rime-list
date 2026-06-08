import argparse
import json
import logging
import re
from datetime import UTC, datetime
from enum import IntEnum
from pathlib import Path
from typing import Any
from urllib.parse import unquote

GITHUB_STEM = "https://github.com/"
REPO_KEYNAME = "request_repo"
REPO_KEY_URL = "html_url"


class RepoStatus(IntEnum):
    NORMAL = 10
    UNMAINTAINED = 20
    ARCHIVED = 21
    REMOVED = 30
    OTHERS = 40

    @classmethod
    def get(cls, tag):
        if tag == "":
            return cls.NORMAL
        elif tag == "=":
            return cls.UNMAINTAINED
        elif tag == "-":
            return cls.REMOVED
        else:
            return cls.OTHERS


def _strip_img(text: str) -> str:
    return re.sub(r"!\[[^\[\]]*\]\([^\)]+\)", "", text)


def _strip_link(text: str) -> str:
    text = re.sub(r"\[([^\[\]]*)\]\([^\)]+\)", r"\1", text)
    text = re.sub(r"\(http[^\)]+\)", "", text)
    text = re.sub(r"\b[\w._%+\-]+@[\w.\-]+\.[A-Z|a-z]{2,7}\b", "", text)  # remove email
    return text.strip()


def unescape(text: str) -> str:
    return re.sub(r"([\[\]\(\)\|])", r"\\\1", text)


def remove_emoji(text):
    # 匹配大部分 emoji 的正则
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # 表情符号
        "\U0001F300-\U0001F5FF"  # 符号 & 图形
        "\U0001F680-\U0001F6FF"  # 交通 & 地图
        "\U0001F1E0-\U0001F1FF"  # 国旗
        "\U00002700-\U000027BF"  # Dingbats
        "\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
        "\U00002600-\U000026FF"  # Misc symbols
        "\U00002B00-\U00002BFF"  # Misc symbols & arrows
        "\U0000200D"             # 零宽连接符 (ZWJ)
        "\U00002300-\U000023FF"  # Misc technical
        "]+", flags=re.UNICODE
    )
    return emoji_pattern.sub(r'', text)

def _strip_text(text: str, ignore: bool = True) -> str:
    text = re.sub(r"\s+", " ", text).strip() if text else ""

    text = re.sub(r"\\*\|", "/", text)
    text = re.sub(r"\\+(\S)", r"\1", text)
    text = re.sub(r"\s*[qQ]*\s*群[：:]*(\s*\d{5,}\s*/?)+", " ", text)
    text = re.sub(r"(交流)?[群：:]+", "", text)
    if ignore and text.startswith("-*- "):
        return ""
    return text


def _strip_media(text: str) -> str:
    return _strip_text(_strip_link(_strip_img(text)), False)


def _is_markdown_link(text: str) -> bool:
    return bool(re.match(r"^\[[^\]]+\]\([^\)]+\)$", text.strip()))


def _format_external_link(repo_link: str) -> str:
    if _is_markdown_link(repo_link):
        return repo_link
    label = repo_link.split("://")[-1].strip("/").lower()
    return f"[{label}]({repo_link})"


def _parse_github_time(value: str) -> datetime | None:
    if not value:
        return None
    value = value.replace("Z", "+0000")

    try:
        if "T" in value:
            return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
        return datetime.strptime(value[:10], "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        logging.warning(f"Invalid github time = {value}")
        return None


def get_desc(repo_link: str | None, repo_info: dict[str, Any] | None, comment: str) -> str:
    comment = _strip_text(comment)
    header, desc, homepage = "", "", ""
    if repo_info and repo_link:
        header = _strip_text(repo_info.get("readme_title", ""))
        desc = _strip_text(repo_info.get("description", ""))
        homepage = _strip_text(repo_info.get("homepage", ""))
        if header:
            h = header.lower()
            if any([h in v.lower() for v in [repo_link, desc]]):
                header = ""

        header = _strip_media(header)
        desc = _strip_media(desc)

    if header == "" and desc == "":
        desc = "--"
        if comment:
            if " <" in comment:
                desc = "【" + "】 <".join(comment.split(" <", 1))
            else:
                desc = f"【{comment}】"
    if header and not header.startswith("**"):
        header = f"**{header}**"
    if homepage:
        homepage = unquote(homepage)
        homepage = f" <{homepage}> "
    text = "<br>".join([v for v in [header, desc, homepage] if v])

    out = unescape(_strip_media(text))
    out = remove_emoji(out)
    out = out.strip()
    return out


def extract_repo_name(repo_link: str) -> str:
    if GITHUB_STEM not in repo_link:
        return repo_link
    return repo_link.split(GITHUB_STEM)[-1].strip("/")


def is_archived(dt: datetime, repo_info: dict[str, Any], max_years: int = 3) -> bool:
    cols = ["updated_at", "pushed_at"]
    update_times = [v for c in cols if (v := _parse_github_time(repo_info.get(c, "")))]
    update_dt = max(update_times) if update_times else None
    if update_dt and (dt.year - update_dt.year) >= max_years:
        return True

    if bool(repo_info.get("archived")):
        return True

    return False


def get_data_list(repo_list: list, repo_dict: dict[str, Any], dt: datetime):
    data1 = []  # normal repo
    data2 = []  # archived repo
    data3 = []  # removed, invalid repo
    for entry in repo_list:
        tag, repo_link, comment = (list(entry) + ["", "", ""])[:3]
        default_desc = get_desc(None, None, comment)

        repo_name = extract_repo_name(repo_link)
        if tag == "-":
            data3.append([True, 0, 0, repo_name, default_desc, RepoStatus.REMOVED])
            continue
        elif tag == "%" or repo_name == repo_link:
            data3.append([True, 0, 0, _format_external_link(repo_link), default_desc, RepoStatus.OTHERS])
            continue

        repo_info = repo_dict[repo_name]
        is_forked = bool(repo_info.get("fork"))
        stars = int(repo_info.get("stargazers_count") or 0)
        desc = get_desc(repo_link, repo_info, comment)
        if tag == "=":
            status = RepoStatus.ARCHIVED if bool(repo_info.get("archived")) else RepoStatus.UNMAINTAINED
            data2.append([not is_forked, stars, 0, repo_name, desc, status])
        else:
            forks = int(repo_info.get("forks_count") or 0)
            data1.append([not is_forked, stars, forks, repo_name, desc, RepoStatus.NORMAL])

    data1 = sorted(data1, reverse=True)
    data2 = sorted(data2, reverse=True)
    data3 = sorted(data3, reverse=True)
    data_list = data1 + data2 + data3
    return data_list


def format_repo_list(
    repo_list: list,
    repo_dict: dict,
    repo_codes: dict[str, str],
    dt: datetime,
    style: str = "flat-square",
) -> tuple[list, list]:
    if len(repo_list) == 0:
        return [], []

    th = ["", "收藏", "更新", "仓库", "说明", ""]
    md_table_sep = " | "

    repo_link = "https://github.com/{repo}"
    stars_link = "https://img.shields.io/github/stars/{repo}?style={style}"
    forks_link = "https://img.shields.io/github/forks/{repo}?style={style}"
    commit_link = "https://img.shields.io/github/last-commit/{repo}?style={style}&label=update"

    cell_stars = "![{stars}][{name}_stars]<br>![{forks}][{name}_forks]{is_fork}"
    cell_commit = "![{name}_commit]{is_archived}"
    cell_repo = "[{repo}][{name}]"

    data_list = get_data_list(repo_list, repo_dict, dt)
    # create table
    link_list = []
    output = [
        md_table_sep.join(th),
        md_table_sep.join([""] + ["---"] * (len(th) - 2) + [""]),
    ]
    for e in data_list:
        is_original, stars, forks, repo_name, desc, status = e
        if status == RepoStatus.OTHERS:
            row = ["", "📝", repo_name, desc]
        elif status == RepoStatus.REMOVED:
            repo_path = f"~~[{repo_name}]({repo_link.format(repo=repo_name)})~~"
            # f"~~{cell_repo.format(repo=repo_name, name=repo_code)}~~"
            row = ["", "🩹", repo_path, desc]
        else:
            repo_code = repo_codes.get(repo_name)
            link_list.append(f"[{repo_code}]: " + repo_link.format(repo=repo_name))
            new_links = [
                f"[{repo_code}_stars]: " + stars_link.format(repo=repo_name, style=style),
                f"[{repo_code}_forks]: " + forks_link.format(repo=repo_name, style=style),
                f"[{repo_code}_commit]: " + commit_link.format(repo=repo_name, style=style),
            ]
            link_list.extend(new_links)

            fk = "<br>🎋" if not is_original else ""
            st = "<br>🗃️" if status == RepoStatus.ARCHIVED else ""
            row = [
                cell_stars.format(is_fork=fk, name=repo_code, stars=stars, forks=forks),
                cell_commit.format(is_archived=st, name=repo_code),
                cell_repo.format(repo=repo_name, name=repo_code),
                desc,
            ]

        output.append(md_table_sep.join([""] + row + [""]))
    output = [v.strip() for v in output]

    return output, link_list


def _read_repo_file(repo_file: str) -> dict[str, dict[str, Any]]:
    with open(repo_file, encoding="utf-8") as f:
        data = json.load(f)
    repo_dict = {entry[REPO_KEYNAME]: entry for entry in data}
    return repo_dict


def update_data_file(dt: datetime, data_file: str, repo_file: str, sep="\t") -> tuple[list, dict]:
    """Update data.tsv, remove deleted or duplicated repo"""
    groups: list[dict[str, Any]] = []
    repo_codes: dict[str, str] = {}

    if not Path(repo_file).exists():
        logging.warning(f"{repo_file} does not exist")
        return groups, repo_codes

    sub_group: dict[str, Any] = {}
    existed_repo_set: set[str] = set()
    count = 0

    repo_dict = _read_repo_file(repo_file)
    with open(data_file, encoding="utf-8") as f:
        line_count = len(f.readlines())
    if len(repo_dict) <= int(line_count * 0.7):
        logging.error("Repo data is error")
        return groups, repo_codes

    with open(data_file, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if line == "":
                continue

            parts = line.split(sep)
            if len(groups) == 0 and len(sub_group) == 0:
                groups.append({"header": parts, "values": []})  # table header
                continue

            tag, repo_link, comment = (list(parts) + ["", "", ""])[:3]
            if tag.startswith("#"):  # header line
                if sub_group:
                    groups.append(sub_group)
                sub_group = {"header": parts, "values": []}
                continue

            if GITHUB_STEM in repo_link and tag != "-":
                repo_name = extract_repo_name(repo_link)
                if repo_name in repo_dict:
                    repo_info = repo_dict[repo_name]
                    repo_link = repo_info[REPO_KEY_URL]
                    if repo_link in existed_repo_set:  # ignore duplicated
                        logging.warning(f"dup repo = {repo_link}")
                        continue
                    existed_repo_set.add(repo_link)
                    repo_name = extract_repo_name(repo_link)  # may renamed
                    if is_archived(dt, repo_info):
                        tag = "="  # archived / unmaintained
                else:
                    logging.warning(f"404 repo = {repo_link}")
                    tag = "-"  # removed / private

                parts = [tag, repo_link, comment]
                repo_codes[repo_name] = f"gh_{count:03d}"
                count += 1

            sub_group["values"].append(parts)

    if sub_group:
        groups.append(sub_group)

    logging.info(f"Update {data_file}")
    with open(data_file, "w", encoding="utf-8") as f:
        output2 = []
        for entry in groups:
            output2.append(entry["header"])
            repo_list = sorted(entry["values"], key=lambda x: (RepoStatus.get(x[0]), x[1].lower()))
            output2.extend(repo_list)
        output2 = [sep.join(parts) for parts in output2]
        f.write("\n".join(output2).strip("\n") + "\n")

    return groups, repo_codes


def update_doc_file(
    dt: datetime, doc_file: str, repo_file: str, groups: list[dict[str, Any]], repo_codes: dict[str, str]
):
    md_data_seps = ["<!-- START-TABLE -->", "<!-- END-TABLE -->"]
    logging.info(f"groups = {len(groups)} / repos = {len(repo_codes)}")

    output: list[str] = []
    link_list: list[str] = []
    repo_dict = _read_repo_file(repo_file)
    for entry in groups:
        title, repo_entries = entry["header"], entry["values"]
        if isinstance(title, list):
            title = title[0]

        if not title.startswith("#"):
            continue

        if not repo_entries:
            output.append(title + "\n")
            continue

        out, links = format_repo_list(repo_entries, repo_dict, repo_codes, dt)
        table_text = "\n".join(out).strip("\n")
        output.extend([title, table_text])
        link_list.extend(links + [""])

    output_file = doc_file
    logging.info(f"Read {output_file}")
    with open(output_file, encoding="utf-8") as f:
        text = f.read()

    part1, part2 = text.split(md_data_seps[0])
    _, part2b = part2.split(md_data_seps[1])

    pattern = r"(<!-- START-DATE -->\*)[\d\-]+(\*<!-- END-DATE -->)"
    dt_day = dt.strftime("%Y-%m-%d")
    part1b = re.sub(pattern, rf"\g<1>{dt_day}\g<2>", part1)
    parts = [
        part1b,
        md_data_seps[0],
        "\n\n".join(output),
        "\n\n",
        "\n".join(link_list),
        md_data_seps[1],
        part2b,
    ]
    save_text = "\n\n".join([v.strip() for v in parts])
    save_text = re.sub(r"\\+(\S)", r"\1", save_text)
    save_text = re.sub(r"\n{3,}", "\n\n", save_text).strip()

    logging.info(f"Save to {output_file}")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(save_text + "\n")


if __name__ == "__main__":
    fmt = "%(asctime)s %(levelname)s %(message)s"
    logging.basicConfig(level=logging.INFO, format=fmt)

    parser = argparse.ArgumentParser()
    parser.add_argument("-f", "--file", default="data.tsv", type=str, help="Github repo file")
    parser.add_argument("-d", "--data", default="repo_data.json", type=str, help="Json data dir")
    parser.add_argument("-o", "--output", default="README.md", type=str, help="Save file")

    args = parser.parse_args()
    dt = datetime.now(UTC)

    groups, repo_codes = update_data_file(dt, args.file, args.data, sep="\t")
    if groups and repo_codes:
        update_doc_file(dt, args.output, args.data, groups, repo_codes)
