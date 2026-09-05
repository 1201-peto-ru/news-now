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
from urllib.parse import urlparse, quote


# ============================================================
# NEWS NOW
# ニュース収集・高精度重複ニュース統合システム
#
# 改良版:
#
# ・URL完全一致
# ・タイトル完全一致
# ・タイトル包含判定
# ・SequenceMatcher
# ・N-Gram Jaccard
# ・共通連続文字列
# ・重要語比較
# ・数字 / 年齢 / 地名 / 人物情報
# ・ニュースクラスタ統合
#
# GoogleニュースRSSでは、
# 同じ事件について媒体ごとに異なるタイトルが付きます。
#
# 例:
#
# 相模原の高3殺害事件 19歳を起訴
# 河川敷で元交際相手の女子高校生を殺害の罪
# 【速報】高3殺害で元交際相手19歳起訴、氏名公表
# 逆送の19歳男、殺人罪で起訴
#
# これらを可能な限り
# 「同じニュース」として1件に統合します。
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

# Noneなら取得できたニュースをすべて保存
MAX_TOTAL_NEWS = None

# RSS取得間隔
REQUEST_INTERVAL = 0.5

# HTTP User-Agent
USER_AGENT = (
    "Mozilla/5.0 "
    "(compatible; NEWS-NOW-NewsBot/7.0)"
)


# ============================================================
# 重複判定設定
# ============================================================

# 完全一致
EXACT_MATCH_SCORE = 1.00

# 高類似
HIGH_SIMILARITY = 0.78

# 中類似
MEDIUM_SIMILARITY = 0.62

# 最終統合閾値
DUPLICATE_THRESHOLD = 0.66

# 強い共通文字列
STRONG_COMMON_SUBSTRING = 8

# 中程度の共通文字列
MEDIUM_COMMON_SUBSTRING = 5

# 重要語の一致率
IMPORTANT_TOKEN_MATCH = 0.50

# 日付が大きく離れた記事は
# 同じニュースとして扱いにくくする
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
# HTML除去
# ============================================================

def clean_html(text):

    if not text:
        return ""

    text = html.unescape(text)

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

    result = text

    source_names = sorted(
        KNOWN_SOURCE_NAMES,
        key=len,
        reverse=True,
    )

    for source_name in source_names:

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
# タイトルの媒体名除去
# ============================================================

def clean_title(title, source=""):

    if not title:
        return ""

    result = clean_html(title)

    # source欄の媒体名を削除
    if source:

        source_clean = clean_html(source).strip()

        if source_clean:

            result = re.sub(
                rf"\s*[-－―—–|｜]\s*"
                rf"{re.escape(source_clean)}\s*$",
                "",
                result,
                flags=re.IGNORECASE,
            )

    result = remove_source_names(result)

    # Googleニュースなどで残る
    # 「 - 媒体名」形式を削除
    result = re.sub(
        r"\s*[-－―—–|｜]\s*"
        r"[A-Za-z0-9ぁ-んァ-ヶ一-龯々ー・!！?？.．]+"
        r"\s*$",
        lambda match: (
            ""
            if len(match.group(0)) <= 40
            else match.group(0)
        ),
        result,
    )

    result = re.sub(
        r"\s+",
        " ",
        result,
    ).strip()

    return result


# ============================================================
# テキスト正規化
# ============================================================

def normalize_text(text):

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

    # ニュースの意味にほぼ影響しない語
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

    text = normalize_text(text)

    remove_chars = (
        "はがをにへとでのもや"
    )

    for char in remove_chars:

        text = text.replace(
            char,
            "",
        )

    return text


# ============================================================
# 数字情報抽出
#
# 19歳
# 6月
# 2026年
# 第3戦
#
# 同じニュースかどうかの
# 補助情報として使用
# ============================================================

def extract_numbers(text):

    normalized = normalize_text(text)

    if not normalized:
        return set()

    numbers = set(
        re.findall(
            r"\d+",
            normalized,
        )
    )

    return numbers


# ============================================================
# 年齢抽出
# ============================================================

