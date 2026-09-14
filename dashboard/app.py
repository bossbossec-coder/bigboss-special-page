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
from lib import github_sync as gh  # noqa: E402

# 店舗識別用の固定カラー順（10店舗分）。店舗が増えたら末尾に追加する。
STORE_COLORS = [
    "#4E79A7", "#F28E2B", "#59A14F", "#E15759", "#B07AA1",
    "#76B7B2", "#EDC948", "#FF9DA7", "#9C755F", "#BAB0AC",
]
PRIMARY_COLOR = "#4E79A7"
COMPARISON_COLOR = "#BAB0AC"
ACCENT_COLOR = "#F28E2B"

WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]

DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data" / "incoming"

st.set_page_config(page_title="売上ダッシュボード", layout="wide")

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


def render_target_date_badge(target_date: date) -> None:
    """右上に「対象日」を目立つバッジとして表示する。"""
    weekday = WEEKDAY_JP[target_date.weekday()]
    st.markdown(
        f"""
        <div style="display:flex; justify-content:flex-end;">
          <div style="text-align:right;">
            <div style="font-size:0.75rem; color:#8a8a8a; margin-bottom:2px;">対象日</div>
            <div style="position:relative; display:inline-block;
                        padding:6px 16px 6px 22px; border-radius:6px;
                        background:#fff; border:1px solid #e6e6e6;
                        box-shadow:0 1px 3px rgba(0,0,0,0.08);">
              <div style="position:absolute; top:0; left:0; width:0; height:0;
                          border-left:16px solid {ACCENT_COLOR};
                          border-bottom:16px solid transparent;
                          border-top-left-radius:6px;"></div>
              <span style="font-size:1.5rem; font-weight:800; color:#1a1a1a;">
                {target_date.month}.{target_date.day}
              </span>
              <span style="font-size:1.05rem; font-weight:600; color:#555;">
                [{weekday}]
              </span>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_section_break() -> None:
    """日別グループと月別グループの境目を、通常のdividerより太く目立たせる。"""
    st.markdown(
        f"""
        <hr style="border:none; height:5px; margin:28px 0 24px 0; border-radius:3px;
                   background:linear-gradient(90deg, {PRIMARY_COLOR}, {ACCENT_COLOR});">
        """,
        unsafe_allow_html=True,
    )


def get_secret(name: str) -> str | None:
    """st.secretsが未設定（ローカル実行など）でもエラーにならないよう安全に読む。"""
    try:
        return st.secrets.get(name)
    except Exception:
        return None


st.title("売上ダッシュボード")
st.caption("決まったフォルダに置かれた日次売上Excelを自動集計するプロトタイプです。")

with st.sidebar:
    st.header("設定")
    data_dir_input = st.text_input("Excelフォルダ", value=str(DEFAULT_DATA_DIR))
    if st.button("再読み込み", use_container_width=True):
        st.cache_data.clear()

    as_of = st.date_input("基準日（本日扱いにする日付）", value=date.today())

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

header_title_col, header_date_col = st.columns([3, 1])
with header_title_col:
    st.subheader("売上サマリー")
with header_date_col:
    render_target_date_badge(as_of)

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
mtd_diff = (
    progress["mtd_total"] - progress["last_year_mtd_total"]
    if progress["last_year_mtd_total"] is not None
    else None
)
col3.metric(
    f"当月累計（{progress['elapsed_days']}/{progress['total_days']}日）",
    format_yen_compact(progress["mtd_total"]),
    delta=format_delta(mtd_diff, progress["mtd_yoy_pct"]),
    help=f"正確な金額: {format_yen(progress['mtd_total'])} / 前年同期間: {format_yen(progress['last_year_mtd_total'])}",
)
forecast = progress["forecast_yoy_adjusted"] or progress["forecast_run_rate"]
forecast_note = "前年同月比ベース" if progress["forecast_yoy_adjusted"] else "当月ペース（単純日次平均）ベース"
forecast_diff = (
    forecast - progress["last_year_full_total"]
    if progress["last_year_full_total"] is not None
    else None
)
col4.metric(
    "月末着地予測",
    format_yen_compact(forecast),
    delta=format_delta(forecast_diff, progress["forecast_yoy_pct"]),
    help=(
        f"{forecast_note} / 正確な金額: {format_yen(forecast)} "
        f"/ 前年実績（フル月）: {format_yen(progress['last_year_full_total'])}"
    ),
)

st.divider()

left, right = st.columns([2, 1])

with left:
    st.markdown("#### グループ日別売上（今年 vs 前年同月）")
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

st.markdown("#### 店舗別・日別売上（前年同日比込み）")
st.caption(f"対象日: {as_of}")
daily_store = dl.daily_store_snapshot(filtered, as_of)
daily_store_mtd_yoy = dl.store_ranking(filtered, target_year, target_month, as_of).set_index("store")["yoy_pct"]
daily_store_display = pd.DataFrame(
    {
        "店舗": daily_store["store"],
        "当日売上": daily_store["sales"].map(format_yen),
        "前年同日売上": daily_store["last_year_sales"].map(format_yen),
        "前年同日比": daily_store["yoy_pct"].map(format_pct),
        "当月累計前年比": daily_store["store"].map(daily_store_mtd_yoy).map(format_pct),
    }
)
st.dataframe(daily_store_display, use_container_width=True, hide_index=True, height=350)

render_section_break()

st.markdown("#### 店舗別ランキング（当月累計・前年同期間比）")
ranking = dl.store_ranking(filtered, target_year, target_month, as_of)
ranking_display = pd.DataFrame(
    {
        "店舗": ranking["store"],
        "当月累計売上": ranking["mtd_sales"].map(format_yen),
        "前年同期間売上": ranking["last_year_mtd_sales"].map(format_yen),
        "前年比": ranking["yoy_pct"].map(format_pct),
        "前年売上計": ranking["last_year_full_sales"].map(format_yen),
    }
)
st.dataframe(ranking_display, use_container_width=True, hide_index=True)

st.divider()

st.markdown("#### グループ月別前年比（直近12ヶ月）")
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

monthly_yoy_desc = monthly_yoy.sort_values(["year", "month"], ascending=False)
monthly_display = pd.DataFrame(
    {
        "月": monthly_yoy_desc["label"],
        "当年売上": monthly_yoy_desc["this_year"].map(format_yen),
        "前年同月売上": monthly_yoy_desc["last_year"].map(format_yen),
        "前年比": monthly_yoy_desc["yoy_pct"].map(format_pct),
    }
)
st.dataframe(monthly_display, use_container_width=True, hide_index=True)

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

st.markdown("##### 記録")
daily_rec = dl.daily_record(filtered)
monthly_rec = dl.monthly_record(filtered)
rcol1, rcol2 = st.columns(2)
with rcol1:
    st.markdown("**日商ギネス**")
    if daily_rec:
        st.metric("売上高", format_yen_compact(daily_rec["sales"]), help=format_yen(daily_rec["sales"]))
        st.caption(f"達成日付: {daily_rec['date']} / 店舗名: {daily_rec['store']}")
    else:
        st.caption("データがありません")
with rcol2:
    st.markdown("**月商ギネス**")
    if monthly_rec:
        st.metric("売上高", format_yen_compact(monthly_rec["sales"]), help=format_yen(monthly_rec["sales"]))
        st.caption(f"達成日付: {monthly_rec['year']}年{monthly_rec['month']}月 / 店舗名: {monthly_rec['store']}")
    else:
        st.caption("データがありません")

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
