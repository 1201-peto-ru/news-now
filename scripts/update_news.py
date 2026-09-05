#!/usr/bin/env python3

import json
import hashlib
import html
import re
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from difflib import SequenceMatcher
from urllib.parse import urlparse, quote
from html.parser import HTMLParser


# ============================================================
# NEWS NOW
#
# GoogleニュースRSSからニュースを取得
# ↓
# 重複ニュースを高精度で統合
# ↓
# 元記事ページから本物の記事説明を取得
# ↓
# 媒体名・関連記事・Googleニュースクラスタ文字列を除去
# ↓
# news.jsonへ保存
# ============================================================


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_FILE = ROOT / "news.json"


# ============================================================
# Googleニュース検索URL
# ============================================================

def google_search_url(query):
    return (
        "https://news.google.com/rss/search?"
        f"q={quote(query)}"
        "&hl=ja"
        "&gl=JP"
        "&ceid=JP:ja"
    )


# ============================================================
# ニュースフィード
# ============================================================

FEEDS = {
    "国内": [
        (
            "Google ニュース 国内",
            "https://news.google.com/rss/headlines/section/topic/NATION?hl=ja&gl=JP&ceid=JP:ja",
        ),
        (
            "Google ニュース 日本",
            google_search_url("日本 ニュース"),
        ),
    ],

    "海外": [
        (
            "Google ニュース 世界",
            "https://news.google.com/rss/headlines/section/topic/WORLD?hl=ja&gl=JP&ceid=JP:ja",
        ),
        (
            "Google ニュース 海外",
            google_search_url("海外 ニュース"),
        ),
    ],

    "IT": [
        (
            "Google ニュース IT",
            "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=ja&gl=JP&ceid=JP:ja",
        ),
        (
            "Google ニュース AI",
            google_search_url("AI テクノロジー"),
        ),
    ],

    "スポーツ": [
        (
            "Google ニュース スポーツ",
            "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=ja&gl=JP&ceid=JP:ja",
        ),
        (
            "Google ニュース スポーツ検索",
            google_search_url("スポーツ ニュース"),
        ),
    ],

    "エンタメ": [
        (
            "Google ニュース エンタメ",
            "https://news.google.com/rss/headlines/section/topic/ENTERTAINMENT?hl=ja&gl=JP&ceid=JP:ja",
        ),
        (
            "Google ニュース 芸能",
            google_search_url("芸能 エンタメ"),
        ),
    ],

    "科学": [
        (
            "Google ニュース 科学",
            google_search_url("科学 宇宙 研究"),
        ),
        (
            "Google ニュース サイエンス",
            google_search_url("科学 サイエンス"),
        ),
    ],

    "経済": [
        (
            "Google ニュース 経済",
            google_search_url("日本 経済 ニュース"),
        ),
        (
            "Google ニュース ビジネス",
            google_search_url("ビジネス 経済"),
        ),
    ],
}


# ============================================================
# 設定
# ============================================================

MAX_PER_FEED = 100

# None = 取得できたニュースをすべて保存
MAX_TOTAL_NEWS = None

# RSS取得間隔
REQUEST_INTERVAL = 0.5

# 元記事取得用
DESCRIPTION_WORKERS = 6
DESCRIPTION_TIMEOUT = 15
MAX_ARTICLE_BYTES = 1000000

USER_AGENT = (
    "Mozilla/5.0 "
    "(compatible; NEWS-NOW-NewsBot/8.0; +https://github.com/)"
)


# ============================================================
# 重複判定設定
# ============================================================

EXACT_MATCH_SCORE = 1.00
HIGH_SIMILARITY = 0.78
MEDIUM_SIMILARITY = 0.62
DUPLICATE_THRESHOLD = 0.66

STRONG_COMMON_SUBSTRING = 8
MEDIUM_COMMON_SUBSTRING = 5
IMPORTANT_TOKEN_MATCH = 0.50

MAX_NEWS_TIME_DIFF_HOURS = 72


# ============================================================
# 媒体名
# ============================================================

KNOWN_SOURCE_NAMES = [
    # 新聞
    "読売新聞",
    "朝日新聞",
    "毎日新聞",
    "日本経済新聞",
    "日経新聞",
    "産経新聞",
    "東京新聞",
    "中日新聞",
    "北海道新聞",
    "西日本新聞",
    "中国新聞",
    "神戸新聞",
    "京都新聞",

    # スポーツ
    "スポーツ報知",
    "日刊スポーツ",
    "スポニチ",
    "スポーツニッポン",
    "サンスポ",
    "サンケイスポーツ",
    "デイリースポーツ",
    "東スポ",
    "東京スポーツ",

    # テレビ・ニュース
    "NHK NEWS WEB",
    "NHK",
    "日本テレビ",
    "日テレ",
    "TBS NEWS DIG",
    "TBS",
    "テレビ朝日",
    "テレ朝",
    "フジテレビ",
    "FNNプライムオンライン",
    "FNN",
    "テレビ東京",
    "TOKYO MX",

    # 通信社
    "共同通信",
    "時事通信",
    "Reuters",
    "ロイター",
    "AP通信",

    # ネットニュース
    "Yahoo!ニュース",
    "Yahooニュース",
    "LINE NEWS",
    "gooニュース",
    "ライブドアニュース",
    "livedoorニュース",
    "MSN",
    "msn",
    "Google ニュース",

    # IT・その他
    "ITmedia NEWS",
    "ITmedia",
    "Impress Watch",
    "マイナビニュース",
    "ORICON NEWS",
    "オリコン",
    "PR TIMES",
    "CNET Japan",
    "ねとらぼ",
    "J-CASTニュース",
    "ハフポスト",
    "HuffPost",
    "弁護士ドットコム",

    # ドメイン
    "sanspo.com",
    "nikkansports.com",
    "hochi.news",
    "yomiuri.co.jp",
    "asahi.com",
    "mainichi.jp",
    "nikkei.com",
    "sankei.com",
    "newsdig.tbs.co.jp",
    "news.ntv.co.jp",
    "news.tv-asahi.co.jp",
    "fnn.jp",
    "oricon.co.jp",
]


