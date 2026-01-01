import argparse
import datetime
import json
import logging
import re
from pathlib import Path
from urllib.parse import unquote

GITHUB_STEM = "https://github.com/"


def _strip_img(text):
    return re.sub(r"!\[[^\[\]]*\]\([^\)]+\)", "", text)


def _strip_link(text):
    text = re.sub(r"\[([^\[\]]*)\]\([^\)]+\)", r"\1", text)
    text = re.sub(r"\(http[^\)]+\)", "", text)
    text = re.sub(r"\b[\w._%+\-]+@[\w.\-]+\.[A-Z|a-z]{2,7}\b", "", text)  # remove email
    return text


def unescape(text):
    return re.sub(r"([\[\]\(\)\|])", r"\\\1", text)


def _strip_text(text, ignore=True):
    text = re.sub(r"\s+", " ", text).strip() if text else ""
    if ignore and text.startswith("-*- "):
        return ""
    return text


def _strip_media(text):
    return _strip_text(_strip_link(_strip_img(text)), False)


def get_desc(repo_link, repo_info, comment):
    comment = _strip_text(comment)
    header, desc, homepage = "", "", ""
    if repo_info and repo_link:
        header = _strip_text(repo_info["readme_title"])
        desc = _strip_text(repo_info["description"])
        homepage = _strip_text(repo_info["homepage"])
        if header:
            h = header.lower()
            if any([h in v.lower() for v in [repo_link, desc]]):
                header = ""

        header = _strip_media(header)
        desc = _strip_media(desc)

    if header == "" and desc == "":
        desc = f"【{comment}】" if comment else "--"
    if header and not header.startswith("**"):
        header = f"**{header}**"
    if homepage:
        homepage = unquote(homepage)
        homepage = f" <{homepage}> "
    text = "<br>".join([v for v in [header, desc, homepage] if v])

    out = unescape(_strip_media(text))
    out = out.strip()
    return out


def extract_repo_name(repo_link):
    if GITHUB_STEM not in repo_link:
        return repo_link
    return repo_link.split(GITHUB_STEM)[-1].strip("/")


def get_data_list(repo_list, repo_dict, dt):
    data1 = []
    data2 = []
    data3 = []
    for entry in repo_list:
        tag, repo_link, comment = entry[:3]
        repo_name = extract_repo_name(repo_link)
        if tag != "":  # ignore duplicates
            # if tag == "-":
            data3.append([True, 0, 0, repo_name, get_desc(None, None, comment), 3])
            continue
        elif repo_name not in repo_dict:
            data3.append([True, 0, 0, repo_name, get_desc(None, None, comment), 4])
            continue

        info = repo_dict[repo_name]
        is_archived = info["archived"]
        is_forked = info["fork"]
        stars = info["stargazers_count"]
        forks = info["forks_count"]
        update_at = max(info["updated_at"], info["pushed_at"])

        desc = get_desc(repo_link, info, comment)
        dt2 = datetime.datetime.strptime(update_at, "%Y-%m-%dT%H:%M:%S%z")
        if is_archived or (dt - dt2).days > 365 * 2:
            data2.append([not is_forked, stars, forks, repo_name, desc, 2])
        else:
            data1.append([not is_forked, stars, forks, repo_name, desc, 1])

    data1 = sorted(data1, reverse=True)
    data2 = sorted(data2, reverse=True)
    data3 = sorted(data3, reverse=True)
    data_list = data1 + data2 + data3
    return data_list


def format_repo_list(repo_list, repo_dict, repo_codes, dt, style="flat-square"):
    th = ["", "收藏", "更新", "仓库", "说明", ""]
    md_table_sep = " | "
    repo_link = "https://github.com/{repo}"
    stars_link = "https://img.shields.io/github/stars/{repo}?style={style}"
    forks_link = "https://img.shields.io/github/forks/{repo}?style={style}"
    commit_link = "https://img.shields.io/github/last-commit/{repo}?style={style}&label=update"

    cell_stars = "![{stars}][{name}_stars]<br>![{forks}][{name}_forks]{is_fork}"
    cell_commit = "![{name}_commit]{is_archived}"
    cell_repo = "[{repo}][{name}]"
    if len(repo_list) == 0:
        return [], []

    data_list = get_data_list(repo_list, repo_dict, dt)

    # create table
    link_list = []
    output = [
        md_table_sep.join(th),
        md_table_sep.join([""] + ["---"] * (len(th) - 2) + [""]),
    ]
    for e in data_list:
        is_not_fork, stars, forks, repo_name, desc, archived = e
        if repo_name.startswith("["):
            row = ["", "📝", repo_name, desc]
        else:
            repo_code = repo_codes[repo_name]
            link_list.append(f"[{repo_code}]: " + repo_link.format(repo=repo_name))
            if archived > 2:
                row = ["", "", f"~~{cell_repo.format(repo=repo_name, name=repo_code)}~~", desc]
            else:
                new_links = [
                    f"[{repo_code}_stars]: " + stars_link.format(repo=repo_name, style=style),
                    f"[{repo_code}_forks]: " + forks_link.format(repo=repo_name, style=style),
                    f"[{repo_code}_commit]: " + commit_link.format(repo=repo_name, style=style),
                ]
                link_list.extend(new_links)

                fk = "<br>🎋" if not is_not_fork else ""
                st = "<br>🗃️" if archived == 2 else ""
                row = [
                    cell_stars.format(is_fork=fk, name=repo_code, stars=stars, forks=forks),
                    cell_commit.format(is_archived=st, name=repo_code),
                    cell_repo.format(repo=repo_name, name=repo_code),
                    desc,
                ]

        output.append(md_table_sep.join([""] + row + [""]))
    output = [v.strip() for v in output]

    return output, link_list


