#!/usr/bin/env python3

import json
import hashlib
import html
import re
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from difflib import SequenceMatcher


# ============================================================
# NEWS NOW
# 複数ニュースソース収集・重複ニュース統合システム
# ============================================================

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_FILE = ROOT / "news.json"


# ------------------------------------------------------------
# 取得するニュースフィード
# ------------------------------------------------------------

FEEDS = {

    # =========================
    # 日本
    # =========================

    "国内": [
        (
            "Google ニュース",
            "https://news.google.com/rss/headlines/section/topic/NATION?hl=ja&gl=JP&ceid=JP:ja"
        ),
        (
            "Google ニュース 国内",
            "https://news.google.com/rss/search?q=日本%20ニュース&hl=ja&gl=JP&ceid=JP:ja"
        ),
    ],

    # =========================
    # 海外
    # =========================

    "海外": [
        (
            "Google ニュース 世界",
            "https://news.google.com/rss/headlines/section/topic/WORLD?hl=ja&gl=JP&ceid=JP:ja"
        ),
        (
            "Google ニュース 海外",
            "https://news.google.com/rss/search?q=海外%20ニュース&hl=ja&gl=JP&ceid=JP:ja"
        ),
    ],

    # =========================
    # IT
    # =========================

    "IT": [
        (
            "Google ニュース IT",
            "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=ja&gl=JP&ceid=JP:ja"
        ),
        (
            "Google ニュース AI",
            "https://news.google.com/rss/search?q=AI%20テクノロジー&hl=ja&gl=JP&ceid=JP:ja"
        ),
    ],

    # =========================
    # スポーツ
    # =========================

    "スポーツ": [
        (
            "Google ニュース スポーツ",
            "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=ja&gl=JP&ceid=JP:ja"
        ),
        (
            "Google ニュース スポーツ",
            "https://news.google.com/rss/search?q=スポーツ%20ニュース&hl=ja&gl=JP&ceid=JP:ja"
        ),
    ],

    # =========================
    # エンタメ
    # =========================

    "エンタメ": [
        (
            "Google ニュース エンタメ",
            "https://news.google.com/rss/headlines/section/topic/ENTERTAINMENT?hl=ja&gl=JP&ceid=JP:ja"
        ),
        (
            "Google ニュース 芸能",
            "https://news.google.com/rss/search?q=芸能%20エンタメ&hl=ja&gl=JP&ceid=JP:ja"
        ),
    ],

    # =========================
    # 科学
    # =========================

    "科学": [
        (
            "Google ニュース 科学",
            "https://news.google.com/rss/search?q=科学%20宇宙%20研究&hl=ja&gl=JP&ceid=JP:ja"
        ),
        (
            "Google ニュース サイエンス",
            "https://news.google.com/rss/search?q=科学%20サイエンス&hl=ja&gl=JP&ceid=JP:ja"
        ),
    ],

    # =========================
    # 経済
    # =========================

    "経済": [
        (
            "Google ニュース 経済",
            "https://news.google.com/rss/search?q=日本%20経済%20ニュース&hl=ja&gl=JP&ceid=JP:ja"
        ),
        (
            "Google ニュース ビジネス",
            "https://news.google.com/rss/search?q=ビジネス%20経済&hl=ja&gl=JP&ceid=JP:ja"
        ),
    ],

}


# ------------------------------------------------------------
# 設定
# ------------------------------------------------------------

MAX_PER_FEED = 20

MAX_TOTAL_NEWS = 120

# この値以上なら「同じニュース」と判断
DUPLICATE_THRESHOLD = 0.72

# 説明文の最大文字数
MAX_DESCRIPTION_LENGTH = 500


USER_AGENT = (
    "Mozilla/5.0 "
    "(compatible; NEWS-NOW-NewsBot/1.0)"
)


# ============================================================
# テキスト処理
# ============================================================

def clean_html(text):
    """
    HTMLタグや余分な空白を削除
    """

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


def normalize_text(text):
    """
    ニュース比較用に文章を正規化
    """

    if not text:
        return ""

    text = clean_html(text)

    # 小文字化
    text = text.lower()

    # URL削除
    text = re.sub(
        r"https?://\S+",
        "",
        text
    )

    # 記号を空白へ
    text = re.sub(
        r"[「」『』【】（）()\[\]［］.,，。！？!?：:；;・/／\\\-—_]",
        " ",
        text
    )

    # ニュースサイトでよく付く表現
    remove_words = [
        "速報",
        "breaking",
        "news",
        "最新",
        "ニュース",
        "更新",
    ]

    for word in remove_words:
        text = text.replace(
            word,
            " "
        )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def title_similarity(title_a, title_b):
    """
    2つのニュースタイトルの類似度を0～1で返す
    """

    a = normalize_text(title_a)
    b = normalize_text(title_b)

    if not a or not b:
        return 0.0

    if a == b:
        return 1.0

    return SequenceMatcher(
        None,
        a,
        b
    ).ratio()