# ============================================================
# 説明文に入れてはいけないGoogleニュース系文言
# ============================================================

UNWANTED_DESCRIPTION_PHRASES = [
    "Google ニュースで見出しと意見をもっと見る",
    "Googleニュースで見出しと意見をもっと見る",
    "で見出しと意見をもっと見る",
    "見出しと意見をもっと見る",
    "関連記事",
    "関連ニュース",
    "関連するニュース",
    "あわせて読みたい",
    "合わせて読みたい",
    "おすすめ記事",
    "おすすめニュース",
    "アクセスランキング",
    "ランキング",
    "続きを読む",
    "もっと見る",
    "ニュースをもっと見る",
]


# ============================================================
# HTML除去
# ============================================================

def clean_html(text):

    if not text:
        return ""

    text = html.unescape(str(text))

    text = re.sub(
        r"<script\b[^>]*>.*?</script>",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    text = re.sub(
        r"<style\b[^>]*>.*?</style>",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    text = re.sub(
        r"<[^>]+>",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


# ============================================================
# 媒体名除去
# ============================================================

def remove_source_names(text):

    if not text:
        return ""

    result = str(text)

    for source_name in sorted(
        KNOWN_SOURCE_NAMES,
        key=len,
        reverse=True,
    ):

        result = re.sub(
            re.escape(source_name),
            "",
            result,
            flags=re.IGNORECASE,
        )

    result = re.sub(
        r"\s+",
        " ",
        result,
    )

    return result.strip()


# ============================================================
# タイトルクリーニング
# ============================================================

def clean_title(title, source=""):

    if not title:
        return ""

    result = clean_html(title)

    if source:

        source_clean = clean_html(
            source
        ).strip()

        if source_clean:

            result = re.sub(
                rf"\s*[-－―—–|｜]\s*"
                rf"{re.escape(source_clean)}\s*$",
                "",
                result,
                flags=re.IGNORECASE,
            )

            result = re.sub(
                rf"\s*[（(]\s*"
                rf"{re.escape(source_clean)}"
                rf"\s*[）)]\s*$",
                "",
                result,
                flags=re.IGNORECASE,
            )

    result = remove_source_names(result)

    result = re.sub(
        r"\s+",
        " ",
        result,
    ).strip()

    return result


# ============================================================
# 説明文クリーニング
# ============================================================

def clean_description(text, title=""):

    if not text:
        return ""

    result = clean_html(text)

    result = html.unescape(result)

    # URL除去
    result = re.sub(
        r"https?://\S+",
        "",
        result,
        flags=re.IGNORECASE,
    )

    # Googleニュース等の不要文言
    for phrase in UNWANTED_DESCRIPTION_PHRASES:

        result = result.replace(
            phrase,
            "",
        )

    # 媒体名除去
    result = remove_source_names(
        result
    )

    # 「（スポーツ報知）」など
    result = re.sub(
        r"[（(]\s*[A-Za-z0-9ぁ-んァ-ヶ一-龯々ー・!！?？.\s]{2,40}\s*[）)]",
        "",
        result,
    )

    # 記事タイトルが説明文の先頭に丸ごと入っている場合
    clean_title_text = clean_html(
        title
    ).strip()

    if clean_title_text:

        if result.startswith(
            clean_title_text
        ):

            result = result[
                len(clean_title_text):
            ].strip(
                " \t\r\n　:：-－―—|｜"
            )

    # タイトルだけの場合は説明なし
    normalized_result = normalize_compare_text(
        result
    )

    normalized_title = normalize_compare_text(
        clean_title_text
    )

    if (
        normalized_title
        and normalized_result
        == normalized_title
    ):
        return ""

    # 関連記事らしい区切りを検出
    suspicious_markers = [
        "【",
        "】",
        "Google ニュース",
        "Googleニュース",
        "見出しと意見",
        "関連記事",
        "あわせて読みたい",
        "おすすめ記事",
        "アクセスランキング",
    ]

    suspicious_count = sum(
        1
        for marker in suspicious_markers
        if marker in result
    )

    if suspicious_count >= 2:
        return ""

    # 改行整理
    result = re.sub(
        r"[\r\n\t]+",
        " ",
        result,
    )

    result = re.sub(
        r"\s+",
        " ",
        result,
    ).strip()

    # 媒体名除去後に残る区切り
    result = re.sub(
        r"\s*[-－―—–|｜]+\s*$",
        "",
        result,
    ).strip()

    # 先頭の記号
    result = result.strip(
        " \t\r\n　-－―—|｜:："
    )

    if len(result) < 15:
        return ""

    # 異常に長い説明はクラスタ情報の可能性が高い
    if len(result) > 500:
        return ""

    # 複数媒体が残っている場合
    source_hits = 0

    lower_result = result.lower()

    for source_name in KNOWN_SOURCE_NAMES:

        if source_name.lower() in lower_result:
            source_hits += 1

    if source_hits >= 2:
        return ""

    # 関連記事が大量に連結されているような場合
    separators = [
        "　",
        " | ",
        "｜",
    ]

    long_segments = []

    for separator in separators:

        parts = [
            part.strip()
            for part in result.split(separator)
            if part.strip()
        ]

        if len(parts) >= 3:
            long_segments.extend(parts)

    if len(long_segments) >= 4:
        return ""

    # 日本語ニュースの説明として長すぎる場合は
    # 最初の1〜2文だけにする
    sentences = re.split(
        r"(?<=[。！？!?])\s*",
        result,
    )

    sentences = [
        sentence.strip()
        for sentence in sentences
        if sentence.strip()
    ]

    if len(sentences) >= 2:

        result = "".join(
            sentences[:2]
        ).strip()

    # 最終文字数
    if len(result) > 320:

        result = result[:320]

        # 途中で切れた場合
        last_end = max(
            result.rfind("。"),
            result.rfind("！"),
            result.rfind("？"),
        )

        if last_end >= 80:
            result = result[
                :last_end + 1
            ]

    if len(result) < 15:
        return ""

    return result.strip()


# ============================================================
# 比較用テキスト
# ============================================================

def normalize_compare_text(text):

    if not text:
        return ""

    text = clean_html(text)

    text = remove_source_names(text)

    text = text.lower()

    text = re.sub(
        r"https?://\S+",
        "",
        text,
    )

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
        "独自",
        "緊急",
    ]

    for word in remove_words:

        text = text.replace(
            word,
            "",
        )

    text = text.translate(
        str.maketrans(
            "０１２３４５６７８９",
            "0123456789",
        )
    )

    text = re.sub(
        r"[「」『』【】（）()\[\]［］"
        r"<>＜＞"
        r".,，。！？!?：:；;・"
        r"/／\\\-—–_~〜"
        r"\"“”‘’']",
        "",
        text,
    )

    text = re.sub(
        r"\s+",
        "",
        text,
    )

    return text.strip()


# ============================================================
# 比較用タイトル
# ============================================================

def compact_title(text):

    text = normalize_compare_text(
        text
    )

    for char in "はがをにへとでのもや":

        text = text.replace(
            char,
            "",
        )

    return text


# ============================================================
# 数字抽出
# ============================================================

def extract_numbers(text):

    normalized = normalize_compare_text(
        text
    )

    if not normalized:
        return set()

    return set(
        re.findall(
            r"\d+",
            normalized,
        )
    )


# ============================================================
# 年齢抽出
# ============================================================

def extract_ages(text):

    text = clean_html(text)

    ages = set()

    for pattern in [
        r"(\d{1,3})歳",
        r"(\d{1,3})才",
    ]:

        for match in re.findall(
            pattern,
            text,
        ):

            ages.add(match)

    return ages


# ============================================================
# N-Gram
# ============================================================

def make_ngrams(text, size=2):

    text = compact_title(text)

    if not text:
        return set()

    if len(text) <= size:
        return {text}

    return {
        text[index:index + size]
        for index in range(
            len(text) - size + 1
        )
    }


# ============================================================
# Jaccard
# ============================================================

def jaccard_similarity(
    set_a,
    set_b,
):

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


# ============================================================
# 重要チャンク
# ============================================================

def extract_significant_chunks(title):

    normalized = compact_title(
        title
    )

    chunks = set()

    if len(normalized) < 3:
        return chunks

    for size in range(3, 13):

        if len(normalized) < size:
            continue

        for index in range(
            len(normalized) - size + 1
        ):

            chunk = normalized[
                index:index + size
            ]

            if re.fullmatch(
                r"[0-9]+",
                chunk,
            ):
                continue

            chunks.add(chunk)

    return chunks


# ============================================================
# コア情報一致
# ============================================================

def same_core_information(
    news_a,
    news_b,
):

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

    if not common:
        return 0.0

    weighted_common = sum(
        len(chunk)
        for chunk in common
    )

    total_a = sum(
        len(chunk)
        for chunk in chunks_a
    )

    total_b = sum(
        len(chunk)
        for chunk in chunks_b
    )

    smaller_total = min(
        total_a,
        total_b,
    )

    if smaller_total <= 0:
        return 0.0

    return min(
        weighted_common / smaller_total,
        1.0,
    )


# ============================================================
# 最長共通文字列
# ============================================================

def longest_common_substring_length(
    a,
    b,
):

    a = compact_title(a)
    b = compact_title(b)

    if not a or not b:
        return 0

    previous = [0] * (
        len(b) + 1
    )

    longest = 0

    for char_a in a:

        current = [0] * (
            len(b) + 1
        )

        for index, char_b in enumerate(
            b,
            start=1,
        ):

            if char_a == char_b:

                current[index] = (
                    previous[index - 1] + 1
                )

                longest = max(
                    longest,
                    current[index],
                )

        previous = current

    return longest


# ============================================================
# タイトル包含
# ============================================================

def title_containment_score(
    title_a,
    title_b,
):

    a = compact_title(title_a)
    b = compact_title(title_b)

    if not a or not b:
        return 0.0

    if a == b:
        return 1.0

    shorter = min(
        len(a),
        len(b),
    )

    if shorter < 5:
        return 0.0

    if a in b or b in a:
        return 1.0

    common_length = (
        longest_common_substring_length(
            a,
            b,
        )
    )

    return common_length / shorter


# ============================================================
# 重要語一致
# ============================================================

def extract_keyword_chunks(title):

    text = compact_title(title)

    if not text:
        return set()

    chunks = set()

    for size in range(4, 9):

        if len(text) < size:
            continue

        for index in range(
            len(text) - size + 1
        ):

            chunk = text[
                index:index + size
            ]

            if re.fullmatch(
                r"[0-9]+",
                chunk,
            ):
                continue

            chunks.add(chunk)

    return chunks


def important_token_score(
    title_a,
    title_b,
):

    tokens_a = extract_keyword_chunks(
        title_a
    )

    tokens_b = extract_keyword_chunks(
        title_b
    )

    if not tokens_a or not tokens_b:
        return 0.0

    common = tokens_a.intersection(
        tokens_b
    )

    if not common:
        return 0.0

    smaller = min(
        len(tokens_a),
        len(tokens_b),
    )

    if smaller <= 0:
        return 0.0

    return len(common) / smaller


# ============================================================
# 数字一致
# ============================================================

def number_similarity(
    title_a,
    title_b,
):

    numbers_a = extract_numbers(
        title_a
    )

    numbers_b = extract_numbers(
        title_b
    )

    if not numbers_a or not numbers_b:
        return 0.5

    if numbers_a.intersection(
        numbers_b
    ):
        return 1.0

    return 0.0


# ============================================================
# 年齢一致
# ============================================================

def age_similarity(
    title_a,
    title_b,
):

    ages_a = extract_ages(
        title_a
    )

    ages_b = extract_ages(
        title_b
    )

    if not ages_a or not ages_b:
        return 0.5

    if ages_a.intersection(
        ages_b
    ):
        return 1.0

    return 0.0


# ============================================================
# タイトル類似度
# ============================================================

def title_similarity(
    title_a,
    title_b,
):

    a = normalize_compare_text(
        title_a
    )

    b = normalize_compare_text(
        title_b
    )

    if not a or not b:
        return 0.0

    if a == b:
        return 1.0

    if len(a) >= 8 and a in b:
        return 0.98

    if len(b) >= 8 and b in a:
        return 0.98

    sequence_score = SequenceMatcher(
        None,
        a,
        b,
    ).ratio()

    bigram_score = jaccard_similarity(
        make_ngrams(a, 2),
        make_ngrams(b, 2),
    )

    trigram_score = jaccard_similarity(
        make_ngrams(a, 3),
        make_ngrams(b, 3),
    )

    score = (
        sequence_score * 0.50
        + bigram_score * 0.30
        + trigram_score * 0.20
    )

    return max(
        sequence_score * 0.90,
        score,
    )


# ============================================================
# 時間一致
# ============================================================

def time_similarity(
    news_a,
    news_b,
):

    time_a = news_a.get(
        "_published",
        0,
    )

    time_b = news_b.get(
        "_published",
        0,
    )

    if not time_a or not time_b:
        return 0.5

    diff_hours = abs(
        time_a - time_b
    ) / 3600

    if diff_hours <= 3:
        return 1.0

    if diff_hours <= 12:
        return 0.9

    if diff_hours <= 24:
        return 0.8

    if diff_hours <= 48:
        return 0.65

    if diff_hours <= MAX_NEWS_TIME_DIFF_HOURS:
        return 0.5

    return 0.2


# ============================================================
# 同一ニューススコア
# ============================================================

def same_news_score(
    news_a,
    news_b,
):

    title_a = news_a.get(
        "title",
        "",
    )

    title_b = news_b.get(
        "title",
        "",
    )

    similarity = title_similarity(
        title_a,
        title_b,
    )

    core_score = same_core_information(
        news_a,
        news_b,
    )

    containment_score = (
        title_containment_score(
            title_a,
            title_b,
        )
    )

    keyword_score = (
        important_token_score(
            title_a,
            title_b,
        )
    )

    number_score = number_similarity(
        title_a,
        title_b,
    )

    age_score = age_similarity(
        title_a,
        title_b,
    )

    time_score = time_similarity(
        news_a,
        news_b,
    )

    common_length = (
        longest_common_substring_length(
            title_a,
            title_b,
        )
    )

    normalized_a = compact_title(
        title_a
    )

    normalized_b = compact_title(
        title_b
    )

    if normalized_a == normalized_b:
        return EXACT_MATCH_SCORE

    if containment_score >= 0.85:

        if common_length >= MEDIUM_COMMON_SUBSTRING:
            return 0.95

    if (
        common_length >= STRONG_COMMON_SUBSTRING
        and keyword_score >= 0.35
    ):

        return max(
            0.90,
            (
                containment_score * 0.35
                + keyword_score * 0.30
                + similarity * 0.35
            ),
        )

    if similarity >= HIGH_SIMILARITY:

        return max(
            0.88,
            similarity,
        )

    if (
        similarity >= MEDIUM_SIMILARITY
        and (
            core_score >= 0.45
            or keyword_score >= IMPORTANT_TOKEN_MATCH
        )
    ):

        return max(
            0.80,
            (
                similarity * 0.35
                + core_score * 0.30
                + keyword_score * 0.25
                + containment_score * 0.10
            ),
        )

    if (
        common_length >= MEDIUM_COMMON_SUBSTRING
        and core_score >= 0.35
        and keyword_score >= 0.25
    ):

        return max(
            0.72,
            (
                similarity * 0.25
                + core_score * 0.35
                + keyword_score * 0.25
                + containment_score * 0.15
            ),
        )

    score = (
        similarity * 0.30
        + core_score * 0.25
        + containment_score * 0.20
        + keyword_score * 0.15
        + number_score * 0.04
        + age_score * 0.03
        + time_score * 0.03
    )

    return min(
        score,
        1.0,
    )


# ============================================================
# 同じニュースか
# ============================================================

def are_same_news(
    news_a,
    news_b,
):

    url_a = news_a.get(
        "url",
        "",
    )

    url_b = news_b.get(
        "url",
        "",
    )

    if (
        url_a
        and url_b
        and normalize_url(url_a)
        == normalize_url(url_b)
    ):
        return True

    return (
        same_news_score(
            news_a,
            news_b,
        )
        >= DUPLICATE_THRESHOLD
    )


# ============================================================
# ID
# ============================================================

def make_id(
    title,
    published,
):

    normalized = normalize_compare_text(
        title
    )

    hour = (
        int(published // 3600)
        if published
        else 0
    )

    value = (
        f"{normalized}|{hour}"
    ).encode(
        "utf-8"
    )

    return hashlib.sha256(
        value
    ).hexdigest()[:16]


# ============================================================
# 日付
# ============================================================

def parse_date(
    date_text,
):

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


def format_japan_date(
    date_text,
):

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

def fetch_feed(
    url,
):

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "application/rss+xml, "
                "application/atom+xml, "
                "application/xml, "
                "text/xml, */*"
            ),
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=30,
    ) as response:

        return response.read()


# ============================================================
# XML
# ============================================================

def find_child_text(
    element,
    names,
):

    for child in element:

        tag = child.tag.split(
            "}"
        )[-1]

        if tag in names:

            if child.text:
                return child.text.strip()

    return ""


def get_atom_link(
    element,
):

    for child in element:

        tag = child.tag.split(
            "}"
        )[-1]

        if tag != "link":
            continue

        href = child.attrib.get(
            "href",
            "",
        ).strip()

        if href:
            return href

        if child.text:
            return child.text.strip()

    return ""


# ============================================================
# RSSニュース取得
#
# 重要:
# GoogleニュースRSSのdescriptionは
# 絶対に使用しない。
# ============================================================

def fetch_feed_items(
    category,
    feed_name,
    feed_url,
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

        channel = None

        for element in root.iter():

            if element.tag.split(
                "}"
            )[-1] == "channel":

                channel = element
                break

        if channel is not None:

            item_elements = [
                element
                for element in channel
                if element.tag.split(
                    "}"
                )[-1] == "item"
            ]

        else:

            item_elements = [
                element
                for element in root
                if element.tag.split(
                    "}"
                )[-1] == "entry"
            ]

        results = []

        for item in item_elements:

            original_title = clean_html(
                find_child_text(
                    item,
                    {"title"},
                )
            )

            if not original_title:
                continue

            link = find_child_text(
                item,
                {"link"},
            )

            if not link:

                link = get_atom_link(
                    item
                )

            link = link.strip()

            if not link:
                continue

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

            clean_article_title = clean_title(
                original_title,
                source,
            )

            if not clean_article_title:
                continue

            pub_date = find_child_text(
                item,
                {
                    "pubDate",
                    "published",
                    "updated",
                },
            )

            published = parse_date(
                pub_date
            )

            results.append(
                {
                    "category": category,
                    "title": clean_article_title,
                    "description": "",
                    "date": format_japan_date(
                        pub_date
                    ),
                    "url": link,
                    "_published": (
                        published.timestamp()
                        if published
                        else 0
                    ),
                }
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
# カテゴリー
# ============================================================

def choose_category(
    base,
    duplicate,
):

    priority = {
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
        "国内",
    )

    duplicate_category = duplicate.get(
        "category",
        "国内",
    )

    if (
        priority.get(
            duplicate_category,
            0,
        )
        >
        priority.get(
            base_category,
            0,
        )
    ):

        return duplicate_category

    return base_category


# ============================================================
# タイトル品質
# ============================================================

def title_quality(
    title,
):

    if not title:
        return 0

    text = clean_title(
        title
    )

    length = len(
        normalize_compare_text(text)
    )

    if length == 0:
        return 0

    if 15 <= length <= 45:
        score = 100

    elif 10 <= length <= 60:
        score = 80

    else:
        score = 50

    if re.search(
        r"\d+歳",
        text,
    ):
        score += 5

    important_words = [
        "起訴",
        "逮捕",
        "判決",
        "殺害",
        "事故",
        "事件",
        "発表",
        "決定",
        "優勝",
        "首相",
    ]

    for word in important_words:

        if word in text:
            score += 2

    return score


# ============================================================
# ニュース統合
# ============================================================

def merge_news_items(
    base,
    duplicate,
):

    base_title = base.get(
        "title",
        "",
    )

    duplicate_title = duplicate.get(
        "title",
        "",
    )

    if (
        title_quality(duplicate_title)
        >
        title_quality(base_title)
    ):

        base["title"] = duplicate_title

    if (
        duplicate.get(
            "_published",
            0,
        )
        >
        base.get(
            "_published",
            0,
        )
    ):

        base["date"] = duplicate.get(
            "date",
            base.get(
                "date",
                "",
            ),
        )

        base["_published"] = duplicate.get(
            "_published",
            base.get(
                "_published",
                0,
            ),
        )

        base["url"] = duplicate.get(
            "url",
            base.get(
                "url",
                "",
            ),
        )

    base["category"] = choose_category(
        base,
        duplicate,
    )

    # 説明文は重複統合後に元記事から取得する
    base["description"] = ""

    return base


# ============================================================
# URL正規化
# ============================================================

def normalize_url(
    url,
):

    if not url:
        return ""

    url = url.strip()

    try:

        parsed = urlparse(
            url
        )

        if not parsed.scheme:
            return url

        normalized = (
            f"{parsed.scheme.lower()}://"
            f"{parsed.netloc.lower()}"
            f"{parsed.path}"
        )

        return normalized.rstrip(
            "/"
        )

    except Exception:

        return url


# ============================================================
# URL重複削除
# ============================================================

def remove_url_duplicates(
    news_list,
):

    unique = {}

    for news in news_list:

        key = normalize_url(
            news.get(
                "url",
                "",
            )
        )

        if not key:

            key = (
                "title:"
                + normalize_compare_text(
                    news.get(
                        "title",
                        "",
                    )
                )
            )

        if key not in unique:

            unique[key] = news

        else:

            merge_news_items(
                unique[key],
                news,
            )

    return list(
        unique.values()
    )


# ============================================================
# クラスタ統合
# ============================================================

def merge_duplicates(
    news_list,
):

    news_list.sort(
        key=lambda item: item.get(
            "_published",
            0,
        ),
        reverse=True,
    )

    clusters = []

    for news in news_list:

        best_cluster_index = None
        best_score = 0.0

        for index, cluster in enumerate(
            clusters
        ):

            representative = cluster[
                "representative"
            ]

            score = same_news_score(
                representative,
                news,
            )

            for member in cluster[
                "members"
            ]:

                member_score = (
                    same_news_score(
                        member,
                        news,
                    )
                )

                score = max(
                    score,
                    member_score,
                )

            if score > best_score:

                best_score = score
                best_cluster_index = index

        if (
            best_cluster_index
            is not None
            and best_score
            >= DUPLICATE_THRESHOLD
        ):

            cluster = clusters[
                best_cluster_index
            ]

            cluster[
                "members"
            ].append(
                news
            )

            merge_news_items(
                cluster[
                    "representative"
                ],
                news,
            )

        else:

            clusters.append(
                {
                    "representative": dict(
                        news
                    ),
                    "members": [
                        news
                    ],
                }
            )

    return [
        cluster["representative"]
        for cluster in clusters
    ]


# ============================================================
# 元記事HTML解析
# ============================================================

class ArticleMetaParser(
    HTMLParser
):

    def __init__(self):

        super().__init__(
            convert_charrefs=True
        )

        self.meta_descriptions = []

        self.jsonld_blocks = []

        self._inside_jsonld = False
        self._jsonld_buffer = []

    def handle_starttag(
        self,
        tag,
        attrs,
    ):

        tag = tag.lower()

        attrs_dict = {
            str(key).lower(): (
                value or ""
            )
            for key, value in attrs
        }

        if tag == "meta":

            name = (
                attrs_dict.get(
                    "name",
                    "",
                )
                or attrs_dict.get(
                    "property",
                    "",
                )
            ).lower().strip()

            content = (
                attrs_dict.get(
                    "content",
                    "",
                )
                or ""
            ).strip()

            if name in {
                "description",
                "og:description",
                "twitter:description",
            } and content:

                self.meta_descriptions.append(
                    (
                        name,
                        content,
                    )
                )

        elif tag == "script":

            script_type = (
                attrs_dict.get(
                    "type",
                    "",
                )
                .lower()
                .strip()
            )

            if (
                script_type
                == "application/ld+json"
            ):

                self._inside_jsonld = True
                self._jsonld_buffer = []

    def handle_data(
        self,
        data,
    ):

        if self._inside_jsonld:

            self._jsonld_buffer.append(
                data
            )

    def handle_endtag(
        self,
        tag,
    ):

        if (
            tag.lower()
            == "script"
            and self._inside_jsonld
        ):

            self.jsonld_blocks.append(
                "".join(
                    self._jsonld_buffer
                )
            )

            self._inside_jsonld = False
            self._jsonld_buffer = []


# ============================================================
# JSON-LD description抽出
# ============================================================

def extract_jsonld_descriptions(
    value,
):

    results = []

    if isinstance(
        value,
        dict,
    ):

        description = value.get(
            "description"
        )

        if isinstance(
            description,
            str,
        ):

            results.append(
                description
            )

        for child in value.values():

            results.extend(
                extract_jsonld_descriptions(
                    child
                )
            )

    elif isinstance(
        value,
        list,
    ):

        for child in value:

            results.extend(
                extract_jsonld_descriptions(
                    child
                )
            )

    return results


# ============================================================
# 元記事説明取得
# ============================================================

def fetch_article_description(
    url,
    title,
):

    if not url:
        return ""

    parsed = urlparse(
        url
    )

    if parsed.scheme.lower() not in {
        "http",
        "https",
    }:

        return ""

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,"
                "application/xhtml+xml,"
                "application/xml;q=0.9,"
                "*/*;q=0.8"
            ),
            "Accept-Language": "ja,en-US;q=0.8,en;q=0.5",
        },
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=DESCRIPTION_TIMEOUT,
        ) as response:

            data = response.read(
                MAX_ARTICLE_BYTES
            )

        # 大半の日本語サイトはUTF-8
        try:

            page = data.decode(
                "utf-8"
            )

        except UnicodeDecodeError:

            page = data.decode(
                "cp932",
                errors="ignore",
            )

        parser = ArticleMetaParser()

        try:

            parser.feed(
                page
            )

        except Exception:

            pass

        # ----------------------------------------------------
        # 優先順位
        #
        # 1. og:description
        # 2. description
        # 3. twitter:description
        # 4. JSON-LD
        # ----------------------------------------------------

        candidates = []

        for name, content in (
            parser.meta_descriptions
        ):

            priority = {
                "og:description": 0,
                "description": 1,
                "twitter:description": 2,
            }.get(
                name,
                9,
            )

            candidates.append(
                (
                    priority,
                    content,
                )
            )

        candidates.sort(
            key=lambda item: item[0]
        )

        for _, candidate in candidates:

            cleaned = clean_description(
                candidate,
                title,
            )

            if cleaned:

                return cleaned

        # ----------------------------------------------------
        # JSON-LD
        # ----------------------------------------------------

        for block in parser.jsonld_blocks:

            try:

                parsed_json = json.loads(
                    block
                )

                descriptions = (
                    extract_jsonld_descriptions(
                        parsed_json
                    )
                )

                for candidate in descriptions:

                    cleaned = clean_description(
                        candidate,
                        title,
                    )

                    if cleaned:

                        return cleaned

            except Exception:

                continue

        return ""

    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        Exception,
    ):

        return ""


