import argparse
import datetime
import json
import logging
import re
from pathlib import Path

GITHUB_STEM = "https://github.com/"


def get_desc(repo, info, comment):
    def strip_img(text):
        return re.sub(r"!\[[^\[\]]*\]\([^\)]+\)", "", text)

    def strip_link(text):
        text = re.sub(r"\[([^\[\]]*)\]\([^\)]+\)", r"\1", text)
        text = re.sub(r"\(http[^\)]+\)", "", text)
        text = re.sub(r"\b[\w._%+\-]+@[\w.\-]+\.[A-Z|a-z]{2,7}\b", "", text)  # remove email
        return text

    def unescape(text):
        return re.sub(r"([\[\]\(\)\|])", r"\\\1", text)

    def strip(text):
        text = re.sub(r"\s+", " ", text).strip() if text else ""
        if text.startswith("-*- "):
            return ""
        return text

    comment = strip(comment)
    header, desc, homepage = "", "", ""
    if info and repo:
        header = strip(info["header"])
        desc = strip(info["description"])
        homepage = strip(info["homepage"])
        if header:
            h = header.lower()
            if any([h in v.lower() for v in [repo, desc]]):
                header = ""

        header = strip(strip_link(strip_img(header)))
        desc = strip(strip_link(strip_img(desc)))
    if header == "" and desc == "":
        desc = f"【{comment}】"
    if header and not header.startswith("**"):
        header = f"**{header}**"
    if homepage:
        homepage = f"<{homepage}>"
    text = "<br>".join([v for v in [header, desc, homepage] if v])

    return unescape(strip_link(strip_img(text))).strip()


def format_repo_list(repo_list, repo_dict, dt):
    t1 = "![{stars}](https://img.shields.io/github/stars/{repo}?style=plastic)<br>\
          ![{forks}](https://img.shields.io/github/forks/{repo}?style=plastic){is_fork}"
    t2 = "{status}![](https://img.shields.io/github/last-commit/{repo}?label=update)"
    t3 = "[{repo}](https://github.com/{repo})"
    if len(repo_list) == 0:
        return []

    data1 = []
    data2 = []
    data3 = []
    for entry in repo_list:
        tag, repo, comment = entry[:3]
        if tag != "":  # dup
            if tag == "-":
                data3.append([True, 0, 0, repo, get_desc(None, None, comment), 3])
            # ignore duplicates
            continue
        elif repo not in repo_dict:
            data3.append([True, 0, 0, repo, get_desc(None, None, comment), 4])
            continue

        info = repo_dict[repo]
        desc = get_desc(repo, info, comment)
        dt2 = datetime.datetime.strptime(info["update"], "%Y-%m-%dT%H:%M:%S%z")
        if info["is_archived"] or (dt - dt2).days > 365 * 2:
            data2.append([not info["is_fork"], info["stars"], info["forks"], repo, desc, 2])
        else:
            data1.append([not info["is_fork"], info["stars"], info["forks"], repo, desc, 1])

    data1 = sorted(data1, reverse=True)
    data2 = sorted(data2, reverse=True)
    data3 = sorted(data3, reverse=True)

    th = ["", "Stars/Forks", "Last Update", "Github Repo", "Description", ""]
    sep2 = " | "
    output = [sep2.join(th), sep2.join([""] + ["---"] * (len(th) - 2) + [""])]
    for e in data1 + data2 + data3:
        is_not_fork, stars, forks, repo, desc, archived = e
        name = repo.split(GITHUB_STEM)[-1]
        if archived <= 2:
            fk = "<br>🎋" if not is_not_fork else ""
            row = [
                t1.format(is_fork=fk, repo=name, stars=stars, forks=forks),
                t2.format(status="🗃️<br>" if archived == 2 else "", repo=name),
                t3.format(repo=name),
                desc,
            ]
        else:
            if repo.startswith("["):
                v2, v3 = "📝", repo
            else:
                v2, v3 = "", "~~{}~~".format(t3.format(repo=name))
            row = ["", v2, v3, desc]
        output.append(sep2.join([""] + row + [""]))
    output = [v.strip() for v in output]
    return output