# ============================================================
# ID生成
# ============================================================

def make_id(url, title):
    value = f"{url}|{title}".encode("utf-8")

    return hashlib.sha256(
        value
    ).hexdigest()[:16]


# ============================================================
# 日付処理
# ============================================================

def parse_date(date_text):

    if not date_text:
        return None

    try:

        dt = parsedate_to_datetime(
            date_text
        )

        if dt.tzinfo is None:

            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone(
            timezone.utc
        )

    except Exception:

        return None


def format_japan_date(date_text):

    dt = parse_date(
        date_text
    )

    if not dt:
        return ""

    japan_time = (
        dt + timedelta(hours=9)
    )

    return japan_time.strftime(
        "%Y-%m-%d %H:%M"
    )


# ============================================================
# RSS取得
# ============================================================

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


# ============================================================
# XMLからテキスト取得
# ============================================================

def get_text(element, tag_name):

    child = element.find(
        tag_name
    )

    if child is None:
        return ""

    return child.text or ""


# ============================================================
# 1つのRSSを取得
# ============================================================

def fetch_feed_items(
    category,
    feed_name,
    feed_url
):

    print(
        f"取得中: [{category}] "
        f"{feed_name}"
    )

    try:

        xml_data = fetch_feed(
            feed_url
        )

        root = ET.fromstring(
            xml_data
        )

        channel = root.find(
            "channel"
        )

        if channel is None:

            print(
                "  channelが見つかりません"
            )

            return []

        results = []

        for item in channel.findall(
            "item"
        ):

            title = clean_html(
                get_text(
                    item,
                    "title"
                )
            )

            link = get_text(
                item,
                "link"
            ).strip()

            description = clean_html(
                get_text(
                    item,
                    "description"
                )
            )

            pub_date = get_text(
                item,
                "pubDate"
            ).strip()

            source_element = item.find(
                "source"
            )

            source = ""

            if source_element is not None:

                source = clean_html(
                    source_element.text or ""
                )

            if not title or not link:
                continue

            if not source:

                source = feed_name

            published = parse_date(
                pub_date
            )

            news_item = {

                "id": make_id(
                    link,
                    title
                ),

                "category": category,

                "title": title,

                "description": (
                    description[
                        :MAX_DESCRIPTION_LENGTH
                    ]
                ),

                "source": source,

                "date": format_japan_date(
                    pub_date
                ),

                "url": link,

                "_published": (
                    published.timestamp()
                    if published
                    else 0
                ),

                "_sources": [
                    source
                ],

                "_source_urls": [
                    link
                ],

            }

            results.append(
                news_item
            )

            if len(results) >= MAX_PER_FEED:

                break

        print(
            f"  → {len(results)}件"
        )

        return results

    except Exception as error:

        print(
            f"  → 取得失敗: {error}"
        )

        return []


# ============================================================
# 同じニュースを統合
# ============================================================

def merge_news_items(
    base,
    duplicate
):

    # より新しいタイトルを優先
    if (
        duplicate.get(
            "_published",
            0
        )
        >
        base.get(
            "_published",
            0
        )
    ):

        base["title"] = duplicate[
            "title"
        ]

        base["date"] = duplicate[
            "date"
        ]

        base["_published"] = duplicate[
            "_published"
        ]

    # 説明文
    if (
        len(
            duplicate.get(
                "description",
                ""
            )
        )
        >
        len(
            base.get(
                "description",
                ""
            )
        )
    ):

        base["description"] = duplicate[
            "description"
        ]

    # 情報源を追加
    for source in duplicate.get(
        "_sources",
        []
    ):

        if source not in base[
            "_sources"
        ]:

            base[
                "_sources"
            ].append(
                source
            )

    # 元記事URLを追加
    for url in duplicate.get(
        "_source_urls",
        []
    ):

        if url not in base[
            "_source_urls"
        ]:

            base[
                "_source_urls"
            ].append(
                url
            )

    return base


def are_same_news(
    news_a,
    news_b
):

    # 同じURLなら確実に同じ
    if (
        news_a.get("url")
        ==
        news_b.get("url")
    ):

        return True

    # タイトル比較
    similarity = title_similarity(
        news_a.get(
            "title",
            ""
        ),
        news_b.get(
            "title",
            ""
        )
    )

    return (
        similarity
        >= DUPLICATE_THRESHOLD
    )


