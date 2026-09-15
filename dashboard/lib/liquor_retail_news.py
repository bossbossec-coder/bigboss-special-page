"""酒販店小売業に関するニュース（業界団体・業界紙）を取得する。

各情報源のRSS/RDFフィードを取得し、タイトル・日付・リンクの一覧にまとめる。
ここで指定しているフィードのURLは、公開されている情報をもとにした推測を
含んでおり、実際に正しく取得できるかはこの開発環境からは検証できていない
（外部サイトへ接続できないため）。取得に失敗した情報源はNoneとして扱い、
他の情報源の表示やダッシュボード全体には影響しないようにする。

本番環境で表示を確認し、うまく取得できない情報源があれば
LIQUOR_RETAIL_NEWS_SOURCESのURLを見直す必要がある。
"""

from __future__ import annotations

from lib import feed_utils

# 表示名 -> フィードURL（未検証のものを含む。ラベルの並び順で表示する）
LIQUOR_RETAIL_NEWS_SOURCES: dict[str, str] = {
    "全国小売酒販組合中央会": "https://prtimes.jp/companyrdf.php?company_id=134181",
    "酒類食品産業新聞（ssnp.co.jp）": "https://www.ssnp.co.jp/liquor/feed/",
}


def fetch_liquor_retail_news(max_items: int = 5) -> dict[str, list[dict] | None]:
    """情報源ごとに、酒販店小売業に関するニュースを新しい順に返す。

    戻り値は表示名をキーに、[{"title", "link", "date"}, ...] のリスト。
    取得自体に失敗した情報源は値をNoneにする（表示側で「取得できません」に
    切り替える）。"""
    return feed_utils.fetch_feed_items(LIQUOR_RETAIL_NEWS_SOURCES, max_items=max_items)