def update_data(data_file: str, json_dir: str, sep="\t") -> tuple[dict, list]:
    if not Path(data_file).exists():
        logging.warning(f"{data_file} does not exist")
        return None, None

    files = Path(json_dir).glob("*.json")
    data = [json.load(open(file)) for file in files]

    repo_dict = {}
    for entry in data:
        repo, info = entry["repo"], entry["data"]
        repo_dict[repo] = {
            "name": info["full_name"],
            "url": info["html_url"],
            "description": info["description"],
            "header": entry["header"],
            "update": max([info[k] for k in ["updated_at", "pushed_at"]]),
            "stars": info["stargazers_count"],
            "forks": info["forks_count"],
            "is_archived": info["archived"],
            "is_fork": info["fork"],
            "homepage": info["homepage"],
        }

    groups = []
    sub_groups = []
    repo_list = []
    is_update = False
    extra_groups = []
    with open(data_file) as f:
        for line in f:
            line = line.rstrip("\n")
            if line == "":
                continue

            parts = line.split(sep)
            if len(parts) > 1 and GITHUB_STEM in parts[1]:
                tag, repo = parts[:2]
                extra = parts[2] if len(parts) > 2 else ""
                repo = repo.strip().strip("/")
                if repo in repo_dict:
                    repo_url = repo_dict[repo]["url"]
                    if repo_url != repo:  # update repo url
                        is_update = True
                        repo = repo_url
                    if repo in repo_list:
                        logging.warning(f"dup repo = {repo}")
                        tag = "*"
                    else:
                        repo_list.append(repo)
                else:
                    logging.warning(f"404 repo = {repo}")
                    tag = "-"

                if tag != parts[0]:
                    is_update = True
                parts = [tag, repo, extra] + parts[3:]
            # output.append(sep.join(parts))

            if parts[0].startswith("#"):
                if sub_groups:
                    groups.append(sub_groups)
                sub_groups = [parts, []]
            elif len(sub_groups) == 0:
                extra_groups.append(parts)  # # first line
            else:
                sub_groups[1].append(parts)

    if sub_groups:
        groups.append(sub_groups)

    # if is_update:
    logging.info(f"Update {data_file}")
    with open(data_file, "w") as f:
        output2 = extra_groups
        for titles, repos in groups:
            output2.append(titles)
            output2.extend(sorted(repos))
        output2 = [sep.join(parts) for parts in output2]
        f.write("\n".join(output2).strip("\n") + "\n")

    return repo_dict, groups


def update_doc(output_file: str, repo_dict: dict, groups: list | None) -> bool:
    dt = datetime.datetime.now(datetime.UTC)
    dt_day = dt.strftime("%Y-%m-%d")

    if groups is None:
        return False

    logging.info(f"groups = {len(groups)}")
    output = []
    for group in groups:
        title, repos = group
        if isinstance(title, list):
            title = title[0]
        out = format_repo_list(repos, repo_dict, dt)
        output.extend([title, "\n".join(out).strip("\n")])

    seps = ["<!-- START-TABLE -->", "<!-- END-TABLE -->"]
    logging.info(f"Read {output_file}")
    with open(output_file) as f:
        text = f.read()

    part1, part2 = text.split(seps[0])
    _, part2b = part2.split(seps[1])

    pattern = r"(<!-- START-DATE -->\*)[\d\-]+(\*<!-- END-DATE -->)"
    part1b = re.sub(pattern, rf"\g<1>{dt_day}\g<2>", part1)
    parts = [part1b, seps[0], "\n\n".join(output), seps[1], part2b]
    save_parts = "\n\n".join([v.strip() for v in parts])

    logging.info(f"Save to {output_file}")
    with open(output_file, "w") as f:
        f.write(save_parts.strip() + "\n")
    return True


if __name__ == "__main__":
    fmt = "%(asctime)s %(levelname)s %(message)s"
    logging.basicConfig(level=logging.INFO, format=fmt)

    parser = argparse.ArgumentParser()
    # parser.add_argument("-g", "--github_token", required=True, type=str, help="Github tokens")
    parser.add_argument("-f", "--data_file", required=True, type=str, help="Github repo file")
    parser.add_argument("-o", "--output_file", default="README.md", type=str, help="Save file")
    parser.add_argument("-t", "--temp_dir", default="temp", type=str, help="Json data dir")

    args = parser.parse_args()
    # gh_token = args.github_token.split(",")
    data_file = args.data_file
    output_file = args.output_file
    temp_dir = args.temp_dir

    repo_dict, groups = update_data(data_file, temp_dir, sep="\t")
    update_doc(output_file, repo_dict, groups)
