"""アサヒ・キリン・サントリー・サッポロの新商品情報を、各社のPR TIMES配信
フィード（プレスリリース配信サービス）から取得する。

各社のフィードには新商品以外のニュース（決算・人事・CMなど）も混ざっている
ため、タイトルに「新発売」「新商品」等のキーワードを含むものだけを抽出する。
取得に失敗した場合はその会社の分だけNoneとして扱い、他の会社の表示や
ダッシュボード全体には影響しないようにする。

注意: ここで使っているPR TIMESの企業ID（company_id）はWeb検索で調べた
ものであり、実際にアクセスして中身を検証できていない（この開発環境からは
外部サイトへ接続できないため）。本番環境で表示を確認し、もし特定の
メーカーだけ情報が出ない場合はcompany_idの見直しが必要になる可能性がある。
"""

from __future__ import annotations

from lib import feed_utils

PR_TIMES_COMPANY_IDS: dict[str, str] = {
    "アサヒ": "16166",
    "キリン": "73077",
    "サントリー": "42435",
    "サッポロ": "3564",
}

PRODUCT_KEYWORDS = ("新発売", "新商品", "リニューアル発売", "期間限定発売", "数量限定発売")


def fetch_new_products(max_items_per_maker: int = 5) -> dict[str, list[dict] | None]:
    """メーカーごとに、新商品と思われるプレスリリースを新しい順に返す。

    戻り値はメーカー名をキーに、[{"title", "link", "date"}, ...] のリスト。
    取得自体に失敗した会社は値をNoneにする（表示側で「取得できません」に
    切り替える）。該当する新商品ニュースが1件も見つからない会社は
    空リスト[]を返す。"""
    sources = {
        maker_name: f"https://prtimes.jp/companyrdf.php?company_id={company_id}"
        for maker_name, company_id in PR_TIMES_COMPANY_IDS.items()
    }
    return feed_utils.fetch_feed_items(sources, max_items=max_items_per_maker, keyword_filter=PRODUCT_KEYWORDS)