def extract_ages(text):

    text = clean_html(text)

    ages = set()

    patterns = [
        r"(\d{1,3})歳",
        r"(\d{1,3})才",
    ]

    for pattern in patterns:

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
# Jaccard類似度
# ============================================================

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


# ============================================================
# 重要な文字列チャンク
#
# 例:
#
# 相模原の高3殺害事件
# 高3殺害
# 元交際相手
# 19歳男
# 殺人罪
# 横浜地検
#
# ============================================================

def extract_significant_chunks(title):

    normalized = compact_title(title)

    chunks = set()

    if len(normalized) < 3:
        return chunks

    # 3文字〜12文字
    for size in range(3, 13):

        if len(normalized) < size:
            continue

        for index in range(
            len(normalized) - size + 1
        ):

            chunk = normalized[
                index:index + size
            ]

            # 数字だけは除外
            if re.fullmatch(
                r"[0-9]+",
                chunk,
            ):
                continue

            chunks.add(chunk)

    return chunks


# ============================================================
# 重要チャンク一致率
# ============================================================

def same_core_information(news_a, news_b):

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
# 最長共通連続文字列
#
# タイトルの途中に
# 同じ事件名や人物名が含まれる場合を検出
# ============================================================

def longest_common_substring_length(a, b):

    a = compact_title(a)
    b = compact_title(b)

    if not a or not b:
        return 0

    # DP配列
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
# タイトル包含率
#
# 短いタイトルが
# 長いタイトルにかなり含まれている場合を検出
# ============================================================

def title_containment_score(title_a, title_b):

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

    if a in b:
        return 1.0

    if b in a:
        return 1.0

    # 共通文字列の割合
    common_length = (
        longest_common_substring_length(
            a,
            b,
        )
    )

    return common_length / shorter


# ============================================================
# 重要語抽出
#
# 日本語は空白がないため、
# 文字N-Gramを使用して
# 重要な情報の重なりを検出
# ============================================================

def extract_keyword_chunks(title):

    text = compact_title(title)

    if not text:
        return set()

    chunks = set()

    # 4〜8文字を重要語として扱う
    for size in range(4, 9):

        if len(text) < size:
            continue

        for index in range(
            len(text) - size + 1
        ):

            chunk = text[
                index:index + size
            ]

            # 数字だけ除外
            if re.fullmatch(
                r"[0-9]+",
                chunk,
            ):
                continue

            chunks.add(chunk)

    return chunks


# ============================================================
# 重要語一致率
# ============================================================

