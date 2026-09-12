"""動作確認用のサンプル日次売上Excelを生成するスクリプト。

前年同日比・月進捗・月末着地予測を確認できるように、
過去13か月分×10店舗の日次データを data/incoming/ に書き出す。

実行方法:
    python3 scripts/generate_sample_data.py
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import openpyxl

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "incoming"

STORES = [
    "渋谷店", "新宿店", "池袋店", "横浜店", "大宮店",
    "千葉店", "立川店", "大阪店", "名古屋店", "福岡店",
]

BASE_SALES = {store: random.Random(store).randint(300_000, 650_000) for store in STORES}


def daterange(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def simulate_sales(store: str, day: date, rng: random.Random) -> int:
    base = BASE_SALES[store]
    # 土日は客数が増える想定で少し上振れさせる
    weekday_factor = 1.25 if day.weekday() >= 5 else 1.0
    # ざっくり前年より数%成長している想定のトレンド
    months_since_start = (day.year - (day.year - 2)) * 12 + day.month
    growth_factor = 1.0 + 0.004 * months_since_start
    noise = rng.uniform(0.85, 1.15)
    return int(base * weekday_factor * growth_factor * noise)


def write_store_file(store: str, day: date, sales: int, customers: int) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "売上"
    ws.append(["日付", "店舗名", "売上金額", "客数", "備考"])
    ws.append([day.strftime("%Y-%m-%d"), store, sales, customers, ""])

    filename = f"{day.strftime('%Y%m%d')}_{store}.xlsx"
    wb.save(OUTPUT_DIR / filename)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today()
    start = (today.replace(day=1) - timedelta(days=400)).replace(day=1)

    rng = random.Random(42)
    count = 0
    for day in daterange(start, today):
        for store in STORES:
            sales = simulate_sales(store, day, rng)
            customers = max(1, int(sales / rng.randint(2800, 3600)))
            write_store_file(store, day, sales, customers)
            count += 1

    print(f"{count} 件のサンプルExcelファイルを {OUTPUT_DIR} に作成しました。")


if __name__ == "__main__":
    main()