# ============================================================
# 説明文を一括取得
# ============================================================

def enrich_descriptions(
    news_list,
):

    if not news_list:
        return news_list

    print("")
    print(
        "=" * 70
    )
    print(
        "元記事から説明文を取得しています"
    )
    print(
        "=" * 70
    )
    print("")

    success_count = 0
    failed_count = 0

    with ThreadPoolExecutor(
        max_workers=DESCRIPTION_WORKERS
    ) as executor:

        future_map = {}

        for index, news in enumerate(
            news_list
        ):

            future = executor.submit(
                fetch_article_description,
                news.get(
                    "url",
                    "",
                ),
                news.get(
                    "title",
                    "",
                ),
            )

            future_map[
                future
            ] = index

        for future in as_completed(
            future_map
        ):

            index = future_map[
                future
            ]

            news = news_list[
                index
            ]

            try:

                description = future.result()

            except Exception:

                description = ""

            news[
                "description"
            ] = description

            if description:

                success_count += 1

            else:

                failed_count += 1

            completed = (
                success_count
                + failed_count
            )

            if (
                completed % 25 == 0
                or completed == len(news_list)
            ):

                print(
                    f"  説明取得: "
                    f"{completed}/{len(news_list)} "
                    f"(成功 {success_count}件)"
                )

    print("")
    print(
        f"説明文取得成功: {success_count}件"
    )
    print(
        f"説明文取得失敗/なし: {failed_count}件"
    )

    return news_list