def important_token_score(title_a, title_b):

    tokens_a = extract_keyword_chunks(
        title_a
    )

    tokens_b = extract_keyword_chunks(
        title_b
    )

    if not tokens_a or not tokens_b:
        return 0.0

    common = (
        tokens_a.intersection(
            tokens_b
        )
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
# 数字情報一致
# ============================================================

def number_similarity(title_a, title_b):

    numbers_a = extract_numbers(
        title_a
    )

    numbers_b = extract_numbers(
        title_b
    )

    if not numbers_a or not numbers_b:
        return 0.5

    common = (
        numbers_a.intersection(
            numbers_b
        )
    )

    if common:
        return 1.0

    return 0.0


# ============================================================
# 年齢一致
# ============================================================

def age_similarity(title_a, title_b):

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

def title_similarity(title_a, title_b):

    a = normalize_text(title_a)
    b = normalize_text(title_b)

    if not a or not b:
        return 0.0

    if a == b:
        return 1.0

    # 片方がもう片方に含まれる
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
# 公開日時の近さ
# ============================================================

def time_similarity(news_a, news_b):

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
# ニュース同一性スコア
# ============================================================

def same_news_score(news_a, news_b):

    title_a = news_a.get(
        "title",
        "",
    )

    title_b = news_b.get(
        "title",
        "",
    )

    # --------------------------------------------------------
    # 基本比較
    # --------------------------------------------------------

    similarity = title_similarity(
        title_a,
        title_b,
    )

    core_score = same_core_information(
        news_a,
        news_b,
    )

    containment_score = title_containment_score(
        title_a,
        title_b,
    )

    keyword_score = important_token_score(
        title_a,
        title_b,
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

    # --------------------------------------------------------
    # 完全一致
    # --------------------------------------------------------

    if normalized_a == normalized_b:

        return EXACT_MATCH_SCORE

    # --------------------------------------------------------
    # 強いタイトル包含
    # --------------------------------------------------------

    if containment_score >= 0.85:

        if (
            common_length
            >= MEDIUM_COMMON_SUBSTRING
        ):
            return 0.95

    # --------------------------------------------------------
    # 非常に強い共通情報
    # --------------------------------------------------------

    if (
        common_length
        >= STRONG_COMMON_SUBSTRING
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

    # --------------------------------------------------------
    # 高類似
    # --------------------------------------------------------

    if similarity >= HIGH_SIMILARITY:

        return max(
            0.88,
            similarity,
        )

    # --------------------------------------------------------
    # 中類似 +
    # 重要情報一致
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # 共通連続文字列が強い
    # --------------------------------------------------------

    if (
        common_length
        >= MEDIUM_COMMON_SUBSTRING
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

    # --------------------------------------------------------
    # 通常スコア
    # --------------------------------------------------------

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
# 同じニュースか判定
# ============================================================

def are_same_news(news_a, news_b):

    url_a = news_a.get(
        "url",
        "",
    )

    url_b = news_b.get(
        "url",
        "",
    )

    # --------------------------------------------------------
    # URL完全一致
    # --------------------------------------------------------

    if (
        url_a
        and url_b
        and normalize_url(url_a)
        == normalize_url(url_b)
    ):

        return True

    # --------------------------------------------------------
    # タイトル比較
    # --------------------------------------------------------

    score = same_news_score(
        news_a,
        news_b,
    )

    if score >= DUPLICATE_THRESHOLD:
        return True

    return False


# ============================================================
# ID生成
# ============================================================

def make_id(title, published):

    normalized = normalize_text(
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
            ),
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=30,
    ) as response:

        return response.read()


# ============================================================
# XMLユーティリティ
# ============================================================

def find_child_text(element, names):

    for child in element:

        tag = child.tag.split(
            "}"
        )[-1]

        if tag in names:

            if child.text:

                return child.text.strip()

    return ""


def get_atom_link(element):

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
# RSS / Atomニュース取得
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

        results = []

        # ----------------------------------------------------
        # RSS
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Atom
        # ----------------------------------------------------

        else:

            item_elements = [
                element
                for element in root
                if element.tag.split(
                    "}"
                )[-1] == "entry"
            ]

        # ----------------------------------------------------
        # 各記事
        # ----------------------------------------------------

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

            # ------------------------------------------------
            # 媒体名
            # ------------------------------------------------

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

            # ------------------------------------------------
            # タイトル
            # ------------------------------------------------

            clean_article_title = clean_title(
                original_title,
                source,
            )

            if not clean_article_title:
                continue

            # ------------------------------------------------
            # 日付
            # ------------------------------------------------

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

            # ------------------------------------------------
            # Googleニュースdescriptionは使用しない
            # ------------------------------------------------

            description = ""

            news_item = {
                "category": category,
                "title": clean_article_title,
                "description": description,
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
# カテゴリー優先順位
# ============================================================

def choose_category(base, duplicate):

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
        "国内",
    )

    duplicate_category = duplicate.get(
        "category",
        "国内",
    )

    if (
        category_priority.get(
            duplicate_category,
            0,
        )
        >
        category_priority.get(
            base_category,
            0,
        )
    ):

        return duplicate_category

    return base_category


# ============================================================
# より良いタイトルを選択
#
# 長すぎず短すぎず、
# 情報量が多いタイトルを優先
# ============================================================

def title_quality(title):

    if not title:
        return 0

    text = clean_title(
        title
    )

    length = len(
        normalize_text(text)
    )

    if length == 0:
        return 0

    # 15〜45文字程度を最も高評価
    if 15 <= length <= 45:
        score = 100

    elif 10 <= length <= 60:
        score = 80

    else:
        score = 50

    # 年齢や数字
    if re.search(
        r"\d+歳",
        text,
    ):
        score += 5

    # 事件・判決など
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

def merge_news_items(base, duplicate):

    base_title = base.get(
        "title",
        "",
    )

    duplicate_title = duplicate.get(
        "title",
        "",
    )

    # --------------------------------------------------------
    # より良いタイトルを採用
    # --------------------------------------------------------

    if (
        title_quality(duplicate_title)
        >
        title_quality(base_title)
    ):

        base["title"] = duplicate_title

    # --------------------------------------------------------
    # より新しい記事
    # --------------------------------------------------------

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

    base["description"] = ""

    base["category"] = choose_category(
        base,
        duplicate,
    )

    return base


# ============================================================
# URL正規化
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

def remove_url_duplicates(news_list):

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
                + normalize_text(
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
#
# A と B が同じ
# B と C が同じ
#
# の場合、
#
# A / B / C
#
# を1つのニュースグループとして統合
#
# これが今回の重複削除精度向上の重要部分です。
# ============================================================

def merge_duplicates(news_list):

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

        # ----------------------------------------------------
        # 既存クラスタと比較
        # ----------------------------------------------------

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

            # ------------------------------------------------
            # クラスタ内の他記事とも比較
            #
            # 代表記事だけでは
            # A-B-C型の重複を見逃す可能性があるため
            # グループ全体を確認
            # ------------------------------------------------

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

            if (
                score
                > best_score
            ):

                best_score = score

                best_cluster_index = index

        # ----------------------------------------------------
        # 既存クラスタに追加
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # 新しいクラスタ
        # ----------------------------------------------------

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

    # --------------------------------------------------------
    # クラスタ代表を返す
    # --------------------------------------------------------

    merged = []

    for cluster in clusters:

        merged.append(
            cluster[
                "representative"
            ]
        )

    return merged


# ============================================================
# 公開用データ
# ============================================================

def finalize_news(news):

    title = clean_title(
        news.get(
            "title",
            "",
        )
    )

    if not title:
        return None

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
        "description": "",
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
# 既存ニュース読み込み
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
# 最終安全チェック
# ============================================================

def final_safety_clean(news):

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

    lower_title = title.lower()

    for source_name in KNOWN_SOURCE_NAMES:

        if (
            source_name.lower()
            in lower_title
        ):

            title = re.sub(
                re.escape(source_name),
                "",
                title,
                flags=re.IGNORECASE,
            )

    title = re.sub(
        r"\s+",
        " ",
        title,
    ).strip()

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
        "description": "",
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
# メイン処理
# ============================================================

def main():

    print("")
    print("=" * 70)
    print("NEWS NOW ニュース収集開始")
    print("=" * 70)
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
        f"取得したニュース総数: {len(all_news)}件"
    )

    # ========================================================
    # URL重複削除
    # ========================================================

    all_news = remove_url_duplicates(
        all_news
    )

    print(
        f"URL重複削除後: {len(all_news)}件"
    )

    # ========================================================
    # 高精度ニュースクラスタ統合
    # ========================================================

    merged_news = merge_duplicates(
        all_news
    )

    print(
        f"高精度ニュース統合後: {len(merged_news)}件"
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

    for item in final_news:

        if (
            "source" in item
            or "sources" in item
            or "sourceCount" in item
            or "_source" in item
        ):

            source_field_count += 1

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
    print("=" * 70)
    print("NEWS NOW ニュース更新完了")
    print("=" * 70)

    print(
        f"取得総数             : {len(all_news)}件"
    )

    print(
        f"統合後               : {len(final_news)}件"
    )

    print(
        "重複判定方式         : 高精度クラスタ統合"
    )

    print(
        "媒体情報公開         : なし"
    )

    print(
        "関連記事連結         : なし"
    )

    print(
        "Google RSS説明文     : 使用しない"
    )

    print(
        f"source関連キー       : {source_field_count}件"
    )

    print(
        f"媒体名残存確認       : {remaining_source_names}件"
    )

    print(
        f"保存先               : {OUTPUT_FILE}"
    )

    print("=" * 70)
    print("")


# ============================================================
# 実行
# ============================================================

if __name__ == "__main__":
    main()
