"""ログイン画面に表示する「本日は○○の日です」メッセージ用のデータ・関数。

カーナビの雑学表示のように、その日に対応する記念日・祝日名を1つ（複数該当
する場合は複数）返す。国民の祝日のうち、日付が年によって動くもの（成人の日
などのハッピーマンデー、春分の日・秋分の日）は計算で求め、それ以外の
記念日は広く知られているものを中心に固定の月日で登録している。
全ての日を網羅しているわけではなく、該当が無い日はNoneを返す
（ログイン画面側では、その場合は日付・曜日のみを表示する）。
"""

from __future__ import annotations

from datetime import date


def _nth_monday(year: int, month: int, n: int) -> date:
    """指定した月のn番目の月曜日を返す（ハッピーマンデー祝日の計算用）。"""
    first_of_month = date(year, month, 1)
    days_to_monday = (7 - first_of_month.weekday()) % 7
    first_monday = 1 + days_to_monday
    return date(year, month, first_monday + (n - 1) * 7)


def _vernal_equinox_day(year: int) -> int:
    """春分の日（3月）を近似式で求める（1980〜2099年の範囲で有効）。"""
    return int(20.8431 + 0.242194 * (year - 1980)) - (year - 1980) // 4


def _autumnal_equinox_day(year: int) -> int:
    """秋分の日（9月）を近似式で求める（1980〜2099年の範囲で有効）。"""
    return int(23.2488 + 0.242194 * (year - 1980)) - (year - 1980) // 4


# 日付が固定の祝日・記念日（広く知られているものを中心とした一部抜粋）
FIXED_DAY_FACTS: dict[tuple[int, int], str] = {
    (1, 1): "元日",
    (1, 7): "七草の日（七草がゆを食べる日）",
    (1, 11): "鏡開きの日",
    (2, 3): "節分",
    (2, 11): "建国記念の日",
    (2, 14): "バレンタインデー",
    (2, 22): "猫の日",
    (2, 23): "天皇誕生日",
    (3, 3): "ひな祭り（桃の節句）",
    (3, 14): "ホワイトデー",
    (4, 1): "エイプリルフール",
    (4, 12): "パンの日",
    (4, 29): "昭和の日",
    (5, 3): "憲法記念日",
    (5, 4): "みどりの日",
    (5, 5): "こどもの日（端午の節句）",
    (6, 10): "時の記念日",
    (6, 16): "和菓子の日",
    (7, 7): "七夕",
    (8, 8): "そろばんの日",
    (8, 11): "山の日",
    (8, 15): "終戦記念日",
    (9, 15): "老人の日",
    (9, 29): "招き猫の日",
    (10, 31): "ハロウィン",
    (11, 3): "文化の日",
    (11, 15): "七五三",
    (11, 22): "いい夫婦の日",
    (11, 23): "勤労感謝の日",
    (12, 24): "クリスマスイブ",
    (12, 25): "クリスマス",
    (12, 31): "大晦日",
}


def get_day_fact(target: date) -> str | None:
    """指定日に対応する「本日は○○の日です」的なメッセージを返す
    （複数該当する場合は " / " でつなげる。該当が無い日はNone）。"""
    year, month, day = target.year, target.month, target.day

    floating_facts = {
        (1, _nth_monday(year, 1, 2).day): "成人の日",
        (3, _vernal_equinox_day(year)): "春分の日",
        (7, _nth_monday(year, 7, 3).day): "海の日",
        (9, _nth_monday(year, 9, 3).day): "敬老の日",
        (9, _autumnal_equinox_day(year)): "秋分の日",
        (10, _nth_monday(year, 10, 2).day): "スポーツの日",
    }

    facts = [label for (m, d), label in floating_facts.items() if m == month and d == day]
    if (month, day) in FIXED_DAY_FACTS:
        facts.append(FIXED_DAY_FACTS[(month, day)])

    return " / ".join(facts) if facts else None