# ============================================================
# 公開用データ
# ============================================================

def finalize_news(
    news,
):

    title = clean_title(
        news.get(
            "title",
            "",
        )
    )

    if not title:
        return None

    description = clean_description(
        news.get(
            "description",
            "",
        ),
        title,
    )

    published = news.get(
        "_published",
        0,
    )

    return {
        "id": make_id(
            title,
            published,
        ),
        "category": news.get(
            "category",
            "総合",
        ),
        "title": title,
        "description": description,
        "date": news.get(
            "date",
            "",
        ),
        "url": news.get(
            "url",
            "",
        ),
    }


# ============================================================
# 最終安全チェック
# ============================================================

def final_safety_clean(
    news,
):

    if not news:
        return None

    title = clean_title(
        str(
            news.get(
                "title",
                "",
            )
        )
    )

    if not title:
        return None

    description = clean_description(
        str(
            news.get(
                "description",
                "",
            )
        ),
        title,
    )

    return {
        "id": str(
            news.get(
                "id",
                "",
            )
        ),
        "category": str(
            news.get(
                "category",
                "総合",
            )
        ),
        "title": title,
        "description": description,
        "date": str(
            news.get(
                "date",
                "",
            )
        ),
        "url": str(
            news.get(
                "url",
                "",
            )
        ),
    }


