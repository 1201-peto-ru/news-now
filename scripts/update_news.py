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
# 高精度ニュース収集・重複統合システム
#
# 改善版:
#
# ・URL重複
# ・完全一致
# ・タイトル類似度
# ・単語一致率
# ・N-Gram一致率
# ・重要フレーズ一致
# ・数字情報一致
# ・公開時間
#
# を組み合わせて、
# 表現が違う同じニュースも可能な限り1件に統合する。
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

# None = 全件保存
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

# 非常に高いタイトル一致
VERY_HIGH_SIMILARITY = 0.88

# 高いタイトル一致
HIGH_SIMILARITY = 0.78

# 中程度
MEDIUM_SIMILARITY = 0.66

# 単語一致率
HIGH_TOKEN_OVERLAP = 0.72

# フレーズ一致率
HIGH_PHRASE_OVERLAP = 0.60

# 同一ニュースとみなす最終スコア
DUPLICATE_THRESHOLD = 0.76

# 明確な同一ニュース
STRONG_DUPLICATE_THRESHOLD = 0.84

# 公開時間の差
MAX_TIME_DIFF_HOURS = 48


# ============================================================
# 媒体名
# ============================================================

KNOWN_SOURCE_NAMES = [
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

    "スポーツ報知",
    "日刊スポーツ",
    "スポニチ",
    "スポーツニッポン",
    "サンスポ",
    "サンケイスポーツ",
    "デイリースポーツ",
    "東スポ",
    "東京スポーツ",

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

    "共同通信",
    "時事通信",
    "Reuters",
    "ロイター",
    "AP通信",

    "Yahoo!ニュース",
    "Yahooニュース",
    "LINE NEWS",
    "gooニュース",
    "ライブドアニュース",
    "livedoorニュース",
    "MSN",
    "Google ニュース",

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
# タイトル整理
# ============================================================

def clean_title(title, source=""):
    if not title:
        return ""

    result = clean_html(title)

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

    # 末尾の余分な記号
    result = re.sub(
        r"[\s\-－―—–|｜]+$",
        "",
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
# 比較用コンパクトタイトル
# ============================================================

def compact_title(text):
    text = normalize_text(text)

    remove_chars = "はがをにへとでのもや"

    for char in remove_chars:
        text = text.replace(char, "")

    return text


# ============================================================
# 日本語ニュース用トークン抽出
#
# 日本語にはスペースが少ないため、
# 文字列全体だけでなく2〜6文字の特徴的な単位を使用する。
# ============================================================

def extract_tokens(title):
    text = compact_title(title)

    if not text:
        return set()

    tokens = set()

    # 英数字の単語
    for token in re.findall(
        r"[a-zA-Z0-9]+",
        text,
    ):
        if len(token) >= 2:
            tokens.add(token.lower())

    # 日本語の特徴的なN-Gram
    for size in range(2, 7):
        if len(text) < size:
            continue

        for i in range(
            len(text) - size + 1
        ):
            token = text[
                i:i + size
            ]

            # 数字だけは除外
            if token.isdigit():
                continue

            tokens.add(token)

    return tokens


# ============================================================
# 重要フレーズ
#
# 長い共通フレーズほど
# 同じニュースである可能性が高い。
# ============================================================

def extract_significant_phrases(title):
    text = compact_title(title)

    phrases = set()

    if len(text) < 3:
        return phrases

    for size in range(4, 11):

        if len(text) < size:
            continue

        for i in range(
            len(text) - size + 1
        ):
            phrase = text[
                i:i + size
            ]

            if phrase.isdigit():
                continue

            phrases.add(phrase)

    return phrases


# ============================================================
# 数字抽出
#
# 人数・金額・日付・順位などは
# 同一ニュース判定で非常に重要。
# ============================================================

def extract_numbers(title):
    text = normalize_text(title)

    numbers = re.findall(
        r"\d+(?:\.\d+)?",
        text,
    )

    return set(numbers)


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
        text[i:i + size]
        for i in range(
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
        set_a & set_b
    )

    union = len(
        set_a | set_b
    )

    if union == 0:
        return 0.0

    return intersection / union


# ============================================================
# 小さい方を基準にした一致率
#
# 短いタイトルが長いタイトルに
# ほぼ含まれているケースに強い。
# ============================================================

def containment_similarity(set_a, set_b):

    if not set_a or not set_b:
        return 0.0

    intersection = len(
        set_a & set_b
    )

    smaller = min(
        len(set_a),
        len(set_b),
    )

    if smaller == 0:
        return 0.0

    return intersection / smaller


# ============================================================
# SequenceMatcher
# ============================================================

def sequence_similarity(title_a, title_b):

    a = compact_title(title_a)
    b = compact_title(title_b)

    if not a or not b:
        return 0.0

    if a == b:
        return 1.0

    # 片方がもう片方に含まれる
    if len(a) >= 8 and a in b:
        return 0.97

    if len(b) >= 8 and b in a:
        return 0.97

    return SequenceMatcher(
        None,
        a,
        b,
    ).ratio()


# ============================================================
# N-Gram類似度
# ============================================================

def ngram_similarity(title_a, title_b):

    bigram_a = make_ngrams(
        title_a,
        2,
    )

    bigram_b = make_ngrams(
        title_b,
        2,
    )

    trigram_a = make_ngrams(
        title_a,
        3,
    )

    trigram_b = make_ngrams(
        title_b,
        3,
    )

    bigram = jaccard_similarity(
        bigram_a,
        bigram_b,
    )

    trigram = jaccard_similarity(
        trigram_a,
        trigram_b,
    )

    return (
        bigram * 0.55
        + trigram * 0.45
    )


# ============================================================
# トークン一致率
# ============================================================

def token_similarity(title_a, title_b):

    tokens_a = extract_tokens(title_a)
    tokens_b = extract_tokens(title_b)

    if not tokens_a or not tokens_b:
        return 0.0, 0.0

    jaccard = jaccard_similarity(
        tokens_a,
        tokens_b,
    )

    containment = containment_similarity(
        tokens_a,
        tokens_b,
    )

    return jaccard, containment


# ============================================================
# 重要フレーズ一致率
# ============================================================

def phrase_similarity(title_a, title_b):

    phrases_a = extract_significant_phrases(
        title_a
    )

    phrases_b = extract_significant_phrases(
        title_b
    )

    if not phrases_a or not phrases_b:
        return 0.0, 0

    common = phrases_a & phrases_b

    if not common:
        return 0.0, 0

    longest_common = max(
        len(phrase)
        for phrase in common
    )

    containment = containment_similarity(
        phrases_a,
        phrases_b,
    )

    return containment, longest_common


# ============================================================
# 数字一致判定
# ============================================================

def number_similarity(title_a, title_b):

    numbers_a = extract_numbers(title_a)
    numbers_b = extract_numbers(title_b)

    # 両方とも数字なしなら中立
    if not numbers_a and not numbers_b:
        return 0.5

    # 片方だけ数字あり
    if not numbers_a or not numbers_b:
        return 0.25

    # 完全一致
    if numbers_a == numbers_b:
        return 1.0

    common = len(
        numbers_a & numbers_b
    )

    union = len(
        numbers_a | numbers_b
    )

    if union == 0:
        return 0.5

    return common / union


# ============================================================
# 公開時間の近さ
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

    # 1時間以内
    if diff_hours <= 1:
        return 1.0

    # 6時間以内
    if diff_hours <= 6:
        return 0.9

    # 24時間以内
    if diff_hours <= 24:
        return 0.75

    # 48時間以内
    if diff_hours <= 48:
        return 0.55

    # 1週間以内
    if diff_hours <= 168:
        return 0.35

    return 0.15


# ============================================================
# URL正規化
# ============================================================

def normalize_url(url):

    if not url:
        return ""

    url = url.strip()

    try:

        parsed = urlparse(url)

        if not parsed.scheme:
            return url

        normalized = (
            f"{parsed.scheme.lower()}://"
            f"{parsed.netloc.lower()}"
            f"{parsed.path}"
        )

        return normalized.rstrip("/")

    except Exception:
        return url


# ============================================================
# 高精度同一ニューススコア
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

    if not title_a or not title_b:
        return 0.0

    # --------------------------------------------------------
    # 完全一致
    # --------------------------------------------------------

    normalized_a = compact_title(title_a)
    normalized_b = compact_title(title_b)

    if normalized_a == normalized_b:
        return 1.0

    # --------------------------------------------------------
    # 片方が含まれる
    # --------------------------------------------------------

    if (
        len(normalized_a) >= 10
        and normalized_a in normalized_b
    ):
        return 0.96

    if (
        len(normalized_b) >= 10
        and normalized_b in normalized_a
    ):
        return 0.96

    # --------------------------------------------------------
    # 各種スコア
    # --------------------------------------------------------

    sequence = sequence_similarity(
        title_a,
        title_b,
    )

    ngram = ngram_similarity(
        title_a,
        title_b,
    )

    token_jaccard, token_containment = (
        token_similarity(
            title_a,
            title_b,
        )
    )

    phrase_score, longest_phrase = (
        phrase_similarity(
            title_a,
            title_b,
        )
    )

    number_score = number_similarity(
        title_a,
        title_b,
    )

    time_score = time_similarity(
        news_a,
        news_b,
    )

    # --------------------------------------------------------
    # 非常に強い共通フレーズ
    #
    # 8文字以上の特徴的な文字列が一致
    # --------------------------------------------------------

    if (
        longest_phrase >= 9
        and sequence >= 0.60
    ):
        return max(
            0.88,
            sequence * 0.55
            + ngram * 0.25
            + phrase_score * 0.20,
        )

    # --------------------------------------------------------
    # 高いタイトル類似
    # --------------------------------------------------------

    if (
        sequence >= VERY_HIGH_SIMILARITY
    ):
        return max(
            sequence,
            0.90,
        )

    # --------------------------------------------------------
    # タイトルがかなり似ていて
    # トークンも多く一致
    # --------------------------------------------------------

    if (
        sequence >= HIGH_SIMILARITY
        and token_containment >= 0.60
    ):
        return max(
            0.85,
            sequence * 0.55
            + ngram * 0.20
            + token_containment * 0.25,
        )

    # --------------------------------------------------------
    # 表現が違うが重要語が多く一致
    # --------------------------------------------------------

    if (
        token_containment >= HIGH_TOKEN_OVERLAP
        and sequence >= 0.55
        and longest_phrase >= 5
    ):
        return max(
            0.82,
            sequence * 0.30
            + ngram * 0.20
            + token_containment * 0.30
            + phrase_score * 0.20,
        )

    # --------------------------------------------------------
    # 通常の総合スコア
    # --------------------------------------------------------

    score = (
        sequence * 0.30
        + ngram * 0.20
        + token_jaccard * 0.15
        + token_containment * 0.20
        + phrase_score * 0.10
        + number_score * 0.03
        + time_score * 0.02
    )

    return min(
        score,
        1.0,
    )


# ============================================================
# 同一ニュース判定
# ============================================================

def are_same_news(news_a, news_b):

    url_a = normalize_url(
        news_a.get(
            "url",
            "",
        )
    )

    url_b = normalize_url(
        news_b.get(
            "url",
            "",
        )
    )

    # --------------------------------------------------------
    # 同一URL
    # --------------------------------------------------------

    if (
        url_a
        and url_b
        and url_a == url_b
    ):
        return True

    score = same_news_score(
        news_a,
        news_b,
    )

    # --------------------------------------------------------
    # 強い一致
    # --------------------------------------------------------

    if score >= STRONG_DUPLICATE_THRESHOLD:
        return True

    # --------------------------------------------------------
    # 時間が極端に離れている場合は
    # 同じニュースでも続報の可能性があるため慎重にする
    # --------------------------------------------------------

    time_a = news_a.get(
        "_published",
        0,
    )

    time_b = news_b.get(
        "_published",
        0,
    )

    if time_a and time_b:

        diff_hours = abs(
            time_a - time_b
        ) / 3600

        if diff_hours > MAX_TIME_DIFF_HOURS:

            # 非常に高い一致だけ統合
            return score >= 0.90

    return score >= DUPLICATE_THRESHOLD


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

    dt = parse_date(date_text)

    if not dt:
        return ""

    japan_time = dt.astimezone(
        timezone(
            timedelta(hours=9)
        )
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

            if (
                element.tag.split(
                    "}"
                )[-1]
                == "channel"
            ):
                channel = element
                break

        if channel is not None:

            item_elements = [
                element
                for element in channel
                if element.tag.split(
                    "}"
                )[-1]
                == "item"
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
                )[-1]
                == "entry"
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

            # URL
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

            # 媒体名
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

            # タイトル
            clean_article_title = clean_title(
                original_title,
                source,
            )

            if not clean_article_title:
                continue

            # 日付
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

            news_item = {
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

CATEGORY_PRIORITY = {
    "国内": 7,
    "海外": 7,
    "IT": 6,
    "スポーツ": 6,
    "エンタメ": 6,
    "科学": 6,
    "経済": 6,
}


# ============================================================
# カテゴリー統合
# ============================================================

def choose_category(base, duplicate):

    base_category = base.get(
        "category",
        "国内",
    )

    duplicate_category = duplicate.get(
        "category",
        "国内",
    )

    if (
        CATEGORY_PRIORITY.get(
            duplicate_category,
            0,
        )
        >
        CATEGORY_PRIORITY.get(
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

    base_time = base.get(
        "_published",
        0,
    )

    duplicate_time = duplicate.get(
        "_published",
        0,
    )

    # --------------------------------------------------------
    # より新しい記事を基本的に優先
    # --------------------------------------------------------

    if duplicate_time > base_time:

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

        base["_published"] = duplicate_time

        base["url"] = duplicate.get(
            "url",
            base.get(
                "url",
                "",
            ),
        )

    # --------------------------------------------------------
    # ただし短すぎるタイトルより
    # 情報量があるタイトルを優先
    # --------------------------------------------------------

    base_title = base.get(
        "title",
        "",
    )

    duplicate_title = duplicate.get(
        "title",
        "",
    )

    if (
        len(duplicate_title)
        > len(base_title) + 8
    ):
        base["title"] = duplicate_title

    base["description"] = ""

    base["category"] = choose_category(
        base,
        duplicate,
    )

    return base


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
# 高速化用候補判定
#
# 全記事を何百件も完全比較すると遅くなるため、
# 最低限の共通性があるものを中心に比較する。
# ============================================================

def might_be_related(news_a, news_b):

    title_a = compact_title(
        news_a.get(
            "title",
            "",
        )
    )

    title_b = compact_title(
        news_b.get(
            "title",
            "",
        )
    )

    if not title_a or not title_b:
        return False

    # 最初の3文字が一致
    if (
        len(title_a) >= 3
        and len(title_b) >= 3
        and title_a[:3] == title_b[:3]
    ):
        return True

    # 長い共通フレーズ
    short = (
        title_a
        if len(title_a) < len(title_b)
        else title_b
    )

    long = (
        title_b
        if len(title_a) < len(title_b)
        else title_a
    )

    for size in range(
        min(8, len(short)),
        3,
        -1,
    ):

        for i in range(
            len(short) - size + 1
        ):

            phrase = short[
                i:i + size
            ]

            if phrase in long:
                return True

    # N-Gramで最低限の一致
    bigram_a = make_ngrams(
        title_a,
        2,
    )

    bigram_b = make_ngrams(
        title_b,
        2,
    )

    if jaccard_similarity(
        bigram_a,
        bigram_b,
    ) >= 0.15:
        return True

    return False


# ============================================================
# 重複ニュース統合
#
# 新しいニュースから順番に処理。
# 同じニュースグループを1件にまとめる。
# ============================================================

def merge_duplicates(news_list):

    news_list.sort(
        key=lambda item: item.get(
            "_published",
            0,
        ),
        reverse=True,
    )

    merged = []

    total = len(news_list)

    for index, news in enumerate(
        news_list,
        start=1,
    ):

        duplicate_index = None
        best_score = 0.0

        for existing_index, existing in enumerate(
            merged
        ):

            # 明らかに関係なさそうなら
            # 重い比較を減らす
            if not might_be_related(
                existing,
                news,
            ):
                continue

            score = same_news_score(
                existing,
                news,
            )

            if score > best_score:

                best_score = score
                duplicate_index = existing_index

        # ----------------------------------------------------
        # 最も一致したニュースへ統合
        # ----------------------------------------------------

        if (
            duplicate_index is not None
            and best_score >= DUPLICATE_THRESHOLD
        ):

            merge_news_items(
                merged[duplicate_index],
                news,
            )

        else:

            merged.append(news)

        # 進捗表示
        if (
            index % 50 == 0
            or index == total
        ):
            print(
                f"  重複判定: {index}/{total}"
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

            data = json.load(file)

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

    # 媒体名の最終除去
    for source_name in KNOWN_SOURCE_NAMES:

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

    if not title:
        return None

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
# 最終的な完全重複チェック
#
# 公開直前にもう一度同じタイトルを除去する。
# ============================================================

def final_duplicate_check(news_list):

    unique = []

    for news in news_list:

        found = False

        for existing in unique:

            if are_same_news(
                existing,
                news,
            ):

                found = True

                # より新しいものを残す
                existing_date = existing.get(
                    "date",
                    ""
                )

                news_date = news.get(
                    "date",
                    ""
                )

                if news_date > existing_date:
                    existing.update(news)

                break

        if not found:
            unique.append(news)

    return unique


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

            all_news.extend(items)

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
    # 高精度同一ニュース統合
    # ========================================================

    print("")
    print(
        "高精度重複ニュース判定中..."
    )

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
    # 公開用データ作成
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
    # 最終重複チェック
    # ========================================================

    print("")
    print(
        "公開前の最終重複チェック中..."
    )

    before_final_check = len(
        final_news
    )

    final_news = final_duplicate_check(
        final_news
    )

    print(
        f"最終重複削除: "
        f"{before_final_check}件 → "
        f"{len(final_news)}件"
    )

    # ========================================================
    # 新しい順
    #
    # 公開データはdate文字列で並び替え
    # ========================================================

    final_news.sort(
        key=lambda item: item.get(
            "date",
            ""
        ),
        reverse=True,
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

        if existing.get("items"):

            print(
                "既存のnews.jsonを維持します。"
            )

            return

        print(
            "既存ニュースもありません。"
        )

        return

    # ========================================================
    # 保存時間
    # ========================================================

    japan_tz = timezone(
        timedelta(hours=9)
    )

    now = datetime.now(
        japan_tz
    )

    output = {
        "updatedAt": now.isoformat(),
        "total": len(final_news),
        "items": final_news,
    }

    # ========================================================
    # 保存
    # ========================================================

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

        file.write("\n")

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
        f"取得総数            : {len(all_news)}件"
    )

    print(
        f"最終ニュース数      : {len(final_news)}件"
    )

    print(
        "重複判定            : 強化版"
    )

    print(
        "URL重複削除          : 有効"
    )

    print(
        "タイトル類似度       : 有効"
    )

    print(
        "N-Gram判定           : 有効"
    )

    print(
        "重要フレーズ判定     : 有効"
    )

    print(
        "トークン一致判定     : 有効"
    )

    print(
        "数字情報判定         : 有効"
    )

    print(
        "公開時間判定         : 有効"
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
