#!/usr/bin/env python3

import json
import hashlib
import html
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_FILE = ROOT / "news.json"


FEEDS = {
    "国内": "https://news.google.com/rss/headlines/section/topic/NATION?hl=ja&gl=JP&ceid=JP:ja",
    "海外": "https://news.google.com/rss/headlines/section/topic/WORLD?hl=ja&gl=JP&ceid=JP:ja",
    "IT": "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=ja&gl=JP&ceid=JP:ja",
    "スポーツ": "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=ja&gl=JP&ceid=JP:ja",
    "エンタメ": "https://news.google.com/rss/headlines/section/topic/ENTERTAINMENT?hl=ja&gl=JP&ceid=JP:ja",
    "科学": "https://news.google.com/rss/search?q=科学%20宇宙%20研究&hl=ja&gl=JP&ceid=JP:ja"
}


MAX_PER_CATEGORY = 15
MAX_TOTAL_NEWS = 80


USER_AGENT = (
    "Mozilla/5.0 "
    "(compatible; NEWS-NOW-NewsBot/1.0)"
)


def clean_html(text):
    if not text:
        return ""

    text = html.unescape(text)

    text = re.sub(
        r"<script\b[^>]*>.*?</script>",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL
    )

    text = re.sub(
        r"<style\b[^>]*>.*?</style>",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL
    )

    text = re.sub(
        r"<[^>]+>",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def make_id(url, title):
    value = f"{url}|{title}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:16]


def parse_date(date_text):
    if not date_text:
        return None

    try:
        dt = parsedate_to_datetime(date_text)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    except Exception:
        return None


def format_japan_date(date_text):
    dt = parse_date(date_text)

    if not dt:
        return ""

    japan_time = dt + timedelta(hours=9)

    return japan_time.strftime("%Y-%m-%d %H:%M")


def fetch_feed(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "application/rss+xml, "
                "application/xml, "
                "text/xml, */*"
            )
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=30
    ) as response:

        return response.read()


def get_text(element, tag_name):
    child = element.find(tag_name)

    if child is None:
        return ""

    return child.text or ""


def fetch_category(category, url):
    print(f"ニュース取得中: {category}")

    try:
        xml_data = fetch_feed(url)

        root = ET.fromstring(xml_data)

        channel = root.find("channel")

        if channel is None:
            print(
                f"{category}: channelが見つかりません"
            )
            return []

        results = []

        for item in channel.findall("item"):

            title = clean_html(
                get_text(item, "title")
            )

            link = get_text(
                item,
                "link"
            ).strip()

            description = clean_html(
                get_text(item, "description")
            )

            pub_date = get_text(
                item,
                "pubDate"
            ).strip()

            source_element = item.find("source")

            source = ""

            if source_element is not None:
                source = clean_html(
                    source_element.text or ""
                )

            if not title or not link:
                continue

            if not source:
                source = "Google ニュース"

            published = parse_date(pub_date)

            news_item = {
                "id": make_id(
                    link,
                    title
                ),
                "category": category,
                "title": title,
                "description": description[:500],
                "source": source,
                "date": format_japan_date(
                    pub_date
                ),
                "url": link,
                "_published": (
                    published.timestamp()
                    if published
                    else 0
                )
            }

            results.append(news_item)

            if len(results) >= MAX_PER_CATEGORY:
                break

        print(
            f"{category}: {len(results)}件取得"
        )

        return results

    except Exception as error:

        print(
            f"{category}: 取得失敗: {error}"
        )

        return []


def load_existing_news():
    if not OUTPUT_FILE.exists():
        return {
            "updatedAt": "",
            "items": []
        }

    try:
        with open(
            OUTPUT_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            return json.load(file)

    except Exception:
        return {
            "updatedAt": "",
            "items": []
        }


def main():

    all_news = []

    for category, url in FEEDS.items():

        category_news = fetch_category(
            category,
            url
        )

        all_news.extend(
            category_news
        )

        time.sleep(1)


    unique_news = {}

    for news in all_news:

        key = (
            news.get("url")
            or news.get("title")
        )

        if key not in unique_news:
            unique_news[key] = news


    all_news = list(
        unique_news.values()
    )


    all_news.sort(
        key=lambda item: item.get(
            "_published",
            0
        ),
        reverse=True
    )


    all_news = all_news[
        :MAX_TOTAL_NEWS
    ]


    for news in all_news:

        news.pop(
            "_published",
            None
        )


    existing = load_existing_news()


    if not all_news:

        print(
            "新しいニュースを取得できませんでした。"
        )

        if existing.get("items"):

            print(
                f"既存ニュースを維持します: "
                f"{len(existing['items'])}件"
            )

            return

        print(
            "既存ニュースもありません。"
        )

        return


    now = datetime.now(
        timezone.utc
    ).astimezone()


    output = {
        "updatedAt": now.isoformat(),
        "items": all_news
    }


    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            output,
            file,
            ensure_ascii=False,
            indent=2
        )

        file.write("\n")


    print(
        f"ニュース更新完了: "
        f"{len(all_news)}件"
    )

    print(
        f"保存先: {OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()
