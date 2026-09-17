"""Googleカレンダー（公開設定）から、本日の予定を抽出してテキストで表示する
ための処理。

ダッシュボードの`google_calendar_src`は、Googleカレンダーの埋め込み表示用
URL（例: https://calendar.google.com/calendar/embed?src=xxxx%40group.calendar.google.com&ctz=...）
で、これはiframe埋め込みにしか使えない。今日の予定だけをテキストで抜き出す
ために、同じ公開カレンダーのICS（iCalendar）形式のエクスポートURLを組み立てて
取得する（Googleカレンダー側で「公開」設定になっている前提。カレンダーIDは
埋め込み用URLのsrcパラメータから取り出す）。

繰り返し予定（定休日など）にも対応するため、icalendar/recurring-ical-events
ライブラリでその日に実際に発生する予定だけを展開して取り出している。

この開発環境からはGoogleカレンダーへ接続して実際のデータを検証できていない
ため（外部サイトへ接続できない）、公開情報をもとにした未検証の実装。本番
環境で表示を確認し、うまく取得できない場合はカレンダーの公開設定（「予定の
表示」を一般公開にする必要がある）などの見直しが必要になる可能性がある。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from urllib.parse import parse_qs, quote, urlparse
from zoneinfo import ZoneInfo

import requests

try:
    import icalendar
    import recurring_ical_events
except ImportError:  # ライブラリが未インストールの環境でもダッシュボード全体は壊さない
    icalendar = None
    recurring_ical_events = None

JST = ZoneInfo("Asia/Tokyo")

REQUEST_TIMEOUT_SECONDS = 8
REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BigbossDashboard/1.0)"}


def _calendar_id_from_embed_src(embed_src: str) -> str | None:
    """埋め込み用URL（.../calendar/embed?src=...）からカレンダーIDを取り出す。"""
    try:
        query = parse_qs(urlparse(embed_src).query)
        values = query.get("src")
        return values[0] if values else None
    except Exception:
        return None


def fetch_today_events(embed_src: str, target_date: date | None = None) -> list[dict] | None:
    """指定日（省略時は日本時間での本日）の予定一覧を取得する。取得・解析に
    失敗した場合はNoneを返す（表示側では何も表示しない）。

    戻り値の形式（開始時刻の早い順。終日予定は先頭にまとめる）:
    [{"title": str, "start_label": str, "all_day": bool}, ...]
    """
    if icalendar is None or recurring_ical_events is None:
        return None
    if not embed_src:
        return None

    calendar_id = _calendar_id_from_embed_src(embed_src)
    if not calendar_id:
        return None

    target = target_date or datetime.now(JST).date()

    try:
        ics_url = f"https://calendar.google.com/calendar/ical/{quote(calendar_id, safe='')}/public/basic.ics"
        response = requests.get(ics_url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        cal = icalendar.Calendar.from_ical(response.content)
    except Exception:
        return None

    try:
        range_start = datetime.combine(target, time.min, tzinfo=JST)
        range_end = range_start + timedelta(days=1)
        occurrences = recurring_ical_events.of(cal).between(range_start, range_end)
    except Exception:
        return None

    events = []
    for component in occurrences:
        try:
            title = str(component.get("summary", "（無題の予定）"))
            dtstart = component.get("dtstart").dt
            all_day = not isinstance(dtstart, datetime)
            if all_day:
                sort_key = (0, "")
                start_label = "終日"
            else:
                if dtstart.tzinfo is not None:
                    dtstart = dtstart.astimezone(JST)
                start_label = dtstart.strftime("%H:%M")
                sort_key = (1, start_label)
            events.append(
                {"title": title, "start_label": start_label, "all_day": all_day, "_sort_key": sort_key}
            )
        except Exception:
            continue

    events.sort(key=lambda e: e["_sort_key"])
    for event in events:
        event.pop("_sort_key", None)
    return events
