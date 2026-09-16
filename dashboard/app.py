"""複数店舗 売上ダッシュボード（ローカル・プロトタイプ版）

指定フォルダに溜まった日次売上Excelを読み込み、
日別・前年同日比・月進捗・月末着地予測を可視化する。
"""

from __future__ import annotations

import base64
import math
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import beverage_news as bn  # noqa: E402
from lib import data_loader as dl  # noqa: E402
from lib import day_facts  # noqa: E402
from lib import ec_industry_news as ec  # noqa: E402
from lib import github_sync as gh  # noqa: E402
from lib import liquor_retail_news as lr  # noqa: E402
from lib import local_news as ln  # noqa: E402

JST = ZoneInfo("Asia/Tokyo")


def today_jst() -> date:
    """日本時間での「今日」の日付を返す。Streamlit Cloudのサーバーは
    UTC（日本より9時間遅い）で動いていることが多く、date.today()を
    そのまま使うと、日本時間の深夜0時〜朝9時の間は前日の日付になって
    しまう。基準日のデフォルト値など「今日」を扱うすべての箇所で、
    date.today()ではなくこちらを使うこと。"""
    return datetime.now(JST).date()


# 店舗識別用の固定カラー順（10店舗分）。店舗が増えたら末尾に追加する。
STORE_COLORS = [
    "#4E79A7", "#F28E2B", "#59A14F", "#E15759", "#B07AA1",
    "#76B7B2", "#EDC948", "#FF9DA7", "#9C755F", "#BAB0AC",
]
PRIMARY_COLOR = "#4E79A7"
COMPARISON_COLOR = "#BAB0AC"
ACCENT_COLOR = "#F28E2B"
KPI_BLUE = "rgb(6, 81, 201)"
KPI_GREEN = "rgb(3, 138, 52)"

WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]

# 店舗一覧・グラフ・テーブルで使う表示順（指定が無い店舗は末尾にアルファベット順で追加）。
STORE_DISPLAY_ORDER = [
    "本店", "矢切店", "楽天", "Yahoo", "ドリクラ", "amazon",
    "auPAY1", "winecom", "auPAY2", "dショッピング", "LINEギフト",
    "ストーリーセゾン", "Qoo10",
]

DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data" / "incoming"

LOGO_PATH = Path(__file__).resolve().parent / "assets" / "bigboss_logo.png"
LOGO_B64 = base64.b64encode(LOGO_PATH.read_bytes()).decode() if LOGO_PATH.exists() else ""


def order_stores(stores: list[str]) -> list[str]:
    """STORE_DISPLAY_ORDERの並び順にする（未登録の店舗名は末尾にアルファベット順で追加）。"""
    stores_set = set(stores)
    ordered = [s for s in STORE_DISPLAY_ORDER if s in stores_set]
    extra = sorted(stores_set - set(STORE_DISPLAY_ORDER))
    return ordered + extra


def reorder_by_store(df: pd.DataFrame, store_order: list[str], store_col: str = "store") -> pd.DataFrame:
    """データフレームの行をstore_orderの並び順に揃える（存在する店舗のみ）。"""
    present_order = [s for s in store_order if s in set(df[store_col])]
    return df.set_index(store_col).loc[present_order].reset_index()

st.set_page_config(
    page_title="売上ダッシュボード",
    page_icon=Image.open(LOGO_PATH) if LOGO_PATH.exists() else None,
    layout="wide",
)


def render_home_screen_icon_tags() -> None:
    """スマホでホーム画面に追加した際、アイコンがBIGBOSSロゴになるようにする。
    Streamlitはページの<head>を直接編集する手段が無いため、components.htmlの
    iframe内スクリプトから親ページ（window.parent.document）のheadに
    apple-touch-icon等のタグを追加している（既に追加済みなら何もしない）。
    iOSの「ホーム画面に追加」はdata:URIのアイコンを認識しないことがあるため、
    server.enableStaticServing（.streamlit/config.toml）で公開した
    static/bigboss_logo.png への実URLを使う。"""
    components.html(
        f"""
        <script>
          (function() {{
            var head = window.parent.document.querySelector('head');
            if (head.querySelector('link[rel="apple-touch-icon"]')) {{ return; }}
            var logoUrl = window.parent.location.origin + '/app/static/bigboss_logo.png';

            var appleIcon = document.createElement('link');
            appleIcon.rel = 'apple-touch-icon';
            appleIcon.href = logoUrl;
            head.appendChild(appleIcon);

            var icon = document.createElement('link');
            icon.rel = 'icon';
            icon.href = logoUrl;
            head.appendChild(icon);

            var capable = document.createElement('meta');
            capable.name = 'apple-mobile-web-app-capable';
            capable.content = 'yes';
            head.appendChild(capable);

            var title = document.createElement('meta');
            title.name = 'apple-mobile-web-app-title';
            title.content = '売上ダッシュボード';
            head.appendChild(title);
          }})();
        </script>
        """,
        height=1,
    )


render_home_screen_icon_tags()

