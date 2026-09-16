"""松戸市・鎌ケ谷市の「お知らせ・新着情報」と地域ニュースを取得する。

各情報源のRSS/Atom/RDFフィードを取得し、タイトル・日付・リンクの一覧に
まとめる。配信元の正確なフィードURLがこの開発環境からは検証できないため
（外部サイトへ接続できない）、情報源ごとに複数の候補URLを用意し、実際に
フィードとして読み込めた最初のURLを使うようにしている（feed_utils側の
仕組み）。取得に失敗した情報源はNoneとして扱い、他の情報源の表示や
ダッシュボード全体には影響しないようにする。

本番環境で表示を確認し、それでもうまく取得できない情報源があれば
LOCAL_NEWS_SOURCESの候補URLを見直す・追加する必要がある。
"""

from __future__ import annotations

from lib import feed_utils

# 表示名 -> フィードURL候補のリスト（先頭から順に試し、最初に読み込めたものを使う）
LOCAL_NEWS_SOURCES: dict[str, list[str]] = {
    "松戸市のお知らせ・新着情報": [
        "https://www.city.matsudo.chiba.jp/rss/whatsnew.rdf",
        "https://www.city.matsudo.chiba.jp/index.rdf",
        "https://www.city.matsudo.chiba.jp/rss/index.rdf",
        "https://www.city.matsudo.chiba.jp/rss.xml",
    ],
    "松戸市の地域ニュース（松戸経済新聞）": [
        "https://matsudo.keizai.biz/rss20.xml",
        "https://matsudo.keizai.biz/index.rdf",
        "https://matsudo.keizai.biz/atom.xml",
        "https://matsudo.keizai.biz/feed/",
    ],
    "鎌ケ谷市のお知らせ・新着情報": [
        "https://www.city.kamagaya.chiba.jp/rss/whatsnew.rdf",
        "https://www.city.kamagaya.chiba.jp/index.rdf",
        "https://www.city.kamagaya.chiba.jp/rss/index.rdf",
        "https://www.city.kamagaya.chiba.jp/rss.xml",
    ],
    "鎌ケ谷市の地域ニュース（号外NET）": [
        # 実際にブラウザで開いて存在を確認済み（鎌ケ谷市・白井市・印西市の地域ニュースサイト）
        "https://kamagaya-shiroi-inzai.goguynet.jp/feed/",
        "https://www.chibanippo.co.jp/news/area/kamagaya/feed",
        "https://kamagaya.mypl.net/article/topics_kamagaya/feed",
    ],
    "松戸市の地域ニュース（松戸つうしん）": [
        # 実際にブラウザで開いて存在を確認済み
        "https://matsudo-tsushin.com/feed/",
    ],
}


def fetch_local_news(max_items: int = 5) -> dict[str, list[dict] | None]:
    """情報源ごとに、新しい記事・お知らせを新しい順に返す。

    戻り値は表示名をキーに、[{"title", "link", "date"}, ...] のリスト。
    取得自体に失敗した情報源は値をNoneにする（表示側で「取得できません」に
    切り替える）。"""
    return feed_utils.fetch_feed_items(LOCAL_NEWS_SOURCES, max_items=max_items)
