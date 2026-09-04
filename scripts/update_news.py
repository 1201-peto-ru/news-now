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
# ニュース収集・重複ニュース統合システム
#
# 目的:
#
# 1ニュース = 1記事
#
# GoogleニュースRSSのdescriptionには
# 関連記事や複数の記事タイトルが混ざることがあるため、
# RSS descriptionをそのまま表示しません。
#
# 代わりに元記事URLへアクセスし、
#
# ・og:description
# ・meta description
# ・JSON-LD description
#
# などから、その記事自身の説明文を取得します。
#
# 媒体名・関連記事タイトル・Googleニュースの案内文などは
# できるだけ除去します。
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

# 重複判定
HIGH_SIMILARITY = 0.80
MEDIUM_SIMILARITY = 0.70
MIN_SHARED_SCORE = 0.55

# RSS取得間隔
REQUEST_INTERVAL = 0.5

# 元記事説明取得間隔
ARTICLE_REQUEST_INTERVAL = 0.15

# 元記事説明取得タイムアウト
ARTICLE_TIMEOUT = 12

# HTTP User-Agent
USER_AGENT = (
    "Mozilla/5.0 "
    "(compatible; NEWS-NOW-NewsBot/7.0)"
)


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
    "河北新報",
    "沖縄タイムス",
    "琉球新報",

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
    "NHKニュース",
    "NHK",
    "日本テレビ",
    "日テレNEWS",
    "日テレ",
    "TBS NEWS DIG",
    "TBS NEWS",
    "TBS",
    "テレビ朝日",
    "テレ朝news",
    "テレ朝",
    "フジテレビ",
    "FNNプライムオンライン",
    "FNN",
    "テレビ東京",
    "TOKYO MX",
    "ABEMA TIMES",
    "AbemaTIMES",

    # 通信社
    "共同通信社",
    "共同通信",
    "時事通信",
    "Reuters",
    "REUTERS",
    "ロイター",
    "AP通信",
    "AP",

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
    "Googleニュース",
    "dメニューニュース",

    # IT・その他
    "ITmedia NEWS",
    "ITmedia",
    "Impress Watch",
    "マイナビニュース",
    "ORICON NEWS",
    "ORICON",
    "オリコン",
    "PR TIMES",
    "CNET Japan",
    "ねとらぼ",
    "J-CASTニュース",
    "ハフポスト",
    "HuffPost",
    "弁護士ドットコム",
    "MANTANWEB",
    "モデルプレス",
    "GIGAZINE",
    "TechCrunch",
    "Engadget",

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
        r"<noscript\b[^>]*>.*?</noscript>",
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

    result = re.sub(
        r"\s*[-－―—–|｜]\s*[-－―—–|｜]\s*",
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

    result = remove_source_names(
        result
    )

    result = re.sub(
        r"\s*[-－―—–|｜]\s*"
        r"(?:"
        r"読売新聞|朝日新聞|毎日新聞|日本経済新聞|"
        r"日経新聞|産経新聞|東京新聞|中日新聞|"
        r"スポーツ報知|日刊スポーツ|スポニチ|"
        r"スポーツニッポン|サンスポ|サンケイスポーツ|"
        r"デイリースポーツ|東スポ|東京スポーツ|"
        r"Yahoo!?ニュース|NHK(?: NEWS WEB)?|"
        r"TBS(?: NEWS DIG)?|共同通信|時事通信|"
        r"Reuters|ロイター|AP通信|"
        r"sanspo\.com|nikkansports\.com|hochi\.news|"
        r"yomiuri\.co\.jp|asahi\.com|mainichi\.jp|"
        r"nikkei\.com|sankei\.com"
        r")\s*$",
        "",
        result,
        flags=re.IGNORECASE,
    )

    result = remove_source_names(
        result
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
# タイトル比較用
# ============================================================

def compact_title(text):
    text = normalize_text(text)

    remove_chars = "はがをにへとでのもや、"

    for char in remove_chars:
        text = text.replace(
            char,
            "",
        )

    return text


# ============================================================
# 説明文クリーンアップ
# ============================================================

def clean_article_description(
    description,
    title,
):
    if not description:
        return ""

    text = clean_html(
        description
    )

    if not text:
        return ""

    # URL削除
    text = re.sub(
        r"https?://\S+",
        "",
        text,
    )

    # Googleニュース系の案内文
    text = re.sub(
        r"Google\s*ニュース\s*で.*?(?:見る|見出し|意見).*?$",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"Googleニュースで.*?$",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"見出しと意見をもっと見る.*?$",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"ニュースをもっと見る.*?$",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"続きを読む\s*$",
        "",
        text,
    )

    text = re.sub(
        r"もっと見る\s*$",
        "",
        text,
    )

    text = re.sub(
        r"詳細はこちら\s*$",
        "",
        text,
    )

    # 媒体名除去
    text = remove_source_names(
        text
    )

    # 先頭・末尾の区切り記号整理
    text = re.sub(
        r"^[\s\-－―—–|｜:：]+",
        "",
        text,
    )

    text = re.sub(
        r"[\s\-－―—–|｜:：]+$",
        "",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    if not text:
        return ""

    # ========================================================
    # タイトルそのものを説明文にしない
    # ========================================================

    normalized_title = normalize_text(
        title
    )

    normalized_text = normalize_text(
        text
    )

    if (
        normalized_title
        and normalized_text
        and (
            normalized_title == normalized_text
            or normalized_title in normalized_text
        )
    ):
        # 説明文がタイトルから始まっている場合
        if text.startswith(title):
            text = text[
                len(title):
            ].strip(
                " \t　-－―—–|｜:："
            )

        elif (
            len(normalized_text)
            <= len(normalized_title) + 20
        ):
            return ""

    # ========================================================
    # 関連記事の羅列を検出
    # ========================================================

    related_markers = [
        "関連記事",
        "関連ニュース",
        "関連するニュース",
        "あわせて読みたい",
        "おすすめ記事",
        "関連情報",
        "もっと読む",
    ]

    for marker in related_markers:
        if marker in text:
            text = text.split(
                marker,
                1,
            )[0].strip()

    # ========================================================
    # 説明文の長さ
    # ========================================================

    if len(text) > 500:
        text = text[:500]

        # 途中で切れた文章を少し整える
        last_sentence = max(
            text.rfind("。"),
            text.rfind("！"),
            text.rfind("？"),
        )

        if last_sentence >= 80:
            text = text[
                :last_sentence + 1
            ]

    # ========================================================
    # 最終媒体名チェック
    # ========================================================

    lower_text = text.lower()

    for source_name in KNOWN_SOURCE_NAMES:
        if source_name.lower() in lower_text:
            return ""

    return text.strip()


# ============================================================
# 元記事HTMLから説明文を取得
# ============================================================

def fetch_article_html(url):
    if not url:
        return ""

    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "ja,en;q=0.8",
                "Accept": (
                    "text/html,"
                    "application/xhtml+xml,"
                    "application/xml;q=0.9,"
                    "*/*;q=0.8"
                ),
            },
        )

        with urllib.request.urlopen(
            request,
            timeout=ARTICLE_TIMEOUT,
        ) as response:

            content_type = (
                response.headers.get(
                    "Content-Type",
                    "",
                )
                .lower()
            )

            if (
                content_type
                and "text/html" not in content_type
                and "application/xhtml" not in content_type
            ):
                return ""

            data = response.read(
                1024 * 1024 * 2
            )

            charset = response.headers.get_content_charset()

            if not charset:
                charset = "utf-8"

            try:
                return data.decode(
                    charset,
                    errors="ignore",
                )

            except Exception:
                return data.decode(
                    "utf-8",
                    errors="ignore",
                )

    except Exception as error:
        print(
            f"    元記事取得失敗: {error}"
        )
        return ""


# ============================================================
# HTML属性からmeta値を取得
# ============================================================

def extract_meta_content(
    html_text,
    attr_name,
    attr_value,
):
    if not html_text:
        return ""

    pattern = (
        r"<meta\b"
        r"[^>]*?"
        rf"{attr_name}\s*=\s*"
        rf"([\"']){re.escape(attr_value)}\1"
        r"[^>]*?"
        r"(?:content\s*=\s*([\"'])(.*?)\2)"
        r"[^>]*>"
    )

    match = re.search(
        pattern,
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if match:
        return html.unescape(
            match.group(4)
            or ""
        ).strip()

    # 属性順が逆の場合
    reverse_pattern = (
        r"<meta\b"
        r"[^>]*?"
        r"(?:content\s*=\s*([\"'])(.*?)\1)"
        r"[^>]*?"
        rf"{attr_name}\s*=\s*"
        rf"([\"']){re.escape(attr_value)}\3"
        r"[^>]*>"
    )

    match = re.search(
        reverse_pattern,
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if match:
        return html.unescape(
            match.group(2)
            or ""
        ).strip()

    return ""


# ============================================================
# JSON-LD description取得
# ============================================================

def extract_jsonld_description(
    html_text,
):
    if not html_text:
        return ""

    scripts = re.findall(
        r"<script\b[^>]*type\s*=\s*"
        r"[\"']application/ld\+json[\"'][^>]*>"
        r"(.*?)"
        r"</script>",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    for script in scripts:

        script = html.unescape(
            script
        ).strip()

        if not script:
            continue

        try:
            data = json.loads(
                script
            )
        except Exception:
            continue

        candidates = []

        if isinstance(
            data,
            dict,
        ):
            candidates.append(
                data
            )

            graph = data.get(
                "@graph"
            )

            if isinstance(
                graph,
                list,
            ):
                candidates.extend(
                    item
                    for item in graph
                    if isinstance(
                        item,
                        dict,
                    )
                )

        elif isinstance(
            data,
            list,
        ):
            candidates.extend(
                item
                for item in data
                if isinstance(
                    item,
                    dict,
                )
            )

        for item in candidates:

            description = item.get(
                "description"
            )

            if isinstance(
                description,
                str,
            ):
                description = clean_html(
                    description
                )

                if description:
                    return description

    return ""


# ============================================================
# 元記事から説明文を探す
# ============================================================

def get_article_description(
    url,
    title,
):
    if not url:
        return ""

    html_text = fetch_article_html(
        url
    )

    if not html_text:
        return ""

    candidates = []

    # --------------------------------------------------------
    # Open Graph
    # --------------------------------------------------------

    og_description = extract_meta_content(
        html_text,
        "property",
        "og:description",
    )

    if og_description:
        candidates.append(
            og_description
        )

    # --------------------------------------------------------
    # Twitter
    # --------------------------------------------------------

    twitter_description = extract_meta_content(
        html_text,
        "name",
        "twitter:description",
    )

    if twitter_description:
        candidates.append(
            twitter_description
        )

    # --------------------------------------------------------
    # 通常meta description
    # --------------------------------------------------------

    meta_description = extract_meta_content(
        html_text,
        "name",
        "description",
    )

    if meta_description:
        candidates.append(
            meta_description
        )

    # --------------------------------------------------------
    # JSON-LD
    # --------------------------------------------------------

    jsonld_description = extract_jsonld_description(
        html_text
    )

    if jsonld_description:
        candidates.append(
            jsonld_description
        )

    # --------------------------------------------------------
    # クリーンアップ
    # --------------------------------------------------------

    for candidate in candidates:

        cleaned = clean_article_description(
            candidate,
            title,
        )

        if not cleaned:
            continue

        # 短すぎるものは説明として弱い
        if len(cleaned) < 15:
            continue

        # URLだけなどを除外
        if re.fullmatch(
            r"[\W_]+",
            cleaned,
        ):
            continue

        return cleaned

    return ""


# ============================================================
# RSS説明文から安全な説明を作る
#
# 原則として元記事取得を優先。
# ここは元記事が取得できなかった場合の
# 最低限の安全なフォールバック。
#
# 関連記事の羅列が疑われる場合は
# 無理に表示しません。
# ============================================================

def fallback_rss_description(
    raw_description,
    title,
):
    if not raw_description:
        return ""

    cleaned = clean_html(
        raw_description
    )

    if not cleaned:
        return ""

    # Googleニュース案内
    cleaned = re.sub(
        r"Google\s*ニュースで.*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"見出しと意見をもっと見る.*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = remove_source_names(
        cleaned
    )

    cleaned = re.sub(
        r"\s+",
        " ",
        cleaned,
    ).strip()

    if not cleaned:
        return ""

    # タイトルを先頭に繰り返している場合
    if title:
        if cleaned.startswith(title):
            cleaned = cleaned[
                len(title):
            ].strip(
                " \t　-－―—–|｜:："
            )

    # 関連記事の可能性が高いパターン
    related_patterns = [
        r"\s+[A-Za-z0-9Ａ-Ｚａ-ｚ０-９]+\.(?:com|jp|net|co\.jp)\s*$",
        r"\s+Google\s*$",
        r"\s+ニュース\s*$",
    ]

    for pattern in related_patterns:
        cleaned = re.sub(
            pattern,
            "",
            cleaned,
            flags=re.IGNORECASE,
        )

    # 媒体名がまだ残っている場合は
    # RSS説明文を使用しない
    for source_name in KNOWN_SOURCE_NAMES:
        if source_name.lower() in cleaned.lower():
            return ""

    # 長すぎるRSS説明は
    # 関連記事連結の可能性が高い
    if len(cleaned) > 280:
        return ""

    # タイトルとほぼ同じなら不要
    normalized_cleaned = normalize_text(
        cleaned
    )

    normalized_title = normalize_text(
        title
    )

    if (
        normalized_cleaned
        and normalized_title
        and normalized_cleaned
        == normalized_title
    ):
        return ""

    return cleaned[:280].strip()


# ============================================================
# N-Gram
# ============================================================

def make_ngrams(
    text,
    size=2,
):
    text = compact_title(
        text
    )

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


def jaccard_similarity(
    set_a,
    set_b,
):
    if not set_a or not set_b:
        return 0.0

    intersection = len(
        set_a.intersection(
            set_b
        )
    )

    union = len(
        set_a.union(
            set_b
        )
    )

    if union == 0:
        return 0.0

    return intersection / union


# ============================================================
# タイトル類似度
# ============================================================

def title_similarity(
    title_a,
    title_b,
):
    a = normalize_text(
        title_a
    )

    b = normalize_text(
        title_b
    )

    if not a or not b:
        return 0.0

    if a == b:
        return 1.0

    if len(a) >= 10 and a in b:
        return 0.96

    if len(b) >= 10 and b in a:
        return 0.96

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
        sequence_score * 0.45
        + bigram_score * 0.35
        + trigram_score * 0.20
    )

    return max(
        sequence_score * 0.85,
        score,
    )


# ============================================================
# 重要情報比較
# ============================================================

def extract_significant_chunks(
    title,
):
    normalized = compact_title(
        title
    )

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

            if re.fullmatch(
                r"[0-9]+",
                chunk,
            ):
                continue

            chunks.add(
                chunk
            )

    return chunks


def same_core_information(
    news_a,
    news_b,
):
    chunks_a = extract_significant_chunks(
        news_a.get(
            "title",
            "",
        )
    )

    chunks_b = extract_significant_chunks(
        news_b.get(
            "title",
            "",
        )
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
# ニュース同一性判定
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

    if similarity >= HIGH_SIMILARITY:
        return max(
            similarity,
            0.90,
        )

    if (
        similarity >= MEDIUM_SIMILARITY
        and core_score >= MIN_SHARED_SCORE
    ):
        return max(
            0.88,
            similarity * 0.65
            + core_score * 0.35,
        )

    if (
        similarity >= 0.62
        and core_score >= 0.78
    ):
        return 0.84

    return (
        similarity * 0.65
        + core_score * 0.35
    )


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

    score = same_news_score(
        news_a,
        news_b,
    )

    return score >= 0.82


# ============================================================
# ID生成
# ============================================================

def make_id(
    title,
    published,
):
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
# XMLユーティリティ
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

            # ================================================
            # タイトル
            # ================================================

            original_title = clean_html(
                find_child_text(
                    item,
                    {"title"},
                )
            )

            if not original_title:
                continue

            # ================================================
            # URL
            # ================================================

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

            # ================================================
            # 媒体名
            # 内部処理のみ
            # ================================================

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

            # ================================================
            # タイトル
            # ================================================

            clean_article_title = clean_title(
                original_title,
                source,
            )

            if not clean_article_title:
                continue

            # ================================================
            # 日付
            # ================================================

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

            # ================================================
            # RSS description
            #
            # 元記事取得に失敗した場合のために
            # 一時的に保持するだけ。
            # そのまま公開はしない。
            # ================================================

            raw_description = find_child_text(
                item,
                {
                    "description",
                    "summary",
                    "content",
                },
            )

            # ================================================
            # 元記事から説明取得
            # ================================================

            description = get_article_description(
                link,
                clean_article_title,
            )

            # ================================================
            # 元記事から取得できなかった場合
            # ================================================

            if not description:

                description = fallback_rss_description(
                    raw_description,
                    clean_article_title,
                )

            # ================================================
            # 説明文最終クリーン
            # ================================================

            description = clean_article_description(
                description,
                clean_article_title,
            )

            # ================================================
            # 内部データ
            # ================================================

            news_item = {
                "category": category,
                "title": clean_article_title,
                "description": description,
                "url": link,
                "date": format_japan_date(
                    pub_date
                ),
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

            time.sleep(
                ARTICLE_REQUEST_INTERVAL
            )

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
# カテゴリー統合
# ============================================================

def choose_category(
    base,
    duplicate,
):
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
# ニュース統合
# ============================================================

def merge_news_items(
    base,
    duplicate,
):
    # より新しい記事を優先
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

        base["title"] = duplicate.get(
            "title",
            base.get(
                "title",
                "",
            ),
        )

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

    # ========================================================
    # 説明文
    #
    # すでに良い説明があれば維持。
    # 空なら重複側の説明を採用。
    # ========================================================

    base_description = clean_article_description(
        base.get(
            "description",
            "",
        ),
        base.get(
            "title",
            "",
        ),
    )

    duplicate_description = clean_article_description(
        duplicate.get(
            "description",
            "",
        ),
        duplicate.get(
            "title",
            "",
        ),
    )

    if not base_description and duplicate_description:
        base["description"] = duplicate_description

    else:
        base["description"] = base_description

    base["category"] = choose_category(
        base,
        duplicate,
    )

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
# 重複ニュース統合
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

    merged = []

    for news in news_list:

        duplicate_found = False

        for existing in merged:

            if are_same_news(
                existing,
                news,
            ):

                merge_news_items(
                    existing,
                    news,
                )

                duplicate_found = True
                break

        if not duplicate_found:

            merged.append(
                news
            )

    return merged


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

    published = news.get(
        "_published",
        0,
    )

    description = clean_article_description(
        news.get(
            "description",
            "",
        ),
        title,
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

    # --------------------------------------------------------
    # 媒体名がタイトルに残っていないか確認
    # --------------------------------------------------------

    lower_title = title.lower()

    for source_name in KNOWN_SOURCE_NAMES:

        if source_name.lower() in lower_title:

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

    # --------------------------------------------------------
    # 説明文
    # --------------------------------------------------------

    description = clean_article_description(
        str(
            news.get(
                "description",
                "",
            )
        ),
        title,
    )

    # --------------------------------------------------------
    # 説明文の媒体名チェック
    # --------------------------------------------------------

    lower_description = description.lower()

    for source_name in KNOWN_SOURCE_NAMES:

        if source_name.lower() in lower_description:

            description = ""

            break

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
    # 同一ニュース統合
    # ========================================================

    merged_news = merge_duplicates(
        all_news
    )

    print(
        f"同一ニュース統合後: {len(merged_news)}件"
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

        # タイトルが空なら除外
        if not public_item.get(
            "title",
            "",
        ):
            continue

        # URLが空なら除外
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
    description_count = 0

    for item in final_news:

        # ----------------------------------------------------
        # source関連キー確認
        # ----------------------------------------------------

        if (
            "source" in item
            or "sources" in item
            or "sourceCount" in item
            or "_source" in item
        ):

            source_field_count += 1

        # ----------------------------------------------------
        # 説明文件数
        # ----------------------------------------------------

        if item.get(
            "description",
            "",
        ).strip():

            description_count += 1

        # ----------------------------------------------------
        # 媒体名残存確認
        # ----------------------------------------------------

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
        f"取得総数        : {len(all_news)}件"
    )

    print(
        f"統合後           : {len(final_news)}件"
    )

    print(
        f"説明文あり       : {description_count}件"
    )

    print(
        "媒体情報公開     : なし"
    )

    print(
        "関連記事連結     : なし"
    )

    print(
        "Google RSS説明文 : 元記事取得を優先"
    )

    print(
        f"source関連キー   : {source_field_count}件"
    )

    print(
        f"媒体名残存確認   : {remaining_source_names}件"
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