# スマートフォンなど狭い画面向けの調整（余白・文字サイズを詰めて情報を収めやすくする）。
# レイアウトの列(st.columns)自体はStreamlit標準機能で狭い画面では自動的に縦積みになる。
st.markdown(
    """
    <style>
    @media (max-width: 640px) {
        .block-container { padding-left: 1rem !important; padding-right: 1rem !important; padding-top: 2rem !important; }
        div[data-testid="stMetricValue"] { font-size: 1.4rem !important; }
        div[data-testid="stMetricLabel"] { font-size: 0.8rem !important; }
        [data-testid="stMarkdownContainer"] h1, h1 { font-size: 1.6rem !important; }
        [data-testid="stMarkdownContainer"] h3, [data-testid="stMarkdownContainer"] h4, h3, h4 { font-size: 1.05rem !important; }

        /* 表示店舗・対象日バッジを横並びのまま縮小し、スマホ幅でも1行に収める（高さも揃える） */
        .hdr-badges-row { flex-wrap: nowrap !important; gap: 8px !important; margin-bottom: 10px !important; align-items: stretch !important; }
        .hdr-store-badge, .hdr-date-badge { display: flex !important; flex-direction: column !important; }
        .hdr-badge-label { font-size: 0.72rem !important; margin-bottom: 3px !important; }
        .hdr-store-box, .hdr-date-box { min-height: 52px !important; box-sizing: border-box !important; flex: 1 1 auto !important; }
        .hdr-store-box { padding: 8px 12px !important; }
        .hdr-store-value { font-size: 1.05rem !important; }
        .hdr-date-box { padding: 8px 14px 8px 26px !important; gap: 5px !important; }
        .hdr-date-flag { border-left-width: 20px !important; border-bottom-width: 20px !important; }
        .hdr-date-year { font-size: 0.8rem !important; }
        .hdr-date-main { font-size: 1.6rem !important; }
        .hdr-date-weekday { font-size: 1.05rem !important; }

        /* 「対象日・表示店舗を変更」ボタン: 上のバッジとの間は狭く、下のKPIブロックとの間は広く */
        .st-key-edit_button_row { margin-top: -18px !important; margin-bottom: 18px !important; }

        /* スマホでは列数の多い表を、横スクロール不要なコンパクト表に差し替える */
        .st-key-daily_store_table_pc, .st-key-ranking_table_pc { display: none !important; }

        /* KPIブロックを4列1行ではなく2列2行に（minmax(0,...)で右列がはみ出さないようにする） */
        .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; gap: 10px !important; }
        .kpi-block { padding: 16px 10px !important; min-height: 120px !important; }
        .kpi-label { font-size: 0.78rem !important; }
        .kpi-value { font-size: 1.6rem !important; }
        .kpi-caption { font-size: 0.78rem !important; }

        /* 棒グラフはPC版を隠し、スマホ向け（軸タイトル無し・万円単位）を表示 */
        .st-key-daily_chart_pc, .st-key-daily_store_chart_pc,
        .st-key-ranking_chart_pc, .st-key-monthly_chart_pc { display: none !important; }

        /* 店舗別売上カード（日/月切り替え）はスマホでは2列 */
        .ds-cards-grid { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; }

    }
    @media (min-width: 641px) {
        /* PC/タブレットでは、スマホ向けのコンパクト表・グラフ・グリッドを隠す（PC側の見た目は変更しない） */
        .st-key-daily_store_table_mobile, .st-key-ranking_table_mobile { display: none !important; }
        .st-key-daily_chart_mobile, .st-key-daily_store_chart_mobile,
        .st-key-ranking_chart_mobile, .st-key-monthly_chart_mobile { display: none !important; }
        .st-key-scroll_top_btn_container { display: none !important; }

        /* PCの表見出しは中央揃え */
        .st-key-daily_store_heading h4, .st-key-ranking_heading h4 { text-align: center !important; }
    }
    @media (max-width: 640px) {
        /* 最上部に戻るボタン（スマホのみ表示）。中身はcomponents.htmlのiframeなので、
           コンテナごと画面左下に固定表示する。 */
        .st-key-scroll_top_btn_container {
            display: block !important;
            position: fixed !important;
            left: 16px !important;
            bottom: 16px !important;
            width: 60px !important;
            height: 60px !important;
            z-index: 9999 !important;
        }
        .st-key-scroll_top_btn_container iframe {
            width: 60px !important;
            height: 60px !important;
            border: none !important;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

def render_scroll_top_button() -> None:
    """最上部に戻るボタン（スマホのみ表示）。st.markdownのHTMLはonclick等のイベント属性が
    無効化されるため、components.htmlで独立したiframeとして描画し、その中でJSを実行する。
    iframe自体はst.container(key=...)経由でCSSにより画面左下に固定表示させている。"""
    with st.container(key="scroll_top_btn_container"):
        components.html(
            """
            <style>
              html, body { margin:0; padding:0; background:transparent; overflow:hidden; }
              .scroll-top-btn {
                width:60px; height:60px; border-radius:50%; border:none;
                display:flex; align-items:center; justify-content:center;
                background:#3a3a3a; color:#ffffff; font-size:3rem; line-height:1;
                box-shadow:0 4px 14px rgba(0,0,0,0.28); cursor:pointer;
                opacity:1; transition:opacity 0.3s ease;
              }
              .scroll-top-btn.is-scrolling { opacity:0.25; }
            </style>
            <button class="scroll-top-btn" id="scrollTopBtn" title="最上部へ戻る">▲</button>
            <script>
              (function() {
                function getScrollTargets() {
                  var doc = window.parent.document;
                  var targets = [];
                  ["stMain", "stAppViewContainer"].forEach(function(t) {
                    var el = doc.querySelector('[data-testid="' + t + '"]');
                    if (el) { targets.push(el); }
                  });
                  return targets;
                }
                var btn = document.getElementById("scrollTopBtn");
                btn.addEventListener("click", function() {
                  getScrollTargets().forEach(function(el) {
                    el.scrollTo({top: 0, behavior: "smooth"});
                  });
                });
                var fadeTimer = null;
                function onScroll() {
                  btn.classList.add("is-scrolling");
                  clearTimeout(fadeTimer);
                  fadeTimer = setTimeout(function() {
                    btn.classList.remove("is-scrolling");
                  }, 400);
                }
                getScrollTargets().forEach(function(el) {
                  el.addEventListener("scroll", onScroll, true);
                });
              })();
            </script>
            """,
            height=60,
        )


def format_yen(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"¥{value:,.0f}"


def format_yen_compact(value: float | None) -> str:
    """KPIカード表示用。桁数が大きいと横幅からはみ出して省略されるため、
    億・万円単位で短く表示する（詳細な金額はテーブルやヘルプ側で確認できる）。"""
    if value is None or pd.isna(value):
        return "—"
    abs_value = abs(value)
    if abs_value >= 1e8:
        return f"¥{value / 1e8:,.2f}億"
    if abs_value >= 1e4:
        return f"¥{value / 1e4:,.0f}万"
    return f"¥{value:,.0f}"


def format_pct(value: float | None) -> str:
    """前年に対する対比％を表示する（100%が前年と同水準、95%なら前年比95%）。"""
    if value is None or pd.isna(value):
        return "—"
    return f"{value:.1f}%"


def format_delta(diff: float | None, pct: float | None) -> str | None:
    """st.metricのdelta表示用。前年差分額（億・万円単位）と前年比をまとめる。"""
    if diff is None or pd.isna(diff):
        return None
    sign = "+" if diff >= 0 else "-"
    text = f"{sign}{format_yen_compact(abs(diff))}"
    if pct is not None and not pd.isna(pct):
        text += f" ({format_pct(pct)})"
    return text


def store_color_map(stores: list[str]) -> dict[str, str]:
    return {store: STORE_COLORS[i % len(STORE_COLORS)] for i, store in enumerate(sorted(stores))}


def symbol_for_ratio(pct: float | None) -> str:
    """対比％を4段階の記号にする（◎150%以上・〇149~100%・▽99~90%・×89%以下）。"""
    if pct is None or pd.isna(pct):
        return ""
    if pct >= 150:
        return "◎"
    if pct >= 100:
        return "〇"
    if pct >= 90:
        return "▽"
    return "×"


def _kpi_block_html(
    label: str,
    value: str,
    bg_color: str,
    symbol: str = "",
    caption: str | None = None,
    tooltip: str | None = None,
) -> str:
    """色分けされたKPIブロック1個分のHTMLを組み立てる。"""
    symbol_html = f'<span style="margin-right:8px;">{symbol}</span>' if symbol else ""
    caption_html = (
        f'<div class="kpi-caption" style="font-size:calc(0.85rem + 2px); opacity:0.9; margin-top:10px;">{caption}</div>'
        if caption
        else ""
    )
    title_attr = f' title="{tooltip}"' if tooltip else ""
    return f"""
        <div class="kpi-block"{title_attr} style="background-color:{bg_color}; color:#ffffff; border-radius:10px;
                    padding:22px 14px; text-align:center; min-height:168px;
                    display:flex; flex-direction:column; justify-content:center; min-width:0;">
          <div class="kpi-label" style="font-size:0.9rem; opacity:0.9;">{label}</div>
          <div class="kpi-value" style="font-size:2.4rem; font-weight:800; margin-top:10px; white-space:nowrap;">
            {symbol_html}{value}
          </div>
          {caption_html}
        </div>
        """


def render_kpi_grid(blocks: list[dict]) -> None:
    """4つのKPIブロックをCSSグリッドで並べる。PCでは4列、スマホ（640px以下）では
    「kpi-grid」クラスへのメディアクエリにより自動的に2列×2行に切り替わる。"""
    items_html = "".join(_kpi_block_html(**block) for block in blocks)
    st.markdown(
        f"""
        <div class="kpi-grid" style="display:grid; grid-template-columns:repeat(4, 1fr); gap:16px;">
          {items_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_daily_store_cards(df: pd.DataFrame) -> None:
    """店舗ごとの売上を、日別（青）/月別（オレンジ）を切り替えられるカードで表示する
    （PCでは4列、スマホでは2列）。カードは1枚ずつ独立してタップで切り替えられる
    （タップしたカードだけが日別⇔月別に切り替わり、他のカードは変わらない）。
    上部の「日」「月」ボタンは、全カードをまとめて日別／月別に揃えたいときに使う。
    切り替え時は軽いアニメーションを付けている。
    （st.markdownのHTMLに埋め込んだラジオボタン等はStreamlit側でクリックの
    既定動作が働かず操作できないため、実際の切り替えはst.buttonで行っている。
    カードタップでの切り替えも、カード1枚ごとに見た目の上へ透明なst.buttonを
    重ねて実現している）"""
    stores = df["store"].tolist()
    if "ds_card_view" not in st.session_state:
        st.session_state["ds_card_view"] = "daily"
    if "ds_card_view_per_store" not in st.session_state:
        st.session_state["ds_card_view_per_store"] = {}
    per_store_view = st.session_state["ds_card_view_per_store"]
    is_daily = st.session_state["ds_card_view"] == "daily"

    with st.container(key="ds_toggle_row"):
        toggle_col1, toggle_col2 = st.columns(2)
        with toggle_col1:
            if st.button("日", key="ds_toggle_daily_btn", use_container_width=True):
                st.session_state["ds_card_view"] = "daily"
                for store in stores:
                    per_store_view[store] = "daily"
                st.rerun()
        with toggle_col2:
            if st.button("月", key="ds_toggle_monthly_btn", use_container_width=True):
                st.session_state["ds_card_view"] = "monthly"
                for store in stores:
                    per_store_view[store] = "monthly"
                st.rerun()

    st.markdown(
        f"""
        <style>
          .st-key-ds_toggle_row div[data-testid="stHorizontalBlock"] {{
            flex-wrap:nowrap !important; gap:10px !important;
          }}
          .st-key-ds_toggle_row div[data-testid="stColumn"] {{
            flex:1 1 0 !important; width:auto !important; min-width:0 !important;
          }}
          @media (min-width: 641px) {{
            /* PCのみ: 日/月ボタンを右寄せにし、売上サマリーの対象日バッジ程度の大きさに縮小する */
            .st-key-ds_toggle_row div[data-testid="stHorizontalBlock"] {{
              max-width: 285px !important; margin-left: auto !important; margin-right: 0 !important;
            }}
            .st-key-ds_toggle_daily_btn button, .st-key-ds_toggle_monthly_btn button {{
              min-height: 64px !important;
            }}
          }}
          .st-key-ds_toggle_daily_btn button, .st-key-ds_toggle_monthly_btn button {{
            color:#ffffff !important; border:none !important; font-weight:700 !important;
            opacity:0.45; transition:opacity 0.2s ease, transform 0.2s ease;
          }}
          .st-key-ds_toggle_daily_btn button {{ background:{KPI_BLUE} !important; }}
          .st-key-ds_toggle_monthly_btn button {{ background:{ACCENT_COLOR} !important; }}
          .st-key-ds_toggle_daily_btn button:hover, .st-key-ds_toggle_monthly_btn button:hover {{
            color:#ffffff !important;
          }}
          .st-key-ds_toggle_{'daily' if is_daily else 'monthly'}_btn button {{
            opacity:1; transform:scale(1.03);
          }}
          @keyframes ds-card-in {{
            from {{ transform:rotateY(90deg); opacity:0; }}
            to {{ transform:rotateY(0deg); opacity:1; }}
          }}
          .ds-cards-grid, .st-key-ds_cards_tap_overlay {{
            display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:10px;
          }}
          .ds-cards-grid {{ margin-top:10px; margin-bottom:16px; }}
          .ds-card {{
            color:#ffffff; border-radius:10px;
            padding:14px 10px; text-align:center; min-width:0;
            display:flex; flex-direction:column; justify-content:center;
            animation: ds-card-in 0.35s ease;
          }}
          .ds-card-daily {{ background:{KPI_BLUE}; }}
          .ds-card-monthly {{ background:{ACCENT_COLOR}; }}
          .ds-store-name {{
            font-size:0.8rem; opacity:0.9; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
          }}
          .ds-value {{ font-size:1.5rem; font-weight:800; margin-top:4px; white-space:nowrap; }}
          .ds-pct {{ font-size:1.2rem; font-weight:400; margin-top:2.7px; white-space:nowrap; }}
          @media (max-width: 640px) {{
            .st-key-ds_cards_tap_overlay {{ grid-template-columns:repeat(2, minmax(0, 1fr)) !important; }}
          }}
          @media (min-width: 641px) {{
            /* PCのみ: カード間のスペースを2倍に、対比の文字は1.62remからさらに80%に、100%以上は黄色にする */
            .ds-cards-grid, .st-key-ds_cards_tap_overlay {{ gap: 20px !important; }}
            .ds-value {{ font-size: 2.4rem !important; }}
            .ds-pct {{ font-size: 1.296rem !important; }}
            .ds-pct-good {{ color: #ffff00 !important; }}
          }}
          .st-key-ds_cards_tap_wrapper {{ position: relative; }}
          .st-key-ds_cards_tap_wrapper > div:has(.st-key-ds_cards_tap_overlay) {{
            position: absolute !important; inset: 0 !important; margin: 0 !important;
            width: 100% !important; height: 100% !important;
          }}
          .st-key-ds_cards_tap_overlay {{ width: 100%; height: 100%; }}
          .st-key-ds_cards_tap_overlay div[data-testid="stElementContainer"] {{
            width: 100% !important; height: 100% !important; margin: 0 !important;
          }}
          .st-key-ds_cards_tap_overlay div[data-testid="stButton"] {{
            width: 100% !important; height: 100% !important;
          }}
          .st-key-ds_cards_tap_overlay div[data-testid="stButton"] button {{
            width: 100% !important; height: 100% !important; opacity: 0; cursor: pointer;
            border: none !important; background: transparent !important; padding: 0 !important;
          }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    slash = '<span style="font-size:0.55em; opacity:0.85;">/</span>'

    def _man(value: float | None) -> str:
        return "—" if value is None or pd.isna(value) else f"{value / 10000:,.0f}"

    cards_html = ""
    for _, row in df.iterrows():
        store_is_daily = per_store_view.get(row["store"], "daily") == "daily"
        if store_is_daily:
            main_value = f"{_man(row['sales'])}{slash}{_man(row['last_year_sales'])}"
            pct_num = row["yoy_pct"]
        else:
            main_value = f"{_man(row['mtd_sales'])}{slash}{_man(row['last_year_mtd_sales'])}"
            pct_num = row["mtd_yoy_pct"]
        pct_value = format_pct(pct_num)
        pct_class = "ds-pct ds-pct-good" if pd.notna(pct_num) and pct_num >= 100 else "ds-pct"
        card_class = "ds-card ds-card-daily" if store_is_daily else "ds-card ds-card-monthly"
        # 1行にまとめて書く（複数行にすると、間の空白行がMarkdown側に「HTMLブロックの
        # 終わり」と誤認識され、以降がコードブロック扱いになってしまうため）。
        cards_html += (
            f'<div class="{card_class}">'
            f'<div class="ds-store-name">{row["store"]}</div>'
            f'<div class="ds-value">{main_value}</div>'
            f'<div class="{pct_class}">{pct_value}</div>'
            "</div>"
        )
    with st.container(key="ds_cards_tap_wrapper"):
        st.markdown(f'<div class="ds-cards-grid">{cards_html}</div>', unsafe_allow_html=True)
        with st.container(key="ds_cards_tap_overlay"):
            for i, store in enumerate(stores):
                if st.button(f"{store}を切り替え", key=f"ds_card_tap_{i}"):
                    current = per_store_view.get(store, "daily")
                    per_store_view[store] = "monthly" if current == "daily" else "daily"
                    st.rerun()


def store_display_label(selected: list[str], all_stores: list[str]) -> str:
    """サイドバーの店舗選択状況を、バッジ表示用の短い文字列にする。"""
    if not selected or len(selected) == len(all_stores):
        return "全店舗"
    if len(selected) <= 2:
        return "・".join(selected)
    return f"{selected[0]} 他{len(selected) - 1}店"


def render_header_badges(store_label: str, target_date: date) -> None:
    """右上に「表示店舗」「対象日」の2つのバッジを、幅に応じて並べて表示する。
    2つを1つのflexコンテナにまとめることで、列幅の制約による表示崩れを避けている。"""
    weekday = WEEKDAY_JP[target_date.weekday()]
    st.markdown(
        f"""
        <div class="hdr-badges-row" style="display:flex; justify-content:flex-end; align-items:flex-start;
                    gap:16px; flex-wrap:wrap; margin-bottom:28px;">
          <div class="hdr-store-badge" style="text-align:right;">
            <div class="hdr-badge-label" style="font-size:1rem; color:#8a8a8a; margin-bottom:6px;">表示店舗</div>
            <div class="hdr-store-box" style="display:inline-flex; align-items:center; justify-content:center;
                        padding:12px 22px; border-radius:10px; min-height:64px;
                        background:#fff; border:1px solid #e6e6e6;
                        box-shadow:0 2px 6px rgba(0,0,0,0.10);">
              <span class="hdr-store-value" style="font-size:1.5rem; font-weight:800; color:#1a1a1a; white-space:nowrap;">
                {store_label}
              </span>
            </div>
          </div>
          <div class="hdr-date-badge" style="text-align:right;">
            <div class="hdr-badge-label" style="font-size:1rem; color:#8a8a8a; margin-bottom:6px;">対象日</div>
            <div class="hdr-date-box" style="position:relative; display:inline-flex; align-items:center; gap:10px;
                        padding:12px 32px 12px 48px; border-radius:10px;
                        background:#fff; border:1px solid #e6e6e6;
                        box-shadow:0 2px 6px rgba(0,0,0,0.10);">
              <div class="hdr-date-flag" style="position:absolute; top:0; left:0; width:0; height:0;
                          border-left:32px solid {ACCENT_COLOR};
                          border-bottom:32px solid transparent;
                          border-top-left-radius:10px;"></div>
              <span class="hdr-date-year" style="writing-mode:vertical-rl; font-size:1.4rem; font-weight:800;
                           color:{ACCENT_COLOR}; letter-spacing:1px;">
                {target_date.year}
              </span>
              <span class="hdr-date-main" style="font-size:3rem; font-weight:800; color:#1a1a1a;">
                {target_date.month}.{target_date.day}
              </span>
              <span class="hdr-date-weekday" style="font-size:2.1rem; font-weight:600; color:#555;">
                [{weekday}]
              </span>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_progress_bar(elapsed: int, total: int) -> None:
    """月の経過日数をグラデーションのプログレスバーで表示する。"""
    pct = (elapsed / total * 100) if total else 0
    st.markdown(
        f"""
        <div style="margin:4px 0 20px 0;">
          <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:8px;">
            <span style="font-size:1.7rem; font-weight:800; color:#1a1a1a;">
              {elapsed}<span style="font-size:1rem; font-weight:600; color:#8a8a8a;"> / {total}日経過</span>
            </span>
            <span style="font-size:1.3rem; font-weight:700; color:{ACCENT_COLOR};">{pct:.0f}%</span>
          </div>
          <div style="width:100%; height:14px; border-radius:7px; background:#eef0f3;
                      overflow:hidden; box-shadow:inset 0 1px 2px rgba(0,0,0,0.08);">
            <div style="width:{pct:.1f}%; height:100%; border-radius:7px;
                        background:linear-gradient(90deg, {PRIMARY_COLOR}, {ACCENT_COLOR});
                        box-shadow:0 1px 3px rgba(0,0,0,0.2);"></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _nice_tick_step(max_value: float, target_ticks: int = 5) -> float:
    """データの最大値から、5個前後になるようなキリの良い目盛り間隔を決める。"""
    if max_value <= 0:
        return 1
    rough_step = max_value / target_ticks
    magnitude = 10 ** math.floor(math.log10(rough_step))
    residual = rough_step / magnitude
    if residual <= 1:
        nice = 1
    elif residual <= 2:
        nice = 2
    elif residual <= 5:
        nice = 5
    else:
        nice = 10
    return nice * magnitude


def _format_man_unit(man_value: float) -> str:
    """万単位の数値を日本語らしい表記にする（例: 10000→1億、5000→5千万、300→300万）。"""
    if man_value == 0:
        return "0"
    if man_value % 10000 == 0:
        return f"{man_value / 10000:,.0f}億"
    if man_value % 1000 == 0:
        return f"{man_value / 1000:,.0f}千万"
    return f"{man_value:,.0f}万"


def _rescale_chart_to_man(fig: go.Figure) -> tuple[go.Figure, list[float]]:
    """グラフの複製を作り、全トレースのY値を万円単位に変換する（元の正確な金額は
    customdataに保持し、ホバー表示に使う）。戻り値は複製したFigureと、
    キリの良い目盛り位置（万単位）のリスト。"""
    fig_scaled = go.Figure(fig)
    scaled_values: list[float] = []
    for trace in fig_scaled.data:
        y = getattr(trace, "y", None)
        if y is None:
            continue
        original = list(y)
        trace.customdata = original
        scaled = [None if v is None else v / 10000 for v in original]
        trace.y = scaled
        trace.hovertemplate = "%{x}<br>%{customdata:,.0f}円<extra></extra>"
        scaled_values.extend(v for v in scaled if v is not None)

    max_value = max(scaled_values) if scaled_values else 0
    step = _nice_tick_step(max_value)
    ticks = []
    v = 0.0
    while v <= max_value + step:
        ticks.append(v)
        v += step

    fig_scaled.update_layout(
        hoverlabel=dict(bgcolor="#ffffff", font=dict(size=17, color="#1a1a1a"))
    )
    return fig_scaled, ticks


def to_mobile_chart(fig: go.Figure) -> go.Figure:
    """スマホ向けに、Y軸タイトルを消し、目盛りを万円単位（キリが良ければ千万単位）に
    したグラフの複製を作る（PC版のグラフはそのまま、スマホ版だけ別に描画するための複製）。
    指でスライドした際に意図せずズーム・パンして表示が変わってしまわないよう、
    ドラッグ操作は無効化している（ツールバーを隠しているため元に戻す手段が無いため）。"""
    fig_m, ticks = _rescale_chart_to_man(fig)
    fig_m.update_xaxes(fixedrange=True)
    fig_m.update_yaxes(
        title=None,
        tickmode="array",
        tickvals=ticks,
        ticktext=[_format_man_unit(t) for t in ticks],
        fixedrange=True,
    )
    fig_m.update_layout(dragmode=False)
    return fig_m


def apply_pc_chart_style(fig: go.Figure, height_multiplier: float = 1.5) -> go.Figure:
    """PC向けに、目盛りをスマホ版と同じ万円単位表記にしつつ軸タイトルは残し、
    グラフ高さを拡大した複製を作る。"""
    fig_p, ticks = _rescale_chart_to_man(fig)
    fig_p.update_yaxes(
        title="売上金額（万円）",
        tickmode="array",
        tickvals=ticks,
        ticktext=[_format_man_unit(t) for t in ticks],
    )
    if fig_p.layout.height:
        fig_p.update_layout(height=fig_p.layout.height * height_multiplier)
    return fig_p


def render_section_break() -> None:
    """日別グループと月別グループの境目を、通常のdividerより太く目立たせる。"""
    st.markdown(
        f"""
        <hr style="border:none; height:5px; margin:28px 0 24px 0; border-radius:3px;
                   background:linear-gradient(90deg, {PRIMARY_COLOR}, {ACCENT_COLOR});">
        """,
        unsafe_allow_html=True,
    )


def render_compact_table(df: pd.DataFrame, sticky_first_col: bool = False) -> None:
    """スマホ向けの、コンパクトな表を描画する。列数を絞れば横スクロール無しで収まる。
    sticky_first_col=Trueの場合は全列を表示しつつ、1列目（店舗名など）を
    左側に固定したまま残りの列だけを横スクロールできるようにする。"""
    first_col_style = (
        "position:sticky; left:0; background:#fff; z-index:1;" if sticky_first_col else ""
    )
    header_cells = "".join(
        f'<th style="text-align:left; padding:6px 8px; font-size:0.72rem; color:#8a8a8a; '
        f'font-weight:600; border-bottom:1px solid #e6e6e6; white-space:nowrap;'
        f'{first_col_style if i == 0 else ""}">{col}</th>'
        for i, col in enumerate(df.columns)
    )
    rows_html = ""
    for _, row in df.iterrows():
        cells = "".join(
            f'<td style="padding:7px 8px; font-size:0.85rem; color:#1a1a1a; '
            f'border-bottom:1px solid #f0f0f0; white-space:nowrap;'
            f'{first_col_style if i == 0 else ""}">{value}</td>'
            for i, value in enumerate(row)
        )
        rows_html += f"<tr>{cells}</tr>"
    st.markdown(
        f"""
        <div style="overflow-x:auto; background:#ffffff;">
          <table style="width:100%; border-collapse:collapse; background:#ffffff;">
            <thead><tr>{header_cells}</tr></thead>
            <tbody>{rows_html}</tbody>
          </table>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_pc_table(df: pd.DataFrame, low_yoy_mask: pd.Series, store_col: str = "店舗") -> None:
    """PC向けの表を描画する。店舗列は中央揃え、その他の数値列は右揃えにし、
    前年比が99.9%以下の店舗は行全体を薄い赤で強調する（低調な店舗を一目で分かるように）。
    （st.dataframe/st.tableはセルごとのtext-align指定を無視して列の型で自動判定してしまう
    ため、render_compact_table同様に生のHTMLテーブルとして描画している）"""
    header_cells = "".join(
        f'<th style="padding:10px 14px; font-size:0.85rem; color:#8a8a8a; font-weight:600; '
        f'border-bottom:2px solid #e0e0e0; white-space:nowrap; '
        f'text-align:{"center" if col == store_col else "right"};">{col}</th>'
        for col in df.columns
    )
    rows_html = ""
    for idx, row in df.iterrows():
        row_bg = "background-color:#fdecea;" if low_yoy_mask.get(idx, False) else ""
        cells = "".join(
            f'<td style="padding:10px 14px; font-size:0.95rem; color:#1a1a1a; '
            f'border-bottom:1px solid #f0f0f0; white-space:nowrap; '
            f'text-align:{"center" if col == store_col else "right"};">{value}</td>'
            for col, value in row.items()
        )
        rows_html += f'<tr style="{row_bg}">{cells}</tr>'
    st.markdown(
        f"""
        <div style="overflow-x:auto; background:#ffffff;">
          <table style="width:100%; border-collapse:collapse; background:#ffffff;">
            <thead><tr>{header_cells}</tr></thead>
            <tbody>{rows_html}</tbody>
          </table>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_record_metrics(records: list[dict], label_fn) -> None:
    """記録（日商・月商ギネスなど）の上位N件を、年間前年比と同じst.metricの
    並びで表示する（ラベル・金額・正確な金額のツールチップという構成）。"""
    if not records:
        st.caption("データがありません")
        return
    cols = st.columns(len(records))
    for i, (col, rec) in enumerate(zip(cols, records)):
        col.metric(
            label_fn(i, rec),
            format_yen_compact(rec["sales"]),
            help=format_yen(rec["sales"]),
        )


def render_calendar_section(embed_src: str) -> None:
    """ダッシュボード下部にGoogleカレンダーの予定表を埋め込み表示する
    （見た目はGoogle側のものをそのまま表示し、アプリ全体のデザインとは別枠）。"""
    st.markdown("#### 予定表")
    components.html(
        f'<iframe src="{embed_src}" style="border:0; width:100%; height:1000px;" '
        f'frameborder="0" scrolling="no"></iframe>',
        height=1020,
    )


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def _cached_beverage_news() -> dict[str, list[dict] | None]:
    """各メーカーの新商品情報を6時間キャッシュする（表示のたびに毎回
    外部サイトへ取得しに行かないようにするため）。"""
    return bn.fetch_new_products()


def render_beverage_news_section() -> None:
    """アサヒ・キリン・サントリー・サッポロの新商品情報を、各社のプレス
    リリース配信情報から取得して一覧表示する。取得に失敗した会社は
    「取得できません」と表示し、他の会社の表示やダッシュボード全体には
    影響しないようにする。"""
    st.markdown("#### 新商品情報（アサヒ・キリン・サントリー・サッポロ）")
    st.caption("各メーカーのプレスリリース配信情報をもとに自動表示しています（新しい順・各社最大5件、6時間おきに更新）。")

    with st.container(key="beverage_news_row"):
        news_by_maker = _cached_beverage_news()
        maker_cols = st.columns(2)
        for i, maker_name in enumerate(bn.PR_TIMES_COMPANY_IDS):
            with maker_cols[i % 2]:
                st.markdown(f"**{maker_name}**")
                items = news_by_maker.get(maker_name)
                if items is None:
                    st.caption("現在情報を取得できません")
                elif not items:
                    st.caption("新商品情報が見つかりませんでした")
                else:
                    for item in items:
                        date_prefix = f"{item['date']}　" if item["date"] else ""
                        st.markdown(f"- {date_prefix}[{item['title']}]({item['link']})")
    st.markdown(
        """
        <style>
          .st-key-beverage_news_row div[data-testid="stHorizontalBlock"] {
            flex-wrap: wrap !important; gap: 16px 24px !important;
          }
          .st-key-beverage_news_row div[data-testid="stColumn"] {
            flex: 1 1 45% !important; min-width: 240px !important;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def _cached_local_news() -> dict[str, list[dict] | None]:
    """松戸市・鎌ケ谷市の情報を6時間キャッシュする（表示のたびに毎回
    外部サイトへ取得しに行かないようにするため）。"""
    return ln.fetch_local_news()


def render_local_news_section() -> None:
    """松戸市・鎌ケ谷市の「お知らせ・新着情報」と地域ニュースを一覧表示する。
    取得に失敗した情報源は「取得できません」と表示し、他の情報源の表示や
    ダッシュボード全体には影響しないようにする。"""
    st.markdown("#### 地域情報（松戸市・鎌ケ谷市）")
    st.caption("各情報源の更新情報をもとに自動表示しています（新しい順・最大5件、6時間おきに更新）。")

    with st.container(key="local_news_row"):
        news_by_source = _cached_local_news()
        source_cols = st.columns(2)
        for i, source_label in enumerate(ln.LOCAL_NEWS_SOURCES):
            with source_cols[i % 2]:
                st.markdown(f"**{source_label}**")
                items = news_by_source.get(source_label)
                if items is None:
                    st.caption("現在情報を取得できません")
                elif not items:
                    st.caption("情報が見つかりませんでした")
                else:
                    for item in items:
                        date_prefix = f"{item['date']}　" if item["date"] else ""
                        st.markdown(f"- {date_prefix}[{item['title']}]({item['link']})")
    st.markdown(
        """
        <style>
          .st-key-local_news_row div[data-testid="stHorizontalBlock"] {
            flex-wrap: wrap !important; gap: 16px 24px !important;
          }
          .st-key-local_news_row div[data-testid="stColumn"] {
            flex: 1 1 45% !important; min-width: 240px !important;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def _cached_liquor_retail_news() -> dict[str, list[dict] | None]:
    """酒販店小売業ニュースを6時間キャッシュする（表示のたびに毎回
    外部サイトへ取得しに行かないようにするため）。"""
    return lr.fetch_liquor_retail_news()


def render_liquor_retail_news_section() -> None:
    """酒販店小売業に関するニュース（業界団体・業界紙）を一覧表示する。
    取得に失敗した情報源は「取得できません」と表示し、他の情報源の表示や
    ダッシュボード全体には影響しないようにする。"""
    st.markdown("#### 酒販店小売業ニュース")
    st.caption("各情報源の更新情報をもとに自動表示しています（新しい順・最大5件、6時間おきに更新）。")

    with st.container(key="liquor_retail_news_row"):
        news_by_source = _cached_liquor_retail_news()
        source_cols = st.columns(2)
        for i, source_label in enumerate(lr.LIQUOR_RETAIL_NEWS_SOURCES):
            with source_cols[i % 2]:
                st.markdown(f"**{source_label}**")
                items = news_by_source.get(source_label)
                if items is None:
                    st.caption("現在情報を取得できません")
                elif not items:
                    st.caption("情報が見つかりませんでした")
                else:
                    for item in items:
                        date_prefix = f"{item['date']}　" if item["date"] else ""
                        st.markdown(f"- {date_prefix}[{item['title']}]({item['link']})")
    st.markdown(
        """
        <style>
          .st-key-liquor_retail_news_row div[data-testid="stHorizontalBlock"] {
            flex-wrap: wrap !important; gap: 16px 24px !important;
          }
          .st-key-liquor_retail_news_row div[data-testid="stColumn"] {
            flex: 1 1 45% !important; min-width: 240px !important;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def _cached_ec_industry_news() -> dict[str, list[dict] | None]:
    """EC業界にまつわるニュースを6時間キャッシュする（表示のたびに毎回
    外部サイトへ取得しに行かないようにするため）。"""
    return ec.fetch_ec_industry_news()


def render_ec_industry_news_section() -> None:
    """EC業界の動向ニュースと、出店中のECモール運営会社の最新ニュースを
    一覧表示する。取得に失敗した情報源は「取得できません」と表示し、他の
    情報源の表示やダッシュボード全体には影響しないようにする。"""
    st.markdown("#### EC業界ニュース")
    st.caption("各情報源の更新情報をもとに自動表示しています（新しい順・最大5件、6時間おきに更新）。")

    with st.container(key="ec_industry_news_row"):
        news_by_source = _cached_ec_industry_news()
        source_cols = st.columns(2)
        for i, source_label in enumerate(ec.EC_INDUSTRY_NEWS_SOURCES):
            with source_cols[i % 2]:
                st.markdown(f"**{source_label}**")
                items = news_by_source.get(source_label)
                if items is None:
                    st.caption("現在情報を取得できません")
                elif not items:
                    st.caption("情報が見つかりませんでした")
                else:
                    for item in items:
                        date_prefix = f"{item['date']}　" if item["date"] else ""
                        st.markdown(f"- {date_prefix}[{item['title']}]({item['link']})")
    st.markdown(
        """
        <style>
          .st-key-ec_industry_news_row div[data-testid="stHorizontalBlock"] {
            flex-wrap: wrap !important; gap: 16px 24px !important;
          }
          .st-key-ec_industry_news_row div[data-testid="stColumn"] {
            flex: 1 1 45% !important; min-width: 240px !important;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def get_secret(name: str) -> str | None:
    """st.secretsが未設定（ローカル実行など）でもエラーにならないよう安全に読む。"""
    try:
        return st.secrets.get(name)
    except Exception:
        return None


VIEWER_SESSION_TIMEOUT = timedelta(hours=12)

VIEWER_PASSWORD = get_secret("viewer_password")

if st.session_state.get("viewer_unlocked"):
    login_time = st.session_state.get("viewer_login_time")
    if login_time is None or datetime.now() - login_time > VIEWER_SESSION_TIMEOUT:
        st.session_state["viewer_unlocked"] = False
        st.session_state.pop("viewer_login_time", None)

if VIEWER_PASSWORD and not st.session_state.get("viewer_unlocked"):

    st.markdown(
        """
        <style>
        [data-testid="stAppViewContainer"] {
            background: radial-gradient(circle at 50% 0%, #2f8dff 0%, #0d5fdb 45%, #052a6e 100%);
        }
        [data-testid="stHeader"] { background: transparent; }
        [data-testid="stToolbar"] { visibility: hidden; }
        [data-testid="stSidebarCollapsedControl"] { display: none; }
        .st-key-password_gate_card {
            max-width: 480px;
            margin: 6vh auto 0 auto;
            background: linear-gradient(180deg, #ffffff 0%, #e8f1ff 100%);
            border-radius: 22px;
            padding: 8px 32px 32px 32px;
            box-shadow: 0 25px 70px rgba(0,0,0,0.5), 0 0 0 3px #d4af37;
            text-align: center;
        }
        .password-gate-logo { width: 380px; max-width: 92%; margin-top: 6px; }
        @media (min-width: 641px) {
            /* PCのみ: スクロール無しで収まるよう、ロゴを左・案内文とログイン欄を右に
               並べる横長レイアウトにする（ロゴは右側の内容と縦位置を揃えて中央に来る） */
            .block-container {
                display: flex !important; flex-direction: column !important;
                justify-content: center !important; min-height: 96vh !important;
                padding-top: 2rem !important; padding-bottom: 2rem !important;
            }
            .st-key-password_gate_card {
                max-width: 920px;
                margin: 0 auto;
                display: flex !important;
                flex-direction: row !important;
                align-items: center;
                column-gap: 40px;
                padding: 36px 44px;
            }
            .st-key-password_gate_card > div:has(.st-key-password_gate_logo) {
                flex: 0 0 300px !important; width: 300px !important;
            }
            .st-key-password_gate_card > div:has(.st-key-password_gate_content) {
                flex: 1 1 auto !important; width: auto !important; min-width: 0 !important;
            }
            .password-gate-logo { width: 100%; max-width: 100%; margin-top: 0; }
        }
        .password-gate-title {
            font-size: 1.6rem; font-weight: 800; color: #0d47a1; margin-top: 4px;
            letter-spacing: 0.02em; text-align: center;
        }
        .password-gate-sub {
            font-size: 0.92rem; color: #777; margin-top: 6px; margin-bottom: 18px;
            text-align: center;
        }
        .password-gate-daytip {
            font-size: 0.8rem; color: #0d47a1; background: rgba(13,71,161,0.06);
            border-radius: 999px; padding: 6px 16px; margin: 0 auto 16px auto;
            text-align: center; width: fit-content; max-width: 100%;
        }
        .password-gate-notice {
            text-align: left; background: rgba(13,71,161,0.07);
            border: 1px solid rgba(13,71,161,0.28); border-radius: 12px;
            padding: 16px 18px; margin: 0 0 22px 0;
            font-size: 0.76rem; line-height: 1.7; color: #123a66;
        }
        .password-gate-notice-title { font-weight: 800; font-size: 0.84rem; color: #0d47a1; margin-bottom: 8px; }
        .password-gate-notice ul { margin: 0; padding-left: 1.1em; }
        .password-gate-notice li { margin-bottom: 6px; }
        .password-gate-notice li:last-child { margin-bottom: 0; }
        @media (min-width: 641px) {
            /* PCのみ: 案内文の枠が縦長にならないよう、注意事項を2列で表示する */
            .password-gate-notice ul {
                display: grid; grid-template-columns: 1fr 1fr; gap: 2px 22px;
            }
            .password-gate-notice li { margin-bottom: 8px; font-size: 0.72rem; }
        }
        .st-key-password_gate_card div[data-testid="stTextInput"] input {
            border-radius: 10px !important; border: 2px solid #d4af37 !important;
            padding: 10px 14px !important; font-size: 1rem !important;
            text-align: center; background: #ffffff !important; color: #1a1a1a !important;
        }
        .st-key-password_gate_card div[data-testid="stTextInput"] input::placeholder {
            color: #999999 !important;
        }
        .st-key-password_gate_card div[data-testid="stTextInput"] input:focus {
            border-color: #2f8dff !important;
            box-shadow: 0 0 0 3px rgba(47,141,255,0.28) !important;
        }
        .st-key-password_gate_card div[data-testid="stFormSubmitButton"] button {
            background: linear-gradient(90deg, #0d47a1, #1565c0) !important;
            color: #ffffff !important; border: none !important; font-weight: 700 !important;
            border-radius: 10px !important; padding: 10px 0 !important; margin-top: 12px !important;
            font-size: 1rem !important;
        }
        .st-key-password_gate_card div[data-testid="stFormSubmitButton"] button:hover {
            filter: brightness(1.1);
            color: #ffffff !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.container(key="password_gate_card"):
        with st.container(key="password_gate_logo"):
            st.markdown(
                f'<img class="password-gate-logo" src="data:image/png;base64,{LOGO_B64}">',
                unsafe_allow_html=True,
            )
        with st.container(key="password_gate_content"):
            today = today_jst()
            weekday_ja = ["月", "火", "水", "木", "金", "土", "日"][today.weekday()]
            today_label = f"{today.year}年{today.month}月{today.day}日（{weekday_ja}）"
            today_fact = day_facts.get_day_fact(today)
            daytip_text = f"📅 {today_label}　本日は「{today_fact}」です" if today_fact else f"📅 {today_label}"
            st.markdown(
                f"""
                <div class="password-gate-title">売上ダッシュボード</div>
                <div class="password-gate-sub">閲覧にはパスワードが必要です</div>
                <div class="password-gate-daytip">{daytip_text}</div>
                <div class="password-gate-notice">
                  <div class="password-gate-notice-title">パスワードの取り扱いについて</div>
                  <ul>
                    <li>本パスワードは毎月月初に更新されます。新しいパスワードは、その都度メールにてご案内いたします。</li>
                    <li>日々の売上をご確認いただくことは、経営感覚を養い、店舗運営の質を高める大切な習慣です。毎日のご確認が、店舗と皆様ご自身の成長につながります。</li>
                    <li>本ページで扱う情報は、当社を代表する役職者・店長の皆様にのみ共有しているものです。重要な情報である事をご理解のうえ、責任を持って閲覧・管理をお願いいたします。</li>
                    <li>セキュリティのため、ログインから12時間が経過すると自動的にログアウトされます。再度ご覧になる際は、お手数ですがパスワードの再入力をお願いいたします。</li>
                  </ul>
                </div>
                """,
                unsafe_allow_html=True,
            )
            with st.form(key="password_gate_form", clear_on_submit=False):
                entered_viewer_password = st.text_input(
                    "パスワード",
                    type="default",
                    key="viewer_password_input",
                    label_visibility="collapsed",
                    placeholder="パスワードを入力",
                )
                submitted = st.form_submit_button("ログイン", use_container_width=True)
            if submitted:
                if entered_viewer_password == VIEWER_PASSWORD:
                    st.session_state["viewer_unlocked"] = True
                    st.session_state["viewer_login_time"] = datetime.now()
                    st.rerun()
                else:
                    st.error("パスワードが違います。")
    st.stop()


render_scroll_top_button()

st.title("売上ダッシュボード")
st.caption("決まったフォルダに置かれた日次売上Excelを自動集計するプロトタイプです。")

if "as_of" not in st.session_state:
    st.session_state["as_of"] = today_jst() - timedelta(days=1)
if "selected_stores" not in st.session_state:
    st.session_state["selected_stores"] = []


def _sync_as_of_from_sidebar() -> None:
    st.session_state["as_of_popover"] = st.session_state["as_of"]


def _sync_as_of_from_popover() -> None:
    st.session_state["as_of"] = st.session_state["as_of_popover"]


def _sync_stores_from_sidebar() -> None:
    st.session_state["stores_popover"] = st.session_state["selected_stores"]


def _sync_stores_from_popover() -> None:
    st.session_state["selected_stores"] = st.session_state["stores_popover"]


with st.sidebar:
    st.header("設定")
    data_dir_input = st.text_input("Excelフォルダ", value=str(DEFAULT_DATA_DIR))
    if st.button("再読み込み", use_container_width=True):
        st.cache_data.clear()

    as_of = st.date_input(
        "基準日（本日扱いにする日付）", key="as_of", on_change=_sync_as_of_from_sidebar
    )

data_dir = Path(data_dir_input)

ADMIN_PASSWORD = get_secret("admin_password")
GITHUB_TOKEN = get_secret("github_token")
GITHUB_REPO = get_secret("github_repo")
GITHUB_BRANCH = get_secret("github_branch")

with st.sidebar:
    st.divider()
    with st.expander("📤 データ登録（Excelアップロード）"):
        upload_unlocked = True
        if ADMIN_PASSWORD:
            entered_password = st.text_input("パスワード", type="password", key="admin_password_input")
            upload_unlocked = entered_password == ADMIN_PASSWORD
            if entered_password and not upload_unlocked:
                st.error("パスワードが違います。")

        if upload_unlocked:
            uploaded_files = st.file_uploader(
                "売上Excelを選択してください（複数選択可）",
                type=["xlsx"],
                accept_multiple_files=True,
                key="sales_file_uploader",
            )
            if uploaded_files and st.button("この内容を登録する", use_container_width=True):
                data_dir.mkdir(parents=True, exist_ok=True)
                for uploaded_file in uploaded_files:
                    content = uploaded_file.getvalue()
                    (data_dir / uploaded_file.name).write_bytes(content)

                    if GITHUB_TOKEN and GITHUB_REPO and GITHUB_BRANCH:
                        sync_result = gh.upload_file_to_github(
                            repo=GITHUB_REPO,
                            branch=GITHUB_BRANCH,
                            token=GITHUB_TOKEN,
                            path_in_repo=f"dashboard/data/incoming/{uploaded_file.name}",
                            content_bytes=content,
                            commit_message=f"売上データ追加: {uploaded_file.name}",
                        )
                        if sync_result.ok:
                            st.success(f"{uploaded_file.name}: 登録しました（GitHubにも保存済み）")
                        else:
                            st.warning(
                                f"{uploaded_file.name}: 画面には反映しましたが、GitHubへの保存に失敗しました。"
                                f"次回の再起動で消える可能性があります（{sync_result.message}）"
                            )
                    else:
                        st.success(f"{uploaded_file.name}: 登録しました")

                st.cache_data.clear()
                st.rerun()


@st.cache_data(show_spinner="Excelファイルを読み込み中...")
def _load(folder_str: str) -> dl.LoadResult:
    return dl.load_all_records(Path(folder_str))


if not data_dir.exists():
    st.error(f"フォルダが見つかりません: {data_dir}")
    st.stop()

result = _load(str(data_dir))
records = result.records

if result.errors:
    with st.expander(f"⚠️ 読み込めなかったファイルが {len(result.errors)} 件あります", expanded=False):
        for err in result.errors:
            st.write(f"- {err}")

if records.empty:
    st.info(
        "Excelファイルがまだありません。`dashboard/data/incoming/` に各店舗の日次売上Excel"
        "（日付・店舗名・売上金額の列を持つファイル）を置いてください。"
        "テスト用のサンプルデータは `scripts/generate_sample_data.py` で生成できます。"
    )
    st.stop()

records, external_records = dl.split_external_sales(records)

all_stores = order_stores(records["store"].unique().tolist())
with st.sidebar:
    selected_stores = st.multiselect(
        "店舗（未選択なら全店舗）",
        all_stores,
        key="selected_stores",
        on_change=_sync_stores_from_sidebar,
    )

filtered = dl.filter_stores(records, selected_stores)
colors = store_color_map(all_stores)

available_months = sorted(
    {(d.year, d.month) for d in records["date"]},
    reverse=True,
)
# 売上テンプレートに来月以降の分の行が既に入っている場合に備え、デフォルト選択は
# データ上の最新月ではなく「今日時点で迎えている月のうち一番新しいもの」にする。
today_ym = (today_jst().year, today_jst().month)
past_or_current_months = [m for m in available_months if m <= today_ym]
default_month = past_or_current_months[0] if past_or_current_months else (
    available_months[0] if available_months else None
)
default_month_idx = (
    available_months.index(default_month) if default_month in available_months else 0
)
with st.sidebar:
    month_labels = [f"{y}年{m}月" for y, m in available_months]
    month_idx = st.selectbox(
        "対象月",
        range(len(available_months)),
        index=default_month_idx,
        format_func=lambda i: month_labels[i],
    )
target_year, target_month = available_months[month_idx]

progress = dl.month_progress(filtered, target_year, target_month, as_of)
yoy_today = dl.yoy_same_day(filtered, as_of)

header_title_col, header_badges_col = st.columns([1, 2])
with header_title_col:
    st.subheader("売上サマリー")
with header_badges_col:
    render_header_badges(store_display_label(selected_stores, all_stores), as_of)

edit_row = st.container(key="edit_button_row")
with edit_row:
    _, edit_spacer_col, edit_button_col = st.columns([2, 1, 1])
with edit_button_col:
    with st.popover("🔧 対象日・表示店舗を変更", use_container_width=True):
        if "as_of_popover" not in st.session_state:
            st.session_state["as_of_popover"] = st.session_state["as_of"]
        if "stores_popover" not in st.session_state:
            st.session_state["stores_popover"] = st.session_state["selected_stores"]
        st.date_input(
            "基準日（本日扱いにする日付）", key="as_of_popover", on_change=_sync_as_of_from_popover
        )
        st.multiselect(
            "店舗（未選択なら全店舗）",
            all_stores,
            key="stores_popover",
            on_change=_sync_stores_from_popover,
        )

forecast = progress["forecast_yoy_adjusted"] or progress["forecast_run_rate"]
forecast_note = "前年同月比ベース" if progress["forecast_yoy_adjusted"] else "当月ペース（単純日次平均）ベース"

last_year_total = yoy_today["last_year_total"]
today_diff = (
    yoy_today["today_total"] - last_year_total if last_year_total is not None else None
)

render_kpi_grid([
    dict(
        label="本日の売上合計",
        value=format_yen_compact(yoy_today["today_total"]),
        bg_color=KPI_BLUE,
        symbol=symbol_for_ratio(yoy_today["pct_change"]),
        caption=f"前年差 {format_delta(today_diff, None) or '—'}",
        tooltip=format_yen(yoy_today["today_total"]),
    ),
    dict(
        label="前年同日比",
        value=format_pct(yoy_today["pct_change"]),
        bg_color=KPI_GREEN,
        caption="&nbsp;",
    ),
    dict(
        label=f"当月累計（{progress['elapsed_days']}/{progress['total_days']}日）",
        value=format_yen_compact(progress["mtd_total"]),
        bg_color="rgb(196, 8, 24)",
        symbol=symbol_for_ratio(progress["mtd_yoy_pct"]),
        caption=f"前年比 {format_pct(progress['mtd_yoy_pct'])}",
        tooltip=format_yen(progress["mtd_total"]),
    ),
    dict(
        label="月末着地予測",
        value=format_yen_compact(forecast),
        bg_color="rgb(48, 47, 47)",
        symbol=symbol_for_ratio(progress["forecast_yoy_pct"]),
        caption=f"前年比 {format_pct(progress['forecast_yoy_pct'])}",
        tooltip=f"{forecast_note} / {format_yen(forecast)}",
    ),
])

st.divider()

left, right = st.columns([2, 1])

with left:
    st.markdown("#### グループ日別売上（今年 vs 前年同月）")
    series = dl.yoy_daily_series(filtered, target_year, target_month)
    fig = go.Figure()
    fig.add_bar(
        x=series["day"], y=series["this_year"],
        name=f"{target_year}年{target_month}月", marker_color=KPI_BLUE,
    )
    fig.add_bar(
        x=series["day"], y=series["last_year"],
        name=f"{target_year - 1}年{target_month}月", marker_color=COMPARISON_COLOR,
    )
    fig.update_layout(
        barmode="group",
        xaxis_title="日",
        yaxis_title="売上金額（円）",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=10, r=10, t=30, b=10),
        height=380,
    )
    with st.container(key="daily_chart_pc"):
        st.plotly_chart(apply_pc_chart_style(fig), use_container_width=True, config={"displayModeBar": False})
    with st.container(key="daily_chart_mobile"):
        st.plotly_chart(to_mobile_chart(fig), use_container_width=True, config={"displayModeBar": False})

with right:
    st.markdown("#### 月進捗")
    total_days = progress["total_days"]
    elapsed = progress["elapsed_days"]
    render_progress_bar(elapsed, total_days)
    st.write(f"当月累計: **{format_yen(progress['mtd_total'])}**")
    st.write(f"1日あたり平均: {format_yen(progress['avg_daily'])}")
    if progress["last_year_full_total"]:
        st.write(f"前年同月 実績（フル月）: {format_yen(progress['last_year_full_total'])}")
    st.write(f"月末着地予測: **{format_yen(forecast)}**（{forecast_note}）")

st.divider()

with st.container(key="daily_store_heading"):
    st.markdown("#### 店舗別・日別売上（単位/万）")
st.caption(f"対象日: {as_of}")
daily_store = reorder_by_store(dl.daily_store_snapshot(filtered, as_of), all_stores)
daily_store_ranking = dl.store_ranking(filtered, target_year, target_month, as_of).set_index("store")
daily_store_mtd_yoy = daily_store_ranking["yoy_pct"]

with st.container(key="daily_store_cards"):
    daily_store_cards_df = daily_store.copy()
    daily_store_cards_df["mtd_sales"] = daily_store_cards_df["store"].map(daily_store_ranking["mtd_sales"])
    daily_store_cards_df["last_year_mtd_sales"] = daily_store_cards_df["store"].map(
        daily_store_ranking["last_year_mtd_sales"]
    )
    daily_store_cards_df["mtd_yoy_pct"] = daily_store_cards_df["store"].map(daily_store_ranking["yoy_pct"])
    render_daily_store_cards(daily_store_cards_df)

fig_daily_store = go.Figure()
fig_daily_store.add_bar(
    x=daily_store["store"], y=daily_store["sales"],
    name="当日売上", marker_color=KPI_BLUE,
)
fig_daily_store.add_bar(
    x=daily_store["store"], y=daily_store["last_year_sales"],
    name="前年同日売上", marker_color=COMPARISON_COLOR,
)
fig_daily_store.update_layout(
    barmode="group",
    xaxis_title="店舗",
    yaxis_title="売上金額（円）",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    margin=dict(l=10, r=10, t=30, b=10),
    height=340,
)
with st.container(key="daily_store_chart_pc"):
    st.plotly_chart(apply_pc_chart_style(fig_daily_store), use_container_width=True, config={"displayModeBar": False})
with st.container(key="daily_store_chart_mobile"):
    st.plotly_chart(to_mobile_chart(fig_daily_store), use_container_width=True, config={"displayModeBar": False})

daily_store_display = pd.DataFrame(
    {
        "店舗": daily_store["store"],
        "当日売上": daily_store["sales"].map(format_yen),
        "前年同日売上": daily_store["last_year_sales"].map(format_yen),
        "前年同日比": daily_store["yoy_pct"].map(format_pct),
        "当月累計前年比": daily_store["store"].map(daily_store_mtd_yoy).map(format_pct),
    }
)
with st.container(key="daily_store_table_pc"):
    render_pc_table(daily_store_display, daily_store["yoy_pct"] <= 99.9)
with st.container(key="daily_store_table_mobile"):
    render_compact_table(daily_store_display[["店舗", "当日売上", "前年同日比"]])

render_section_break()

with st.container(key="ranking_heading"):
    st.markdown("#### 店舗別・月別売上")
ranking = reorder_by_store(dl.store_ranking(filtered, target_year, target_month, as_of), all_stores)

fig_ranking = go.Figure()
fig_ranking.add_bar(
    x=ranking["store"], y=ranking["mtd_sales"],
    name="当月累計売上", marker_color=ACCENT_COLOR,
)
fig_ranking.add_bar(
    x=ranking["store"], y=ranking["last_year_mtd_sales"],
    name="前年同期間売上", marker_color=COMPARISON_COLOR,
)
fig_ranking.add_scatter(
    x=ranking["store"], y=ranking["last_year_full_sales"],
    name="前年売上計", mode="lines+markers", line=dict(color=KPI_GREEN),
)
fig_ranking.update_layout(
    barmode="group",
    xaxis_title="店舗",
    yaxis_title="売上金額（円）",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    margin=dict(l=10, r=10, t=30, b=10),
    height=340,
)
with st.container(key="ranking_chart_pc"):
    st.plotly_chart(apply_pc_chart_style(fig_ranking), use_container_width=True, config={"displayModeBar": False})
with st.container(key="ranking_chart_mobile"):
    st.plotly_chart(to_mobile_chart(fig_ranking), use_container_width=True, config={"displayModeBar": False})

ranking_display = pd.DataFrame(
    {
        "店舗": ranking["store"],
        "当月累計売上": ranking["mtd_sales"].map(format_yen),
        "前年同期間売上": ranking["last_year_mtd_sales"].map(format_yen),
        "前年比": ranking["yoy_pct"].map(format_pct),
        "前年売上計": ranking["last_year_full_sales"].map(format_yen),
    }
)
with st.container(key="ranking_table_pc"):
    render_pc_table(ranking_display, ranking["yoy_pct"] <= 99.9)
with st.container(key="ranking_table_mobile"):
    render_compact_table(ranking_display, sticky_first_col=True)

st.divider()

if "monthly_yoy_offset" not in st.session_state:
    st.session_state["monthly_yoy_offset"] = 0
if "monthly_yoy_mode" not in st.session_state:
    st.session_state["monthly_yoy_mode"] = "month"
monthly_yoy_offset = st.session_state["monthly_yoy_offset"]
monthly_yoy_mode = st.session_state["monthly_yoy_mode"]
monthly_yoy_is_month = monthly_yoy_mode == "month"

st.markdown(f"#### グループ{'月別' if monthly_yoy_is_month else '年別'}前年比（12{'ヶ月' if monthly_yoy_is_month else '年'}表示）")

with st.container(key="monthly_mode_toggle_row"):
    monthly_mode_col1, monthly_mode_col2 = st.columns(2)
    with monthly_mode_col1:
        if st.button("月", key="monthly_mode_month_btn", use_container_width=True):
            st.session_state["monthly_yoy_mode"] = "month"
            st.session_state["monthly_yoy_offset"] = 0
            st.rerun()
    with monthly_mode_col2:
        if st.button("年", key="monthly_mode_year_btn", use_container_width=True):
            st.session_state["monthly_yoy_mode"] = "year"
            st.session_state["monthly_yoy_offset"] = 0
            st.rerun()
st.markdown(
    f"""
    <style>
      .st-key-monthly_mode_toggle_row div[data-testid="stHorizontalBlock"] {{
        flex-wrap:nowrap !important; gap:10px !important;
      }}
      .st-key-monthly_mode_toggle_row div[data-testid="stColumn"] {{
        flex:1 1 0 !important; width:auto !important; min-width:0 !important;
      }}
      @media (min-width: 641px) {{
        .st-key-monthly_mode_toggle_row div[data-testid="stHorizontalBlock"] {{
          max-width: 285px !important; margin-left: auto !important; margin-right: 0 !important;
        }}
        .st-key-monthly_mode_month_btn button, .st-key-monthly_mode_year_btn button {{
          min-height: 64px !important;
        }}
      }}
      .st-key-monthly_mode_month_btn button, .st-key-monthly_mode_year_btn button {{
        color:#ffffff !important; border:none !important; font-weight:700 !important;
        opacity:0.45; transition:opacity 0.2s ease, transform 0.2s ease;
      }}
      .st-key-monthly_mode_month_btn button {{ background:{KPI_GREEN} !important; }}
      .st-key-monthly_mode_year_btn button {{ background:{KPI_BLUE} !important; }}
      .st-key-monthly_mode_month_btn button:hover, .st-key-monthly_mode_year_btn button:hover {{
        color:#ffffff !important;
      }}
      .st-key-monthly_mode_{'month' if monthly_yoy_is_month else 'year'}_btn button {{
        opacity:1; transform:scale(1.03);
      }}
    </style>
    """,
    unsafe_allow_html=True,
)

if monthly_yoy_is_month:
    monthly_yoy = dl.monthly_yoy_series(filtered, as_of, months=12, end_offset=monthly_yoy_offset)
else:
    monthly_yoy = dl.yearly_yoy_series(filtered, as_of, years=12, end_offset=monthly_yoy_offset)

fig3 = go.Figure()
if monthly_yoy_is_month:
    fig3.add_bar(
        x=monthly_yoy["label"], y=monthly_yoy["this_year"],
        name="当年", marker_color=KPI_GREEN,
    )
    fig3.add_bar(
        x=monthly_yoy["label"], y=monthly_yoy["last_year"],
        name="前年同月", marker_color=COMPARISON_COLOR,
    )
else:
    fig3.add_bar(
        x=monthly_yoy["label"], y=monthly_yoy["this_year"],
        name="年間売上",
        marker_color=[
            KPI_BLUE if is_partial else COMPARISON_COLOR
            for is_partial in monthly_yoy["is_partial"]
        ],
    )
fig3.update_layout(
    barmode="group",
    xaxis_title="月" if monthly_yoy_is_month else "年",
    yaxis_title="売上金額（円）",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    margin=dict(l=10, r=10, t=30, b=10),
    height=380,
)
with st.container(key="monthly_nav_row"):
    monthly_prev_col, monthly_next_col = st.columns(2)
    with monthly_prev_col:
        if st.button("◀", key="monthly_nav_prev_btn", use_container_width=True):
            st.session_state["monthly_yoy_offset"] = monthly_yoy_offset + 12
            st.rerun()
    with monthly_next_col:
        if st.button(
            "▶",
            key="monthly_nav_next_btn",
            use_container_width=True,
            disabled=(monthly_yoy_offset <= 0),
        ):
            st.session_state["monthly_yoy_offset"] = max(0, monthly_yoy_offset - 12)
            st.rerun()
st.markdown(
    """
    <style>
      .st-key-monthly_nav_row { margin-bottom: -12px; }
      .st-key-monthly_nav_row div[data-testid="stHorizontalBlock"] {
        flex-wrap:nowrap !important; gap:8px !important; justify-content:flex-end !important;
      }
      .st-key-monthly_nav_row div[data-testid="stColumn"] {
        flex:0 0 auto !important; width:auto !important; min-width:0 !important;
      }
      .st-key-monthly_nav_prev_btn button, .st-key-monthly_nav_next_btn button {
        width:40px !important; height:40px !important; border-radius:50% !important;
        padding:0 !important; font-size:1.1rem !important; line-height:1 !important;
        background:#eef0f3 !important; color:#333 !important; border:none !important;
        transition:background 0.15s ease !important;
      }
      .st-key-monthly_nav_prev_btn button:hover, .st-key-monthly_nav_next_btn button:hover {
        background:#c9ccd1 !important; color:#333 !important;
      }
      .st-key-monthly_nav_prev_btn button:disabled, .st-key-monthly_nav_next_btn button:disabled {
        opacity:0.35 !important; cursor:not-allowed !important;
      }
    </style>
    """,
    unsafe_allow_html=True,
)
with st.container(key="monthly_chart_pc"):
    st.plotly_chart(apply_pc_chart_style(fig3), use_container_width=True, config={"displayModeBar": False})
with st.container(key="monthly_chart_mobile"):
    st.plotly_chart(to_mobile_chart(fig3), use_container_width=True, config={"displayModeBar": False})

partial_label = monthly_yoy.loc[monthly_yoy["is_partial"], "label"]
if not partial_label.empty:
    if monthly_yoy_is_month:
        st.caption(
            f"※ {partial_label.iloc[0]}は基準日（{as_of}）までの実績同士（当年・前年とも月初から同じ日数分）で比較しています。"
        )
    else:
        st.caption(
            f"※ {partial_label.iloc[0]}は基準日（{as_of}）までの実績同士（当年・前年とも年始から同じ日数分）で比較しています。"
        )

if monthly_yoy_is_month:
    st.caption(
        "下の表は、データがある期間をすべて含みます（グラフの表示期間とは連動しません）。"
        "13ヶ月以上ある場合は、表内をスクロールしてご覧ください。"
    )
    total_months_with_data = len({(d.year, d.month) for d in filtered["date"]})
    monthly_yoy_full = dl.monthly_yoy_series(filtered, as_of, months=max(total_months_with_data, 1))
    monthly_yoy_full_desc = monthly_yoy_full.sort_values(["year", "month"], ascending=False)
    monthly_display = pd.DataFrame(
        {
            "月": monthly_yoy_full_desc["label"],
            "当年売上": monthly_yoy_full_desc["this_year"].map(format_yen),
            "前年同月売上": monthly_yoy_full_desc["last_year"].map(format_yen),
            "前年比": monthly_yoy_full_desc["yoy_pct"].map(format_pct),
        }
    )
else:
    st.caption(
        "下の表は、データがある期間をすべて含みます（グラフの表示期間とは連動しません）。"
        "13年以上ある場合は、表内をスクロールしてご覧ください。"
    )
    total_years_with_data = len({d.year for d in filtered["date"]})
    monthly_yoy_full = dl.yearly_yoy_series(filtered, as_of, years=max(total_years_with_data, 1))
    monthly_yoy_full_desc = monthly_yoy_full.sort_values(["year"], ascending=False)
    monthly_display = pd.DataFrame(
        {
            "年": monthly_yoy_full_desc["label"],
            "当年売上": monthly_yoy_full_desc["this_year"].map(format_yen),
            "前年売上": monthly_yoy_full_desc["last_year"].map(format_yen),
            "前年比": monthly_yoy_full_desc["yoy_pct"].map(format_pct),
        }
    )
monthly_table_visible_rows = min(len(monthly_display), 12)
st.dataframe(
    monthly_display,
    use_container_width=True,
    hide_index=True,
    height=35 * (monthly_table_visible_rows + 1) + 3,
)

st.divider()

st.markdown("#### 年間前年比")
year_yoy = dl.calendar_year_yoy(filtered, as_of)
ycol1, ycol2, ycol3, ycol4 = st.columns(4)
ycol1.metric(
    f"{year_yoy['year']}年 累計（1/1〜{as_of.strftime('%m/%d')}）",
    format_yen_compact(year_yoy["this_year_ytd"]),
    help=format_yen(year_yoy["this_year_ytd"]),
)
ycol2.metric(
    f"{year_yoy['year'] - 1}年 同期間累計",
    format_yen_compact(year_yoy["last_year_ytd"]),
    help=format_yen(year_yoy["last_year_ytd"]),
)
ycol3.metric("前年比", format_pct(year_yoy["yoy_pct"]))
ycol4.metric(
    f"{year_yoy['year'] - 1}年 実績（暦年フル）",
    format_yen_compact(year_yoy["last_year_full_total"]),
    help=f"参考: 前年1年間（1月〜12月）の実績合計 / 正確な金額: {format_yen(year_yoy['last_year_full_total'])}",
)

st.divider()

st.markdown("#### 記録")
daily_recs = dl.daily_record(filtered, top_n=3)
monthly_recs = dl.monthly_group_record(filtered, top_n=3)
st.markdown("**日商ギネス**")
render_record_metrics(
    daily_recs,
    label_fn=lambda i, r: f"{i + 1}位（{r['date']} / {r['store']}）",
)
st.markdown("**月商ギネス**（グループ全体・外販除く）")
render_record_metrics(
    monthly_recs,
    label_fn=lambda i, r: f"{i + 1}位（{r['year']}年{r['month']}月）",
)

st.divider()

st.markdown("#### 外販売上")
st.caption("店舗名が「外販」の実績のみを集計。店舗売上とは合算・比較しません（スポット売上のため）。")
external_yoy_today = dl.yoy_same_day(external_records, as_of)
external_progress = dl.month_progress(external_records, target_year, target_month, as_of)
ecol1, ecol2, ecol3 = st.columns(3)
ecol1.metric(
    "本日の売上合計",
    format_yen_compact(external_yoy_today["today_total"]),
    help=format_yen(external_yoy_today["today_total"]),
)
ecol2.metric(
    "前年同日比",
    format_pct(external_yoy_today["pct_change"]),
    help=f"前年同日（{external_yoy_today['last_year_date']}）: {format_yen(external_yoy_today['last_year_total'])}",
)
external_mtd_diff = (
    external_progress["mtd_total"] - external_progress["last_year_mtd_total"]
    if external_progress["last_year_mtd_total"] is not None
    else None
)
ecol3.metric(
    f"当月累計（{external_progress['elapsed_days']}/{external_progress['total_days']}日）",
    format_yen_compact(external_progress["mtd_total"]),
    delta=format_delta(external_mtd_diff, external_progress["mtd_yoy_pct"]),
    help=(
        f"正確な金額: {format_yen(external_progress['mtd_total'])} "
        f"/ 前年同期間: {format_yen(external_progress['last_year_mtd_total'])}"
    ),
)

GOOGLE_CALENDAR_SRC = get_secret("google_calendar_src")
if GOOGLE_CALENDAR_SRC:
    st.divider()
    render_calendar_section(GOOGLE_CALENDAR_SRC)

st.divider()
render_beverage_news_section()

st.divider()
render_local_news_section()

st.divider()
render_liquor_retail_news_section()

st.divider()
render_ec_industry_news_section()
