"""松戸市・鎌ケ谷市の「お知らせ・新着情報」と地域ニュースを取得する。

各情報源のRSS/Atom/RDFフィードを取得し、タイトル・日付・リンクの一覧に
まとめる。ここで指定しているフィードのURLは、公開されている情報をもとにした
推測を含んでおり、実際に正しく取得できるかはこの開発環境からは検証できて
いない（外部サイトへ接続できないため）。取得に失敗した情報源はNoneとして
扱い、他の情報源の表示やダッシュボード全体には影響しないようにする。

本番環境で表示を確認し、うまく取得できない情報源があれば
LOCAL_NEWS_SOURCESのURLを見直す必要がある。
"""

from __future__ import annotations

from lib import feed_utils

# 表示名 -> フィードURL（未検証のものを含む。ラベルの並び順で表示する）
LOCAL_NEWS_SOURCES: dict[str, str] = {
    "松戸市のお知らせ・新着情報": "https://www.city.matsudo.chiba.jp/rss/whatsnew.rdf",
    "松戸市の地域ニュース（松戸経済新聞）": "https://matsudo.keizai.biz/rss20.xml",
    "鎌ケ谷市のお知らせ・新着情報": "https://www.city.kamagaya.chiba.jp/rss/whatsnew.rdf",
    "鎌ケ谷市の地域ニュース（千葉日報 鎌ケ谷版）": "https://www.chibanippo.co.jp/news/area/kamagaya/feed",
}


def fetch_local_news(max_items: int = 5) -> dict[str, list[dict] | None]:
    """情報源ごとに、新しい記事・お知らせを新しい順に返す。

    戻り値は表示名をキーに、[{"title", "link", "date"}, ...] のリスト。
    取得自体に失敗した情報源は値をNoneにする（表示側で「取得できません」に
    切り替える）。"""
    return feed_utils.fetch_feed_items(LOCAL_NEWS_SOURCES, max_items=max_items)
