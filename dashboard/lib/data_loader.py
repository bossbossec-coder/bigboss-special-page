"""日次売上Excelファイルの読み込みと集計ロジック。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

# Excelファイルで必須とする列名
REQUIRED_COLUMNS = ["日付", "店舗名", "売上金額"]
OPTIONAL_COLUMNS = ["客数", "備考"]

# データが入っているシート名の候補（入力テンプレートは「売上入力」、
# サンプル生成データは「売上」という名前を使う）。見つからない場合は
# 必須列を持つ最初のシート、それも無ければ先頭シートにフォールバックする。
PREFERRED_SHEET_NAMES = ["売上入力", "売上"]

# 「店舗名」列にこの値が入っている行は、店舗の売上ではなく外販（スポット売上）として扱い、
# 店舗別の合計・比較には一切含めない。
EXTERNAL_SALES_STORE = "外販"


@dataclass
class LoadResult:
    records: pd.DataFrame  # columns: date, store, sales, customers, source_file
    errors: list[str]  # 読み込みに失敗したファイルとその理由


def _pick_sheet_name(xl: pd.ExcelFile) -> str:
    for name in PREFERRED_SHEET_NAMES:
        if name in xl.sheet_names:
            return name
    for name in xl.sheet_names:
        cols = [str(c).strip() for c in xl.parse(name, nrows=0).columns]
        if all(c in cols for c in REQUIRED_COLUMNS):
            return name
    return xl.sheet_names[0]


def _read_one_file(path: Path) -> pd.DataFrame:
    xl = pd.ExcelFile(path, engine="openpyxl")
    sheet_name = _pick_sheet_name(xl)
    df = xl.parse(sheet_name)
    df.columns = [str(c).strip() for c in df.columns]

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"必須列が見つかりません: {', '.join(missing)}")

    df = df.dropna(subset=["日付", "店舗名"], how="any")
    if df.empty:
        raise ValueError("有効なデータ行がありません")

    # 日付はExcelの日付型のほか、"2026/9/10" や "2026-9-10" のようにセルによって
    # 表記が揃っていないテキストが混在しても読めるよう、1件ずつ形式を推定する
    # （format="mixed" を指定しないと、先頭の値から推定した1つの形式を全件に
    # 適用しようとして、形式が混在する列でエラーになることがある）。
    parsed_date = pd.to_datetime(df["日付"], format="mixed", errors="coerce")

    # 売上金額が空欄のセルは「その日は売上が無かった」という意味で0円として扱う
    # （外販のように、月に数回しか実績が無い店舗では空欄の行が普通にあるため）。
    # 一方、空欄ではないのに数値として読めない値（入力ミスなど）は、これまで
    # 通りファイル全体を読み込みエラーとして扱う。
    raw_sales = df["売上金額"]
    parsed_sales = pd.to_numeric(raw_sales, errors="coerce")
    unparseable_sales = parsed_sales.isna() & raw_sales.notna()
    if unparseable_sales.any():
        raise ValueError("売上金額に数値として読めない値があります")
    parsed_sales = parsed_sales.fillna(0)

    out = pd.DataFrame(
        {
            "date": parsed_date.dt.normalize(),
            "store": df["店舗名"].astype(str).str.strip(),
            "sales": parsed_sales,
        }
    )
    out["customers"] = (
        pd.to_numeric(df["客数"], errors="coerce") if "客数" in df.columns else pd.NA
    )

    bad_dates = out["date"].isna()
    if bad_dates.any():
        raise ValueError("日付列に日付として読み取れない値があります")

    out["source_file"] = path.name
    return out


def load_all_records(folder: Path) -> LoadResult:
    """folder以下の全xlsxファイル（Excelのロックファイル ~$ は除外）を読み込み、
    日付・店舗ごとに集計したデータフレームを返す。
    """
    folder = Path(folder)
    files = sorted(p for p in folder.rglob("*.xlsx") if not p.name.startswith("~$"))

    frames: list[pd.DataFrame] = []
    errors: list[str] = []
    for path in files:
        try:
            frames.append(_read_one_file(path))
        except Exception as exc:  # noqa: BLE001 - 1ファイルの不備で全体を止めない
            errors.append(f"{path.relative_to(folder)}: {exc}")

    if not frames:
        empty = pd.DataFrame(columns=["date", "store", "sales", "customers", "source_file"])
        return LoadResult(records=empty, errors=errors)

    combined = pd.concat(frames, ignore_index=True)
    # 同じ日付・店舗の行が複数ファイル/複数行に分かれている場合は合算する
    grouped = (
        combined.groupby(["date", "store"], as_index=False)
        .agg(sales=("sales", "sum"), customers=("customers", "sum"))
    )
    return LoadResult(records=grouped, errors=errors)


def days_in_month(year: int, month: int) -> int:
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    return (next_month - date(year, month, 1)).days


def filter_stores(df: pd.DataFrame, stores: list[str] | None) -> pd.DataFrame:
    if not stores:
        return df
    return df[df["store"].isin(stores)]


def split_external_sales(
    df: pd.DataFrame, external_store: str = EXTERNAL_SALES_STORE
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """店舗名が外販（スポット売上）の行を切り出す。

    戻り値は (店舗売上のみ, 外販売上のみ) のタプル。店舗別の合計・ランキング・
    前年比などはすべて店舗売上側だけを使い、外販売上を一切混ぜないようにする。
    """
    is_external = df["store"] == external_store
    return df[~is_external].copy(), df[is_external].copy()


def daily_totals(df: pd.DataFrame) -> pd.DataFrame:
    """日付ごとの売上合計（全店舗分を合算）。"""
    if df.empty:
        return pd.DataFrame(columns=["date", "sales"])
    return df.groupby("date", as_index=False)["sales"].sum().sort_values("date")


def month_slice(df: pd.DataFrame, year: int, month: int) -> pd.DataFrame:
    if df.empty:
        return df
    mask = (df["date"].dt.year == year) & (df["date"].dt.month == month)
    return df[mask]


def _trailing_avg_growth_ratio(df: pd.DataFrame, year: int, month: int, lookback_months: int = 3) -> float | None:
    """当月を除く直近数ヶ月分の「実績の前年同月比」の平均を返す。
    月初のわずかな実績だけで着地予測がブレるのを防ぐための土台値として使う
    （データが無い/前年データが無い月はスキップする）。"""
    ratios = []
    y, m = year, month
    for _ in range(lookback_months):
        m -= 1
        if m == 0:
            m, y = 12, y - 1
        this_total = float(month_slice(df, y, m)["sales"].sum())
        last_total = float(month_slice(df, y - 1, m)["sales"].sum())
        if this_total > 0 and last_total > 0:
            ratios.append(this_total / last_total)
    return sum(ratios) / len(ratios) if ratios else None


def month_progress(df: pd.DataFrame, year: int, month: int, as_of: date) -> dict:
    """当月の進捗（累計・平均・着地予測）を計算する。"""
    this_month = month_slice(df, year, month)
    mtd = this_month[this_month["date"].dt.date <= as_of]

    total_days = days_in_month(year, month)
    elapsed_days = min(as_of.day, total_days) if as_of.year == year and as_of.month == month else total_days

    mtd_total = float(mtd["sales"].sum())
    avg_daily = mtd_total / elapsed_days if elapsed_days else 0.0
    forecast_run_rate = avg_daily * total_days

    # 前年同月データが十分にあれば、前年同月実績に「今年の進捗比」を掛けた予測も出す
    last_year = year - 1
    last_year_month = month_slice(df, last_year, month)
    last_year_mtd = last_year_month[last_year_month["date"].dt.day <= elapsed_days]
    last_year_mtd_total = float(last_year_mtd["sales"].sum())
    last_year_full_total = float(last_year_month["sales"].sum())

    forecast_yoy_adjusted = None
    if last_year_mtd_total > 0 and last_year_full_total > 0:
        current_growth_ratio = mtd_total / last_year_mtd_total
        trend_growth_ratio = _trailing_avg_growth_ratio(df, year, month)
        if trend_growth_ratio is not None:
            # 月初は今月実績が少なくブレやすいため、直近3ヶ月の平均的な前年比と
            # 混ぜ合わせる。日数が経つにつれて今月実績の比重を増やし、
            # 月末には今月実績のみの伸び率に収束する。
            weight = elapsed_days / total_days
            growth_ratio = weight * current_growth_ratio + (1 - weight) * trend_growth_ratio
        else:
            growth_ratio = current_growth_ratio
        forecast_yoy_adjusted = last_year_full_total * growth_ratio

    mtd_yoy_pct = None
    if last_year_mtd_total > 0:
        mtd_yoy_pct = mtd_total / last_year_mtd_total * 100

    # 先月同時点（同じ経過日数まで）の累計と比較する（月末まで終わっている
    # 先月の総売上とではなく、公平に「同じ日数分」で比較するため）
    prev_month, prev_month_year = (12, year - 1) if month == 1 else (month - 1, year)
    prev_month_slice = month_slice(df, prev_month_year, prev_month)
    prev_month_mtd = prev_month_slice[prev_month_slice["date"].dt.day <= elapsed_days]
    prev_month_mtd_total = float(prev_month_mtd["sales"].sum())
    mtd_diff_vs_prev_month = (
        mtd_total - prev_month_mtd_total if prev_month_mtd_total > 0 else None
    )

    forecast = forecast_yoy_adjusted or forecast_run_rate
    forecast_yoy_pct = None
    if last_year_full_total > 0:
        forecast_yoy_pct = forecast / last_year_full_total * 100

    return {
        "year": year,
        "month": month,
        "elapsed_days": elapsed_days,
        "total_days": total_days,
        "mtd_total": mtd_total,
        "avg_daily": avg_daily,
        "forecast_run_rate": forecast_run_rate,
        "forecast_yoy_adjusted": forecast_yoy_adjusted,
        "last_year_mtd_total": last_year_mtd_total if last_year_mtd_total else None,
        "last_year_full_total": last_year_full_total if last_year_full_total else None,
        "mtd_yoy_pct": mtd_yoy_pct,
        "forecast_yoy_pct": forecast_yoy_pct,
        "prev_month_mtd_total": prev_month_mtd_total if prev_month_mtd_total else None,
        "mtd_diff_vs_prev_month": mtd_diff_vs_prev_month,
    }


def yoy_same_day(df: pd.DataFrame, target_date: date) -> dict:
    """指定日の売上と、前年同日の売上を比較する。"""
    today_total = float(df[df["date"].dt.date == target_date]["sales"].sum())
    try:
        last_year_date = target_date.replace(year=target_date.year - 1)
    except ValueError:
        # 2/29のようなケースは2/28に読み替える
        last_year_date = target_date.replace(year=target_date.year - 1, day=28)
    last_year_total = float(df[df["date"].dt.date == last_year_date]["sales"].sum())

    pct_change = None
    if last_year_total > 0:
        pct_change = today_total / last_year_total * 100

    return {
        "target_date": target_date,
        "today_total": today_total,
        "last_year_date": last_year_date,
        "last_year_total": last_year_total if last_year_total else None,
        "pct_change": pct_change,
    }


def yoy_daily_series(df: pd.DataFrame, year: int, month: int) -> pd.DataFrame:
    """今年と前年の同月を、月内の日付（day-of-month）で並べて比較できる表を作る。"""
    this_year = daily_totals(month_slice(df, year, month)).rename(columns={"sales": "this_year"})
    last_year = daily_totals(month_slice(df, year - 1, month)).rename(columns={"sales": "last_year"})

    this_year["day"] = this_year["date"].dt.day
    last_year["day"] = last_year["date"].dt.day

    merged = pd.merge(
        this_year[["day", "this_year"]],
        last_year[["day", "last_year"]],
        on="day",
        how="outer",
    ).sort_values("day")
    return merged


def monthly_yoy_series(
    df: pd.DataFrame, as_of: date, months: int = 12, end_offset: int = 0
) -> pd.DataFrame:
    """基準日から遡ったNヶ月分（デフォルト12ヶ月）の月別実績を、前年同月と比較する。

    直近の月（基準日を含む月）が営業途中の場合は、今年・前年とも
    「月初から基準日と同じ日数分」で揃えて比較する（それ以外の月はフル月同士で比較）。
    end_offsetを指定すると、表示期間の終端を基準日の月からさらにその月数だけ
    過去にずらす（グラフの「もっと過去を見る」ボタン用）。
    """
    rows = []
    base_index = as_of.year * 12 + (as_of.month - 1) - end_offset
    for offset in range(months - 1, -1, -1):
        idx = base_index - offset
        year, month0 = divmod(idx, 12)
        month = month0 + 1
        is_partial = (year == as_of.year and month == as_of.month)
        day_limit = as_of.day if is_partial else days_in_month(year, month)

        this_month_all = month_slice(df, year, month)
        this_total = float(this_month_all[this_month_all["date"].dt.day <= day_limit]["sales"].sum())

        last_month_all = month_slice(df, year - 1, month)
        has_last_year = not last_month_all.empty
        last_total = (
            float(last_month_all[last_month_all["date"].dt.day <= day_limit]["sales"].sum())
            if has_last_year
            else None
        )

        yoy_pct = None
        if last_total:
            yoy_pct = this_total / last_total * 100

        rows.append(
            {
                "year": year,
                "month": month,
                "label": f"{year}年{month}月",
                "this_year": this_total,
                "last_year": last_total,
                "yoy_pct": yoy_pct,
                "is_partial": is_partial,
            }
        )
    return pd.DataFrame(rows)


def yearly_yoy_series(
    df: pd.DataFrame, as_of: date, years: int = 12, end_offset: int = 0
) -> pd.DataFrame:
    """基準日から遡ったN年分（デフォルト12年）の年別実績を、前年（暦年）と比較する。

    今年（基準日を含む年）が年度途中の場合は、今年・前年とも
    「年始から基準日と同じ日数分」で揃えて比較する（それ以外の年はフル年同士で比較）。
    end_offsetを指定すると、表示期間の終端を基準日の年からさらにその年数だけ
    過去にずらす（グラフの「もっと過去を見る」ボタン用）。
    """
    rows = []
    base_year = as_of.year - end_offset
    day_of_year_limit_for_as_of = as_of.timetuple().tm_yday
    for offset in range(years - 1, -1, -1):
        year = base_year - offset
        is_partial = year == as_of.year
        day_limit = day_of_year_limit_for_as_of if is_partial else 366

        this_year_all = df[df["date"].dt.year == year]
        this_total = float(
            this_year_all[this_year_all["date"].dt.dayofyear <= day_limit]["sales"].sum()
        )

        last_year_all = df[df["date"].dt.year == year - 1]
        has_last_year = not last_year_all.empty
        last_total = (
            float(last_year_all[last_year_all["date"].dt.dayofyear <= day_limit]["sales"].sum())
            if has_last_year
            else None
        )

        yoy_pct = None
        if last_total:
            yoy_pct = this_total / last_total * 100

        rows.append(
            {
                "year": year,
                "label": f"{year}年",
                "this_year": this_total,
                "last_year": last_total,
                "yoy_pct": yoy_pct,
                "is_partial": is_partial,
            }
        )
    return pd.DataFrame(rows)


def calendar_year_yoy(df: pd.DataFrame, as_of: date) -> dict:
    """暦年（1月〜12月）の累計売上を前年同期間と比較する。"""
    year = as_of.year
    cutoff_this = as_of
    try:
        cutoff_last = as_of.replace(year=year - 1)
    except ValueError:
        cutoff_last = as_of.replace(year=year - 1, day=28)

    this_year_ytd_df = df[(df["date"].dt.year == year) & (df["date"].dt.date <= cutoff_this)]
    last_year_ytd_df = df[(df["date"].dt.year == year - 1) & (df["date"].dt.date <= cutoff_last)]
    last_year_full_df = df[df["date"].dt.year == year - 1]

    this_year_ytd = float(this_year_ytd_df["sales"].sum())
    last_year_ytd = float(last_year_ytd_df["sales"].sum()) if not last_year_ytd_df.empty else None
    last_year_full_total = float(last_year_full_df["sales"].sum()) if not last_year_full_df.empty else None

    yoy_pct = None
    if last_year_ytd:
        yoy_pct = this_year_ytd / last_year_ytd * 100

    return {
        "year": year,
        "as_of": as_of,
        "this_year_ytd": this_year_ytd,
        "last_year_ytd": last_year_ytd,
        "yoy_pct": yoy_pct,
        "last_year_full_total": last_year_full_total,
    }


def daily_store_snapshot(df: pd.DataFrame, target_date: date) -> pd.DataFrame:
    """指定日の店舗別売上を、前年同日の売上・前年比とあわせて一覧化する。"""
    try:
        last_year_date = target_date.replace(year=target_date.year - 1)
    except ValueError:
        # 2/29のようなケースは2/28に読み替える
        last_year_date = target_date.replace(year=target_date.year - 1, day=28)

    today_df = df[df["date"].dt.date == target_date][["store", "sales"]]
    last_year_df = df[df["date"].dt.date == last_year_date][["store", "sales"]].rename(
        columns={"sales": "last_year_sales"}
    )

    merged = pd.merge(today_df, last_year_df, on="store", how="outer").fillna(0)
    merged["yoy_pct"] = merged.apply(
        lambda r: (r["sales"] / r["last_year_sales"] * 100) if r["last_year_sales"] > 0 else None,
        axis=1,
    )
    return merged.sort_values("store")


def store_ranking(df: pd.DataFrame, year: int, month: int, as_of: date) -> pd.DataFrame:
    """店舗別の当月累計売上と前年同期間比を算出する。"""
    this_month = month_slice(df, year, month)
    mtd = this_month[this_month["date"].dt.date <= as_of]
    elapsed_days = as_of.day if (as_of.year == year and as_of.month == month) else days_in_month(year, month)

    this_totals = mtd.groupby("store", as_index=False)["sales"].sum().rename(columns={"sales": "mtd_sales"})

    last_year_month = month_slice(df, year - 1, month)
    last_year_mtd = last_year_month[last_year_month["date"].dt.day <= elapsed_days]
    last_totals = last_year_mtd.groupby("store", as_index=False)["sales"].sum().rename(
        columns={"sales": "last_year_mtd_sales"}
    )
    # 参考値: 前年同月のフル月合計（経過日数で絞らない、店舗ごとの前年売上計）
    last_year_full_totals = last_year_month.groupby("store", as_index=False)["sales"].sum().rename(
        columns={"sales": "last_year_full_sales"}
    )

    merged = pd.merge(this_totals, last_totals, on="store", how="outer")
    merged = pd.merge(merged, last_year_full_totals, on="store", how="outer").fillna(0)
    merged["yoy_pct"] = merged.apply(
        lambda r: (r["mtd_sales"] / r["last_year_mtd_sales"] * 100) if r["last_year_mtd_sales"] > 0 else None,
        axis=1,
    )
    return merged.sort_values("mtd_sales", ascending=False)


def daily_record(df: pd.DataFrame, top_n: int = 1) -> list[dict]:
    """全期間の中で、1日の売上が高かった記録（日商ギネス）を、多い順にtop_n件返す。"""
    if df.empty:
        return []
    top = df.nlargest(top_n, "sales")
    return [
        {"date": row["date"].date(), "store": row["store"], "sales": float(row["sales"])}
        for _, row in top.iterrows()
    ]


def monthly_group_record(df: pd.DataFrame, top_n: int = 1) -> list[dict]:
    """全期間の中で、全店舗合計の月間売上が高かった記録（月商ギネス）を、多い順にtop_n件返す。"""
    if df.empty:
        return []
    tmp = df.copy()
    tmp["year"] = tmp["date"].dt.year
    tmp["month"] = tmp["date"].dt.month
    grouped = tmp.groupby(["year", "month"], as_index=False)["sales"].sum()
    top = grouped.nlargest(top_n, "sales")
    return [
        {"year": int(row["year"]), "month": int(row["month"]), "sales": float(row["sales"])}
        for _, row in top.iterrows()
    ]
