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
from difflib import SequenceMatcher
from urllib.parse import urlparse


# ============================================================
# NEWS NOW
# 複数ニュースソース収集・高精度重複ニュース統合システム
# ============================================================


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_FILE = ROOT / "news.json"


# ============================================================
# ニュースフィード
# ============================================================

FEEDS = {

    "国内": [
        (
            "Google ニュース 国内",
            "https://news.google.com/rss/headlines/section/topic/NATION?hl=ja&gl=JP&ceid=JP:ja"
        ),
        (
            "Google ニュース 日本",
            "https://news.google.com/rss/search?q=日本%20ニュース&hl=ja&gl=JP&ceid=JP:ja"
        ),
    ],

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

    "スポーツ": [
        (
            "Google ニュース スポーツ",
            "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=ja&gl=JP&ceid=JP:ja"
        ),
        (
            "Google ニュース スポーツ検索",
            "https://news.google.com/rss/search?q=スポーツ%20ニュース&hl=ja&gl=JP&ceid=JP:ja"
        ),
    ],

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


# ============================================================
# 設定
# ============================================================

# 1フィードから取得する最大件数
MAX_PER_FEED = 100

# Noneなら取得できたニュースをすべて保存
MAX_TOTAL_NEWS = None

# 高精度重複判定の基準
#
# 0.80以上:
# タイトル全体がかなり近い
HIGH_SIMILARITY = 0.80

# 0.70以上 + 共通情報が多い場合
MEDIUM_SIMILARITY = 0.70

# 日本語ニュースでは文字単位の共通部分も重視する
MIN_SHARED_SCORE = 0.55

# 説明文最大文字数
MAX_DESCRIPTION_LENGTH = 500

# RSS取得間隔
REQUEST_INTERVAL = 0.5

# HTTP User-Agent
USER_AGENT = (
    "Mozilla/5.0 "
    "(compatible; NEWS-NOW-NewsBot/2.0)"
)


# ============================================================
# テキスト処理
# ============================================================

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


def normalize_text(text):
    """
    ニュースタイトル比較用の正規化。

    ・大文字小文字を統一
    ・URL除去
    ・記号除去
    ・ニュース系の一般語を除去
    ・空白整理
    """

    if not text:
        return ""

    text = clean_html(text)
    text = text.lower()

    text = re.sub(
        r"https?://\S+",
        "",
        text
    )

    # よくあるタイトル上のノイズ
    remove_words = [
        "速報",
        "breaking",
        "news",
        "ニュース",
        "最新",
        "速報版",
        "続報",
        "更新",
        "発表",
        "について",
        "明らかに",
        "明らかになった",
    ]

    for word in remove_words:
        text = text.replace(word, "")

    # 記号
    text = re.sub(
        r"[「」『』【】（）()\[\]［］"
        r"<>＜＞"
        r".,，。！？!?：:；;・"
        r"/／\\\-—–_~〜"
        r"\"'“”‘’]",
        "",
        text
    )

    # 数字の全角半角差をある程度吸収
    text = text.replace("０", "0")
    text = text.replace("１", "1")
    text = text.replace("２", "2")
    text = text.replace("３", "3")
    text = text.replace("４", "4")
    text = text.replace("５", "5")
    text = text.replace("６", "6")
    text = text.replace("７", "7")
    text = text.replace("８", "8")
    text = text.replace("９", "9")

    text = re.sub(
        r"\s+",
        "",
        text
    )

    return text.strip()


def compact_title(text):
    """
    タイトル比較用のより強い正規化。
    """

    text = normalize_text(text)

    # 助詞などを完全に除去するのではなく、
    # 日本語ニュースの比較に使いやすい形にする。
    remove_chars = "はがをにへとでのもや、"

    for char in remove_chars:
        text = text.replace(char, "")

    return text


def make_ngrams(text, size=2):
    """
    日本語向けの文字n-gram。
    形態素解析ライブラリを使わずに、
    「同じ人物・企業・出来事」を比較しやすくする。
    """

    text = compact_title(text)

    if len(text) <= size:
        return {text} if text else set()

    return {
        text[index:index + size]
        for index in range(len(text) - size + 1)
    }


def jaccard_similarity(set_a, set_b):
    if not set_a or not set_b:
        return 0.0

    intersection = len(
        set_a.intersection(set_b)
    )

    union = len(
        set_a.union(set_b)
    )

    if union == 0:
        return 0.0

    return intersection / union


def title_similarity(title_a, title_b):
    """
    複数の方法でタイトルを比較する。
    """

    a = normalize_text(title_a)
    b = normalize_text(title_b)

    if not a or not b:
        return 0.0

    if a == b:
        return 1.0

    # 片方がもう片方をほぼ完全に含む場合
    if len(a) >= 10 and a in b:
        return 0.95

    if len(b) >= 10 and b in a:
        return 0.95

    sequence_score = SequenceMatcher(
        None,
        a,
        b
    ).ratio()

    bigram_a = make_ngrams(a, 2)
    bigram_b = make_ngrams(b, 2)

    trigram_a = make_ngrams(a, 3)
    trigram_b = make_ngrams(b, 3)

    bigram_score = jaccard_similarity(
        bigram_a,
        bigram_b
    )

    trigram_score = jaccard_similarity(
        trigram_a,
        trigram_b
    )

    # 一番強い指標を採用しつつ、
    # SequenceMatcherも考慮
    score = (
        sequence_score * 0.45
        + bigram_score * 0.35
        + trigram_score * 0.20
    )

    return max(
        sequence_score * 0.85,
        score
    )


def extract_significant_chunks(title):
    """
    タイトルから比較に使いやすい文字列を抽出。

    日本語では形態素解析なしでも、
    3～8文字程度の連続文字列を使うことで
    人名・企業名・事件名などの一致を検出しやすい。
    """

    normalized = compact_title(title)

    chunks = set()

    if len(normalized) < 3:
        return chunks

    for size in range(3, 9):
        if len(normalized) < size:
            continue

        for index in range(
            len(normalized) - size + 1
        ):
            chunk = normalized[
                index:index + size
            ]

            # 数字だけの文字列は除外
            if re.fullmatch(
                r"[0-9]+",
                chunk
            ):
                continue

            chunks.add(chunk)

    return chunks


# ============================================================
# ニュース同一性判定
# ============================================================

def same_core_information(news_a, news_b):
    """
    タイトルに共通する重要な情報があるかを確認。
    """

    chunks_a = extract_significant_chunks(
        news_a.get("title", "")
    )

    chunks_b = extract_significant_chunks(
        news_b.get("title", "")
    )

    if not chunks_a or not chunks_b:
        return 0.0

    common = chunks_a.intersection(
        chunks_b
    )

    # 長い共通チャンクを重視
    weighted_common = sum(
        len(chunk)
        for chunk in common
    )

    max_weight = max(
        sum(len(chunk) for chunk in chunks_a),
        sum(len(chunk) for chunk in chunks_b),
        1
    )

    return min(
        weighted_common / max_weight * 2.0,
        1.0
    )


def same_news_score(news_a, news_b):
    """
    2つの記事が同一ニュースである可能性を0～1で返す。
    """

    title_a = news_a.get(
        "title",
        ""
    )

    title_b = news_b.get(
        "title",
        ""
    )

    similarity = title_similarity(
        title_a,
        title_b
    )

    core_score = same_core_information(
        news_a,
        news_b
    )

    # 説明文も利用
    description_a = normalize_text(
        news_a.get(
            "description",
            ""
        )
    )

    description_b = normalize_text(
        news_b.get(
            "description",
            ""
        )
    )

    description_score = 0.0

    if description_a and description_b:
        description_score = SequenceMatcher(
            None,
            description_a,
            description_b
        ).ratio()

    # タイトルがかなり近い
    if similarity >= HIGH_SIMILARITY:
        return max(
            similarity,
            0.90
        )

    # タイトルがそこそこ近く、
    # 共通情報も多い
    if (
        similarity >= MEDIUM_SIMILARITY
        and core_score >= MIN_SHARED_SCORE
    ):
        return 0.88

    # タイトルが少し違っていても
    # 共通する情報が非常に多い
    if (
        similarity >= 0.62
        and core_score >= 0.78
    ):
        return 0.84

    # 説明文までかなり似ている
    if (
        similarity >= 0.58
        and description_score >= 0.80
    ):
        return 0.82

    # それ以外
    return max(
        similarity * 0.75,
        core_score * 0.70
    )


def are_same_news(news_a, news_b):
    """
    同一ニュースか判定。

    URLが同じなら即統合。
    """

    url_a = news_a.get(
        "url",
        ""
    )

    url_b = news_b.get(
        "url",
        ""
    )

    if url_a and url_b and url_a == url_b:
        return True

    score = same_news_score(
        news_a,
        news_b
    )

    return score >= 0.82


# ============================================================
# ID生成
# ============================================================

def make_id(title, published):
    """
    統合後ニュース用の安定ID。
    """

    normalized = normalize_text(
        title
    )

    # 同一ニュースの媒体違いで
    # IDが変わらないようにURLは使わない
    value = (
        f"{normalized}|{published}"
    ).encode("utf-8")

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

    japan_time = dt + timedelta(
        hours=9
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
                "application/atom+xml, "
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
# XMLユーティリティ
# ============================================================

def get_text(element, tag_name):

    child = element.find(
        tag_name
    )

    if child is None:
        return ""

    return (
        child.text or ""
    ).strip()


def get_atom_link(element):

    for child in element:
        tag = child.tag.split("}")[-1]

        if tag != "link":
            continue

        href = child.attrib.get(
            "href",
            ""
        ).strip()

        if href:
            return href

        if child.text:
            return child.text.strip()

    return ""


def find_child_text(element, names):

    for child in element:

        tag = child.tag.split("}")[-1]

        if tag in names:

            if child.text:
                return child.text.strip()

    return ""


# ============================================================
# RSS / Atomニュース取得
# ============================================================

def fetch_feed_items(
    category,
    feed_name,
    feed_url
):

    print(
        f"取得中: [{category}] {feed_name}"
    )

    try:

        xml_data = fetch_feed(
            feed_url
        )

        root = ET.fromstring(
            xml_data
        )

        results = []

        # ----------------------------------------------------
        # RSS
        # ----------------------------------------------------

        channel = None

        for element in root.iter():

            if element.tag.split("}")[-1] == "channel":

                channel = element
                break

        if channel is not None:

            item_elements = [
                element
                for element in channel
                if element.tag.split("}")[-1] == "item"
            ]

        else:

            # ------------------------------------------------
            # Atom
            # ------------------------------------------------

            item_elements = [
                element
                for element in root
                if element.tag.split("}")[-1] == "entry"
            ]


        for item in item_elements:

            title = find_child_text(
                item,
                {"title"}
            )

            title = clean_html(
                title
            )


            # RSS link
            link = find_child_text(
                item,
                {"link"}
            )

            # Atom link
            if not link:
                link = get_atom_link(
                    item
                )

            link = link.strip()


            description = find_child_text(
                item,
                {
                    "description",
                    "summary",
                    "content"
                }
            )

            description = clean_html(
                description
            )


            pub_date = find_child_text(
                item,
                {
                    "pubDate",
                    "published",
                    "updated"
                }
            )


            # source
            source = ""

            for child in item:

                tag = child.tag.split(
                    "}"
                )[-1]

                if tag == "source":

                    source = clean_html(
                        child.text or ""
                    )

                    break


            if not source:

                source = feed_name


            if not title or not link:
                continue


            published = parse_date(
                pub_date
            )


            # source URL
            source_url = ""

            for child in item:

                tag = child.tag.split(
                    "}"
                )[-1]

                if tag == "source":

                    source_url = child.attrib.get(
                        "url",
                        ""
                    ).strip()

                    break


            if not source_url:

                parsed = urlparse(
                    link
                )

                if parsed.scheme and parsed.netloc:

                    source_url = (
                        f"{parsed.scheme}://"
                        f"{parsed.netloc}"
                    )


            news_item = {

                "id": "",

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

                "_source_entries": [
                    {
                        "name": source,
                        "url": source_url,
                        "articleUrl": link
                    }
                ],

            }


            results.append(
                news_item
            )


            if (
                MAX_PER_FEED is not None
                and len(results) >= MAX_PER_FEED
            ):
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
# ニュース統合
# ============================================================

def choose_category(base, duplicate):
    """
    同じニュースが複数カテゴリーに入った場合、
    より自然なカテゴリーを選ぶ。
    """

    category_priority = {
        "国内": 7,
        "海外": 7,
        "IT": 6,
        "スポーツ": 6,
        "エンタメ": 6,
        "科学": 6,
        "経済": 6,
    }

    base_category = base.get(
        "category",
        "国内"
    )

    duplicate_category = duplicate.get(
        "category",
        "国内"
    )

    # 基本的には最初のカテゴリーを維持
    if (
        category_priority.get(
            duplicate_category,
            0
        )
        >
        category_priority.get(
            base_category,
            0
        )
    ):
        return duplicate_category

    return base_category


def merge_news_items(
    base,
    duplicate
):

    # 新しい記事の方が新しければ
    # タイトル・日付・説明を更新
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

        base["title"] = duplicate.get(
            "title",
            base.get("title", "")
        )

        base["date"] = duplicate.get(
            "date",
            base.get("date", "")
        )

        base["_published"] = duplicate.get(
            "_published",
            base.get("_published", 0)
        )


    # より詳しい説明を優先
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


    # カテゴリー
    base["category"] = choose_category(
        base,
        duplicate
    )


    # --------------------------------------------------------
    # 媒体情報を統合
    # --------------------------------------------------------

    existing_entries = base.setdefault(
        "_source_entries",
        []
    )

    duplicate_entries = duplicate.get(
        "_source_entries",
        []
    )


    existing_keys = {
        (
            entry.get("name", ""),
            entry.get("articleUrl", "")
        )
        for entry in existing_entries
    }


    for entry in duplicate_entries:

        key = (
            entry.get("name", ""),
            entry.get("articleUrl", "")
        )

        if key not in existing_keys:

            existing_entries.append(
                {
                    "name": entry.get(
                        "name",
                        ""
                    ),
                    "url": entry.get(
                        "url",
                        ""
                    ),
                    "articleUrl": entry.get(
                        "articleUrl",
                        ""
                    )
                }
            )

            existing_keys.add(
                key
            )


    return base


# ============================================================
# URLの正規化
# ============================================================

def normalize_url(url):

    if not url:
        return ""

    url = url.strip()

    try:

        parsed = urlparse(
            url
        )

        if not parsed.scheme:
            return url

        # Google News等のクエリ違いで
        # 同じ記事になるケースを少し吸収
        normalized = (
            f"{parsed.scheme.lower()}://"
            f"{parsed.netloc.lower()}"
            f"{parsed.path}"
        )

        return normalized.rstrip("/")

    except Exception:

        return url


# ============================================================
# URL重複削除
# ============================================================

def remove_url_duplicates(news_list):

    unique = {}

    for news in news_list:

        url = news.get(
            "url",
            ""
        )

        key = normalize_url(
            url
        )

        if not key:

            # URLがない場合はID代わりにタイトル
            key = (
                "title:"
                + normalize_text(
                    news.get(
                        "title",
                        ""
                    )
                )
            )


        if key not in unique:

            unique[key] = news

        else:

            merge_news_items(
                unique[key],
                news
            )


    return list(
        unique.values()
    )


# ============================================================
# 重複ニュース統合
# ============================================================

def merge_duplicates(news_list):

    # 新しいニュースから処理
    news_list.sort(
        key=lambda item: item.get(
            "_published",
            0
        ),
        reverse=True
    )

    merged = []


    for index, news in enumerate(
        news_list
    ):

        found_duplicate = False


        for existing in merged:

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
# 公開用データ
# ============================================================

def finalize_news(news):

    entries = news.get(
        "_source_entries",
        []
    )


    sources = []

    seen_sources = set()


    for entry in entries:

        name = entry.get(
            "name",
            ""
        ).strip()

        source_url = entry.get(
            "url",
            ""
        ).strip()

        article_url = entry.get(
            "articleUrl",
            ""
        ).strip()


        if not name:
            continue


        key = (
            name,
            article_url
        )


        if key in seen_sources:
            continue


        seen_sources.add(
            key
        )


        sources.append(
            {
                "name": name,
                "url": source_url,
                "articleUrl": article_url
            }
        )


    # ソースが1件もなければNEWS NOW
    if not sources:

        sources.append(
            {
                "name": "NEWS NOW",
                "url": "",
                "articleUrl": news.get(
                    "url",
                    ""
                )
            }
        )


    primary_source = sources[0]["name"]


    published = news.get(
        "_published",
        0
    )


    # 安定ID
    news_id = make_id(
        news.get(
            "title",
            ""
        ),
        int(published)
    )


    return {

        "id": news_id,

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

        "source": primary_source,

        "sourceCount": len(
            sources
        ),

        "sources": sources,

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

            data = json.load(
                file
            )

            if not isinstance(
                data,
                dict
            ):

                return {
                    "updatedAt": "",
                    "items": []
                }

            return data


    except Exception as error:

        print(
            f"既存news.json読み込み失敗: {error}"
        )

        return {
            "updatedAt": "",
            "items": []
        }


# ============================================================
# メイン処理
# ============================================================

def main():

    print("")
    print("=" * 70)
    print("NEWS NOW ニュース収集開始")
    print("=" * 70)
    print("")


    all_news = []


    # --------------------------------------------------------
    # 全RSS取得
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


            time.sleep(
                REQUEST_INTERVAL
            )


    print("")
    print(
        f"取得したニュース総数: {len(all_news)}件"
    )


    # --------------------------------------------------------
    # URL重複削除
    # --------------------------------------------------------

    all_news = remove_url_duplicates(
        all_news
    )


    print(
        f"URL重複削除後: {len(all_news)}件"
    )


    # --------------------------------------------------------
    # 高精度重複統合
    # --------------------------------------------------------

    merged_news = merge_duplicates(
        all_news
    )


    print(
        f"同一ニュース統合後: {len(merged_news)}件"
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
    # 件数制限
    # --------------------------------------------------------

    if MAX_TOTAL_NEWS is not None:

        merged_news = merged_news[
            :MAX_TOTAL_NEWS
        ]


    # --------------------------------------------------------
    # 公開用データ
    # --------------------------------------------------------

    final_news = []

    for news in merged_news:

        final_news.append(
            finalize_news(
                news
            )
        )


    # --------------------------------------------------------
    # 取得失敗時
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

        file.write(
            "\n"
        )


    # --------------------------------------------------------
    # 統計
    # --------------------------------------------------------

    multi_source_count = sum(
        1
        for item in final_news
        if item.get(
            "sourceCount",
            1
        ) >= 2
    )


    print("")
    print("=" * 70)
    print("NEWS NOW ニュース更新完了")
    print("=" * 70)
    print(
        f"取得総数        : {len(all_news)}件"
    )
    print(
        f"統合後           : {len(final_news)}件"
    )
    print(
        f"複数媒体ニュース : {multi_source_count}件"
    )
    print(
        f"保存先           : {OUTPUT_FILE}"
    )
    print("=" * 70)
    print("")


# ============================================================
# 実行
# ============================================================

if __name__ == "__main__":
    main()
