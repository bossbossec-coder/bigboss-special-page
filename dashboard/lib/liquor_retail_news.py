"""酒販店小売業に関するニュース（業界団体・業界紙）を取得する。

各情報源のRSS/RDFフィードを取得し、タイトル・日付・リンクの一覧にまとめる。
配信元の正確なフィードURLがこの開発環境からは検証できないため（外部サイトへ
接続できない）、情報源ごとに複数の候補URLを用意し、実際にフィードとして
読み込めた最初のURLを使うようにしている（feed_utils側の仕組み）。取得に
失敗した情報源はNoneとして扱い、他の情報源の表示やダッシュボード全体には
影響しないようにする。

本番環境で表示を確認し、それでもうまく取得できない情報源があれば
LIQUOR_RETAIL_NEWS_SOURCESの候補URLを見直す・追加する必要がある。
"""

from __future__ import annotations

from lib import feed_utils

# 表示名 -> フィードURL候補のリスト（先頭から順に試し、最初に読み込めたものを使う）
LIQUOR_RETAIL_NEWS_SOURCES: dict[str, list[str]] = {
    "全国小売酒販組合中央会": [
        "https://prtimes.jp/companyrdf.php?company_id=134181",
    ],
    "酒類食品産業新聞（ssnp.co.jp）": [
        "https://www.ssnp.co.jp/liquor/feed/",
        "https://www.ssnp.co.jp/feed/",
        "https://www.ssnp.co.jp/liquor/rss.xml",
    ],
}


def fetch_liquor_retail_news(max_items: int = 5) -> dict[str, list[dict] | None]:
    """情報源ごとに、酒販店小売業に関するニュースを新しい順に返す。

    戻り値は表示名をキーに、[{"title", "link", "date"}, ...] のリスト。
    取得自体に失敗した情報源は値をNoneにする（表示側で「取得できません」に
    切り替える）。"""
    return feed_utils.fetch_feed_items(LIQUOR_RETAIL_NEWS_SOURCES, max_items=max_items)
