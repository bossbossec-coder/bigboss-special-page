"""RSS/Atom/RDFフィードを取得し、タイトル・日付・リンクの一覧に変換する
共通処理。新商品情報・地域情報・酒販店ニュースなど、複数の外部情報源を
同じ形式（表示名 -> フィードURL）で取得して表示するセクションで共通して使う。
"""

from __future__ import annotations

import time

import feedparser
import requests

REQUEST_TIMEOUT_SECONDS = 8
REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BigbossDashboard/1.0)"}


def _entry_date_label(entry) -> str:
    """フィードの各項目から日付を取り出し、日本語表記（例: 2026年9月10日）にする。
    日付が取れない場合は空文字を返す。"""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return ""
    return time.strftime("%Y年%-m月%-d日", parsed)


def fetch_feed_items(
    sources: dict[str, str],
    max_items: int = 5,
    keyword_filter: tuple[str, ...] | None = None,
) -> dict[str, list[dict] | None]:
    """情報源（表示名 -> フィードURL）ごとに、新しい記事・お知らせを新しい順に
    返す。keyword_filterを指定した場合、タイトルにいずれかのキーワードを
    含む項目だけを残す（新商品情報のように、全ニュースの中から特定の話題
    だけを抜き出したい場合に使う）。

    戻り値は表示名をキーに、[{"title", "link", "date"}, ...] のリスト。
    取得自体に失敗した情報源は値をNoneにする（表示側で「取得できません」に
    切り替える）。"""
    results: dict[str, list[dict] | None] = {}
    for label, feed_url in sources.items():
        try:
            response = requests.get(feed_url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
        except Exception:
            results[label] = None
            continue

        if feed.bozo and not feed.entries:
            results[label] = None
            continue

        entries = feed.entries
        if keyword_filter:
            entries = [entry for entry in entries if any(kw in entry.title for kw in keyword_filter)]

        items = [
            {"title": entry.title, "link": entry.link, "date": _entry_date_label(entry)}
            for entry in entries
        ][:max_items]
        results[label] = items

    return results