# ============================================================
# 既存ニュース
# ============================================================

def load_existing_news():

    if not OUTPUT_FILE.exists():

        return {
            "updatedAt": "",
            "items": [],
        }

    try:

        with open(
            OUTPUT_FILE,
            "r",
            encoding="utf-8",
        ) as file:

            data = json.load(
                file
            )

            if isinstance(
                data,
                dict,
            ):

                return data

    except Exception as error:

        print(
            f"既存news.json読み込み失敗: {error}"
        )

    return {
        "updatedAt": "",
        "items": [],
    }


# ============================================================
# メイン
# ============================================================

def main():

    print("")
    print(
        "=" * 70
    )
    print(
        "NEWS NOW ニュース収集開始"
    )
    print(
        "=" * 70
    )
    print("")

    all_news = []

    # ========================================================
    # RSS取得
    # ========================================================

    for category, feeds in FEEDS.items():

        print("")
        print(
            f"===== {category} ====="
        )

        for feed_name, feed_url in feeds:

            items = fetch_feed_items(
                category,
                feed_name,
                feed_url,
            )

            all_news.extend(
                items
            )

            time.sleep(
                REQUEST_INTERVAL
            )

    print("")
    print(
        f"取得したニュース総数: "
        f"{len(all_news)}件"
    )

    if not all_news:

        existing = load_existing_news()

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

    # ========================================================
    # URL重複
    # ========================================================

    all_news = remove_url_duplicates(
        all_news
    )

    print(
        f"URL重複削除後: "
        f"{len(all_news)}件"
    )

    # ========================================================
    # ニュース統合
    # ========================================================

    merged_news = merge_duplicates(
        all_news
    )

    print(
        f"高精度ニュース統合後: "
        f"{len(merged_news)}件"
    )

    # ========================================================
    # 新しい順
    # ========================================================

    merged_news.sort(
        key=lambda item: item.get(
            "_published",
            0,
        ),
        reverse=True,
    )

    # ========================================================
    # 件数制限
    # ========================================================

    if MAX_TOTAL_NEWS is not None:

        merged_news = merged_news[
            :MAX_TOTAL_NEWS
        ]

    # ========================================================
    # 元記事から説明文取得
    #
    # ここが今回の重要部分
    # ========================================================

    merged_news = enrich_descriptions(
        merged_news
    )

    # ========================================================
    # 公開用データ
    # ========================================================

    final_news = []

    for news in merged_news:

        public_item = finalize_news(
            news
        )

        if not public_item:
            continue

        public_item = final_safety_clean(
            public_item
        )

        if not public_item:
            continue

        if not public_item.get(
            "title",
            "",
        ):
            continue

        if not public_item.get(
            "url",
            "",
        ):
            continue

        final_news.append(
            public_item
        )

    # ========================================================
    # 取得失敗時
    # ========================================================

    existing = load_existing_news()

    if not final_news:

        print("")
        print(
            "公開できるニュースがありません。"
        )

        if existing.get(
            "items"
        ):

            print(
                "既存のnews.jsonを維持します。"
            )

        return

    # ========================================================
    # 保存
    # ========================================================

    now = datetime.now(
        timezone.utc
    ).astimezone()

    output = {
        "updatedAt": now.isoformat(),
        "total": len(final_news),
        "items": final_news,
    }

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            output,
            file,
            ensure_ascii=False,
            indent=2,
        )

        file.write(
            "\n"
        )

    # ========================================================
    # 最終確認
    # ========================================================

    source_field_count = 0
    remaining_source_names = 0
    description_count = 0

    for item in final_news:

        if (
            "source" in item
            or "sources" in item
            or "sourceCount" in item
            or "_source" in item
        ):

            source_field_count += 1

        if item.get(
            "description",
            "",
        ):

            description_count += 1

        combined_text = (
            item.get(
                "title",
                "",
            )
            + " "
            + item.get(
                "description",
                "",
            )
        )

        for source_name in KNOWN_SOURCE_NAMES:

            if (
                source_name.lower()
                in combined_text.lower()
            ):

                remaining_source_names += 1

                break

    # ========================================================
    # 完了
    # ========================================================

    print("")
    print(
        "=" * 70
    )
    print(
        "NEWS NOW ニュース更新完了"
    )
    print(
        "=" * 70
    )

    print(
        f"取得総数             : "
        f"{len(all_news)}件"
    )

    print(
        f"統合後               : "
        f"{len(final_news)}件"
    )

    print(
        f"説明文取得済み       : "
        f"{description_count}件"
    )

    print(
        "重複判定方式         : "
        "高精度クラスタ統合"
    )

    print(
        "Google RSS説明文     : "
        "使用しない"
    )

    print(
        "関連記事連結         : "
        "使用しない"
    )

    print(
        "媒体情報公開         : "
        "なし"
    )

    print(
        f"source関連キー       : "
        f"{source_field_count}件"
    )

    print(
        f"媒体名残存確認       : "
        f"{remaining_source_names}件"
    )

    print(
        f"保存先               : "
        f"{OUTPUT_FILE}"
    )

    print(
        "=" * 70
    )
    print("")


# ============================================================
# 実行
# ============================================================

if __name__ == "__main__":
    main()