def _read_repo_file(repo_file: str) -> dict[str:dict]:
    key_name = "request_repo"
    with open(repo_file, encoding="utf-8") as f:
        data = json.load(f)
    repo_dict = {entry[key_name]: entry for entry in data}
    return repo_dict


def update_data_file(data_file: str, repo_file: str, sep="\t") -> tuple[dict, list]:
    """Update data.tsv, remove deleted or duplicated repo"""
    if not Path(repo_file).exists():
        logging.warning(f"{repo_file} does not exist")
        return None, None

    key_url = "html_url"
    repo_dict = _read_repo_file(repo_file)
    repo_codes = {}

    groups = []
    sub_groups = []
    existed_repo_set = set()
    extra_groups = []
    count = 0
    with open(data_file, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if line == "":
                continue

            parts = line.split(sep)
            if len(parts) > 1 and GITHUB_STEM in parts[1]:
                tag, repo_link = parts[:2]
                extra = parts[2] if len(parts) > 2 else ""
                repo_name = extract_repo_name(repo_link)
                if repo_name in repo_dict:
                    repo_link = repo_dict[repo_name][key_url]  # may renamed
                    if repo_link in existed_repo_set:
                        logging.warning(f"dup repo = {repo_link}")
                        continue
                        # tag = "*"
                    existed_repo_set.add(repo_link)
                    repo_name = extract_repo_name(repo_link)
                else:
                    logging.warning(f"404 repo = {repo_link}")
                    tag = "-"
                parts = [tag, repo_link, extra] + parts[3:]
                repo_codes[repo_name] = f"gh_{count:03d}"
                count += 1

            if parts[0].startswith("#"):
                if sub_groups:
                    groups.append(sub_groups)
                sub_groups = [parts, []]
            elif len(sub_groups) == 0:
                extra_groups.append(parts)  # first line
            else:
                sub_groups[1].append(parts)

    if sub_groups:
        groups.append(sub_groups)

    logging.info(f"Update {data_file}")
    with open(data_file, "w", encoding="utf-8") as f:
        output2 = extra_groups
        for titles, repos in groups:
            output2.append(titles)
            output2.extend(sorted(repos))
        output2 = [sep.join(parts) for parts in output2]
        f.write("\n".join(output2).strip("\n") + "\n")

    return groups, repo_codes


def update_doc_file(doc_file: str, repo_file: str, groups: list, repo_codes: dict) -> bool:
    dt = datetime.datetime.now(datetime.UTC)
    dt_day = dt.strftime("%Y-%m-%d")

    if groups is None:
        return False
    repo_dict = _read_repo_file(repo_file)

    logging.info(f"groups = {len(groups)}")
    output = []
    link_list = []
    for group in groups:
        title, repo_entries = group
        if isinstance(title, list):
            title = title[0]
        out, links = format_repo_list(repo_entries, repo_dict, repo_codes, dt)
        output.extend([title, "\n".join(out).strip("\n")])
        link_list.extend(links + [""])

    md_data_seps = ["<!-- START-TABLE -->", "<!-- END-TABLE -->"]
    output_file = doc_file
    logging.info(f"Read {output_file}")
    with open(output_file, encoding="utf-8") as f:
        text = f.read()

    part1, part2 = text.split(md_data_seps[0])
    _, part2b = part2.split(md_data_seps[1])

    pattern = r"(<!-- START-DATE -->\*)[\d\-]+(\*<!-- END-DATE -->)"
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
    save_text = re.sub(r"\n{3,}", "\n\n", save_text).strip()

    logging.info(f"Save to {output_file}")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(save_text + "\n")

    return True


if __name__ == "__main__":
    fmt = "%(asctime)s %(levelname)s %(message)s"
    logging.basicConfig(level=logging.INFO, format=fmt)

    parser = argparse.ArgumentParser()
    parser.add_argument("-f", "--file", default="data.tsv", type=str, help="Github repo file")
    parser.add_argument("-d", "--data", default="repo_data.json", type=str, help="Json data dir")
    parser.add_argument("-o", "--output", default="README.md", type=str, help="Save file")

    args = parser.parse_args()
    groups, repo_codes = update_data_file(args.file, args.data, sep="\t")
    update_doc_file(args.output, args.data, groups, repo_codes)
