"""複数店舗 売上ダッシュボード（ローカル・プロトタイプ版）

指定フォルダに溜まった日次売上Excelを読み込み、
日別・前年同日比・月進捗・月末着地予測を可視化する。
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import data_loader as dl  # noqa: E402

# 店舗識別用の固定カラー順（10店舗分）。店舗が増えたら末尾に追加する。
STORE_COLORS = [
    "#4E79A7", "#F28E2B", "#59A14F", "#E15759", "#B07AA1",
    "#76B7B2", "#EDC948", "#FF9DA7", "#9C755F", "#BAB0AC",
]
PRIMARY_COLOR = "#4E79A7"
COMPARISON_COLOR = "#BAB0AC"

DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data" / "incoming"

st.set_page_config(page_title="多店舗売上ダッシュボード", layout="wide")

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
    }
    </style>
    """,
    unsafe_allow_html=True,
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
    if value is None or pd.isna(value):
        return "—"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.1f}%"


def store_color_map(stores: list[str]) -> dict[str, str]:
    return {store: STORE_COLORS[i % len(STORE_COLORS)] for i, store in enumerate(sorted(stores))}


st.title("多店舗売上ダッシュボード")
st.caption("決まったフォルダに置かれた日次売上Excelを自動集計するプロトタイプです。")

with st.sidebar:
    st.header("設定")
    data_dir_input = st.text_input("Excelフォルダ", value=str(DEFAULT_DATA_DIR))
    if st.button("再読み込み", use_container_width=True):
        st.cache_data.clear()

    as_of = st.date_input("基準日（本日扱いにする日付）", value=date.today())

data_dir = Path(data_dir_input)


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

all_stores = sorted(records["store"].unique().tolist())
with st.sidebar:
    selected_stores = st.multiselect("店舗（未選択なら全店舗）", all_stores, default=[])

filtered = dl.filter_stores(records, selected_stores)
colors = store_color_map(all_stores)

available_months = sorted(
    {(d.year, d.month) for d in records["date"]},
    reverse=True,
)
with st.sidebar:
    month_labels = [f"{y}年{m}月" for y, m in available_months]
    month_idx = st.selectbox("対象月", range(len(available_months)), format_func=lambda i: month_labels[i])
target_year, target_month = available_months[month_idx]

progress = dl.month_progress(filtered, target_year, target_month, as_of)
yoy_today = dl.yoy_same_day(filtered, as_of)

st.subheader(f"{target_year}年{target_month}月 サマリー（基準日: {as_of}）")

col1, col2, col3, col4 = st.columns(4)
col1.metric(
    "本日の売上合計",
    format_yen_compact(yoy_today["today_total"]),
    help=format_yen(yoy_today["today_total"]),
)
col2.metric(
    "前年同日比",
    format_pct(yoy_today["pct_change"]),
    help=f"前年同日（{yoy_today['last_year_date']}）: {format_yen(yoy_today['last_year_total'])}",
)
col3.metric(
    f"当月累計（{progress['elapsed_days']}/{progress['total_days']}日）",
    format_yen_compact(progress["mtd_total"]),
    help=format_yen(progress["mtd_total"]),
)
forecast = progress["forecast_yoy_adjusted"] or progress["forecast_run_rate"]
forecast_note = "前年同月比ベース" if progress["forecast_yoy_adjusted"] else "当月ペース（単純日次平均）ベース"
col4.metric(
    "月末着地予測",
    format_yen_compact(forecast),
    help=f"{forecast_note} / 正確な金額: {format_yen(forecast)}",
)

st.divider()

left, right = st.columns([2, 1])

with left:
    st.markdown("#### 日別売上（今年 vs 前年同月）")
    series = dl.yoy_daily_series(filtered, target_year, target_month)
    fig = go.Figure()
    fig.add_bar(
        x=series["day"], y=series["this_year"],
        name=f"{target_year}年{target_month}月", marker_color=PRIMARY_COLOR,
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
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

with right:
    st.markdown("#### 月進捗")
    total_days = progress["total_days"]
    elapsed = progress["elapsed_days"]
    st.progress(elapsed / total_days if total_days else 0, text=f"{elapsed} / {total_days} 日経過")
    st.write(f"当月累計: **{format_yen(progress['mtd_total'])}**")
    st.write(f"1日あたり平均: {format_yen(progress['avg_daily'])}")
    if progress["last_year_full_total"]:
        st.write(f"前年同月 実績（フル月）: {format_yen(progress['last_year_full_total'])}")
    st.write(f"月末着地予測: **{format_yen(forecast)}**（{forecast_note}）")

st.divider()

st.markdown("#### 年間前年比（暦年合計・1月〜基準日）")
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

st.markdown("#### 月別前年比（直近12ヶ月）")
monthly_yoy = dl.monthly_yoy_series(filtered, as_of, months=12)
fig3 = go.Figure()
fig3.add_bar(
    x=monthly_yoy["label"], y=monthly_yoy["this_year"],
    name="当年", marker_color=PRIMARY_COLOR,
)
fig3.add_bar(
    x=monthly_yoy["label"], y=monthly_yoy["last_year"],
    name="前年同月", marker_color=COMPARISON_COLOR,
)
fig3.update_layout(
    barmode="group",
    xaxis_title="月",
    yaxis_title="売上金額（円）",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    margin=dict(l=10, r=10, t=30, b=10),
    height=380,
)
st.plotly_chart(fig3, use_container_width=True, config={"displayModeBar": False})

partial_label = monthly_yoy.loc[monthly_yoy["is_partial"], "label"]
if not partial_label.empty:
    st.caption(
        f"※ {partial_label.iloc[0]}は基準日（{as_of}）までの実績同士（当年・前年とも月初から同じ日数分）で比較しています。"
    )

monthly_display = pd.DataFrame(
    {
        "月": monthly_yoy["label"],
        "当年売上": monthly_yoy["this_year"].map(format_yen),
        "前年同月売上": monthly_yoy["last_year"].map(format_yen),
        "前年比": monthly_yoy["yoy_pct"].map(format_pct),
    }
)
st.dataframe(monthly_display, use_container_width=True, hide_index=True)

st.divider()

st.markdown("#### 店舗別ランキング（当月累計・前年同期間比）")
ranking = dl.store_ranking(filtered, target_year, target_month, as_of)
ranking_display = pd.DataFrame(
    {
        "店舗": ranking["store"],
        "当月累計売上": ranking["mtd_sales"].map(format_yen),
        "前年同期間売上": ranking["last_year_mtd_sales"].map(format_yen),
        "前年比": ranking["yoy_pct"].map(format_pct),
    }
)
st.dataframe(ranking_display, use_container_width=True, hide_index=True)

st.markdown("#### 全期間 日別売上推移")
daily = dl.daily_totals(filtered)
fig2 = go.Figure()
fig2.add_scatter(x=daily["date"], y=daily["sales"], mode="lines", line=dict(color=PRIMARY_COLOR, width=2))
fig2.update_layout(
    xaxis_title="日付", yaxis_title="売上金額（円）",
    margin=dict(l=10, r=10, t=10, b=10), height=300,
)
st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})
