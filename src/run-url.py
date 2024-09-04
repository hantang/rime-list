import logging
import random
import time
from pathlib import Path

import requests
from fake_useragent import UserAgent
from lxml import html


def run(topic, page, ua):
    api = f"https://github.com/topics/{topic}"
    headers = {"User-Agent": ua.random, "Referer": api}
    url = f"{api}?page={page}"
    logging.info(f"URL = {url}")

    repos = []
    res = requests.get(url, headers=headers)
    if res.status_code != 200:
        logging.info(f"Error {res.status_code}")
        return repos

    # from scrapy import Selector
    # selector = Selector(text=res.text)
    # div = selector.xpath("/html/body/div[1]/div[4]/main/div[2]/div[2]/div/div[1]")
    # if div:
    #     div_list = div.css("article.color-shadow-small")
    #     repos = [li.css("h3 a")[-1].xpath("@href").get() for li in div_list]

    tree = html.fromstring(res.text)
    div = tree.xpath("/html/body/div[1]/div[4]/main/div[2]/div[2]/div/div[1]")
    if div:
        div_list = div[0].cssselect("article.color-shadow-small")
        repos = [li.cssselect("h3 a")[-1].get("href") for li in div_list]
        # .text_content()
    return repos


def main(topic, pages=20, count=20):
    save_dir = Path("todo")
    save_file = Path(save_dir, f"out-{topic}.txt")
    if save_file.exists():
        return False
    if not save_dir.exists():
        save_dir.mkdir(parents=True)

    ua = UserAgent(platforms=["pc"])
    out = []
    for idx in range(pages):
        page = idx + 1
        result = run(topic, page, ua)
        if result:
            out.extend(result)
            logging.info(f"Save, current = {len(out)}")
            with open(save_file, "w") as f:
                f.write("\n".join(out))

        if len(result) < count:
            logging.info(f"Break, total = {len(out)}")
            break
        n = random.uniform(1, 5)
        logging.info(f"Sleep = {n}")
        time.sleep(n)
    return True


if __name__ == "__main__":
    fmt = "%(asctime)s %(levelname)s %(message)s"
    logging.basicConfig(level=logging.INFO, format=fmt)
    topics = [
        "rime",
        "rime-schema",
        "rime-config",
        "rime-custom",
        "rime-squirrel",
        "rime-weasel",
        "rime-ime",
    ]
    for topic in topics:
        logging.info(f"====> Run {topic}")
        t = 10 if main(topic) else 1
        if topic == topic[-1]:
            break
        logging.info(f"====> Sleep {t}")
        time.sleep(t)
