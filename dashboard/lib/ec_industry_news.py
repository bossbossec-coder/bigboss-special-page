"""EC業界にまつわるニュースを取得する。

2つの種類の情報源をまとめて扱う。
- EC業界全体の動向ニュース（ECzine・ネットショップ担当者フォーラム・
  日本ネット経済新聞など）
- 出店中のECモール運営会社（楽天・LINEヤフー等）の最新ニュース
  （モールの出店者専用お知らせページはログインが必要で外部から取得
  できないため、各社の一般向けプレスリリース配信を代わりに使う）

各情報源のRSS/RDFフィードを取得し、タイトル・日付・リンクの一覧にまとめる。
配信元の正確なフィードURLがこの開発環境からは検証できないため（外部サイトへ
接続できない）、情報源ごとに複数の候補URLを用意し、実際にフィードとして
読み込めた最初のURLを使うようにしている（feed_utils側の仕組み）。取得に
失敗した情報源はNoneとして扱い、他の情報源の表示やダッシュボード全体には
影響しないようにする。

本番環境で表示を確認し、それでもうまく取得できない情報源があれば
EC_INDUSTRY_NEWS_SOURCESの候補URLを見直す・追加する必要がある。
"""

from __future__ import annotations

from lib import feed_utils

# 表示名 -> フィードURL候補のリスト（先頭から順に試し、最初に読み込めたものを使う）
EC_INDUSTRY_NEWS_SOURCES: dict[str, list[str]] = {
    "EC業界ニュース（ECzine）": [
        # 翔泳社の同系メディア（MarkeZineなど）で実際に使われているパターン
        "https://eczine.jp/rss/new/20/index.xml",
        "https://eczine.jp/rss/index.rdf",
        "https://eczine.jp/feed/",
    ],
    "EC業界ニュース（ネットショップ担当者フォーラム）": [
        "https://netshop.impress.co.jp/rss.xml",
        "https://netshop.impress.co.jp/node/feed",
        "https://netshop.impress.co.jp/rss/index.rdf",
        "https://netshop.impress.co.jp/feed",
    ],
    "EC業界ニュース（日本ネット経済新聞）": [
        # 独自CMSのためRSSが無い可能性が高いが、念のため候補を残す
        "https://www.netkeizai.com/feed",
        "https://www.netkeizai.com/rss",
        "https://www.netkeizai.com/index.rdf",
    ],
    "楽天グループの最新ニュース": [
        "https://prtimes.jp/companyrdf.php?company_id=5889",
        "https://corp.rakuten.co.jp/news/feed/",
        "https://corp.rakuten.co.jp/news/rss.xml",
    ],
    "Amazonジャパンの最新ニュース": [
        "https://prtimes.jp/companyrdf.php?company_id=4612",
    ],
    "LINEヤフーの最新ニュース（Yahoo!ショッピング運営元）": [
        "https://prtimes.jp/companyrdf.php?company_id=129774",
        "https://www.lycorp.co.jp/ja/news/feed/",
        "https://www.lycorp.co.jp/ja/news/rss.xml",
    ],
    "Qoo10（eBay Japan）の最新ニュース": [
        "https://prtimes.jp/companyrdf.php?company_id=22933",
    ],
}


def fetch_ec_industry_news(max_items: int = 5) -> dict[str, list[dict] | None]:
    """情報源ごとに、EC業界にまつわるニュースを新しい順に返す。

    戻り値は表示名をキーに、[{"title", "link", "date"}, ...] のリスト。
    取得自体に失敗した情報源は値をNoneにする（表示側で「取得できません」に
    切り替える）。"""
    return feed_utils.fetch_feed_items(EC_INDUSTRY_NEWS_SOURCES, max_items=max_items)