def merge_duplicates(
    news_list
):

    merged = []

    for news in news_list:

        found_duplicate = False

        for existing in merged:

            # 同じカテゴリーを中心に比較
            if (
                existing.get(
                    "category"
                )
                !=
                news.get(
                    "category"
                )
            ):

                continue

            if are_same_news(
                existing,
                news
            ):

                merge_news_items(
                    existing,
                    news
                )

                found_duplicate = True

                break

        if not found_duplicate:

            merged.append(
                news
            )

    return merged


# ============================================================
# ソース情報を公開用形式に変換
# ============================================================

def finalize_news(news):

    sources = news.get(
        "_sources",
        []
    )

    source_urls = news.get(
        "_source_urls",
        []
    )

    source_list = []

    for index, source in enumerate(
        sources
    ):

        url = ""

        if index < len(
            source_urls
        ):

            url = source_urls[
                index
            ]

        source_list.append({

            "name": source,

            "url": url

        })

    return {

        "id": news.get(
            "id",
            ""
        ),

        "category": news.get(
            "category",
            "総合"
        ),

        "title": news.get(
            "title",
            ""
        ),

        "description": news.get(
            "description",
            ""
        ),

        "source": (
            sources[0]
            if sources
            else "NEWS NOW"
        ),

        "sources": source_list,

        "date": news.get(
            "date",
            ""
        ),

        "url": news.get(
            "url",
            ""
        )

    }


# ============================================================
# 既存ニュース読み込み
# ============================================================

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

            return json.load(
                file
            )

    except Exception:

        return {
            "updatedAt": "",
            "items": []
        }


# ============================================================
# メイン
# ============================================================

def main():

    print("")
    print("=" * 60)
    print("NEWS NOW ニュース収集開始")
    print("=" * 60)
    print("")

    all_news = []

    # --------------------------------------------------------
    # 全RSSフィード取得
    # --------------------------------------------------------

    for category, feeds in FEEDS.items():

        print("")
        print(
            f"===== {category} ====="
        )

        for feed_name, feed_url in feeds:

            items = fetch_feed_items(
                category,
                feed_name,
                feed_url
            )

            all_news.extend(
                items
            )

            # アクセス間隔
            time.sleep(1)


    print("")
    print(
        f"取得したニュース総数: "
        f"{len(all_news)}件"
    )


    # --------------------------------------------------------
    # URLによる一次重複削除
    # --------------------------------------------------------

    unique_by_url = {}

    for news in all_news:

        url = news.get(
            "url",
            ""
        )

        if not url:
            continue

        if url not in unique_by_url:

            unique_by_url[
                url
            ] = news

        else:

            merge_news_items(
                unique_by_url[url],
                news
            )


    all_news = list(
        unique_by_url.values()
    )


    print(
        f"URL重複削除後: "
        f"{len(all_news)}件"
    )


    # --------------------------------------------------------
    # タイトル類似度によるニュース統合
    # --------------------------------------------------------

    merged_news = merge_duplicates(
        all_news
    )


    print(
        f"同一ニュース統合後: "
        f"{len(merged_news)}件"
    )


    # --------------------------------------------------------
    # 新しい順
    # --------------------------------------------------------

    merged_news.sort(
        key=lambda item: item.get(
            "_published",
            0
        ),
        reverse=True
    )


    # --------------------------------------------------------
    # 最大件数
    # --------------------------------------------------------

    merged_news = merged_news[
        :MAX_TOTAL_NEWS
    ]


    # --------------------------------------------------------
    # 公開用データへ変換
    # --------------------------------------------------------

    final_news = []

    for news in merged_news:

        final_news.append(
            finalize_news(
                news
            )
        )


    # --------------------------------------------------------
    # ニュースが取得できなかった場合
    # --------------------------------------------------------

    existing = load_existing_news()

    if not final_news:

        print("")
        print(
            "ニュースを取得できませんでした。"
        )

        if existing.get(
            "items"
        ):

            print(
                "既存のnews.jsonを維持します。"
            )

            return

        print(
            "既存ニュースもありません。"
        )

        return


    # --------------------------------------------------------
    # 保存
    # --------------------------------------------------------

    now = datetime.now(
        timezone.utc
    ).astimezone()


    output = {

        "updatedAt":
            now.isoformat(),

        "total":
            len(final_news),

        "items":
            final_news

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


    # --------------------------------------------------------
    # 完了
    # --------------------------------------------------------

    print("")
    print("=" * 60)

    print(
        "NEWS NOW ニュース更新完了"
    )

    print(
        f"最終ニュース数: "
        f"{len(final_news)}件"
    )

    print(
        f"保存先: {OUTPUT_FILE}"
    )

    print("=" * 60)
    print("")


if __name__ == "__main__":

    main()
