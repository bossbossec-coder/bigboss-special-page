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

    out = pd.DataFrame(
        {
            "date": parsed_date.dt.normalize(),
            "store": df["店舗名"].astype(str).str.strip(),
            "sales": pd.to_numeric(df["売上金額"], errors="coerce"),
        }
    )
    out["customers"] = (
        pd.to_numeric(df["客数"], errors="coerce") if "客数" in df.columns else pd.NA
    )

    bad_dates = out["date"].isna()
    if bad_dates.any():
        raise ValueError("日付列に日付として読み取れない値があります")

    bad_sales = out["sales"].isna()
    if bad_sales.any():
        raise ValueError("売上金額に数値として読めない値があります")

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
        growth_ratio = mtd_total / last_year_mtd_total
        forecast_yoy_adjusted = last_year_full_total * growth_ratio

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
        pct_change = (today_total - last_year_total) / last_year_total * 100

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

    merged = pd.merge(this_totals, last_totals, on="store", how="outer").fillna(0)
    merged["yoy_pct"] = merged.apply(
        lambda r: ((r["mtd_sales"] - r["last_year_mtd_sales"]) / r["last_year_mtd_sales"] * 100)
        if r["last_year_mtd_sales"] > 0
        else None,
        axis=1,
    )
    return merged.sort_values("mtd_sales", ascending=False)
