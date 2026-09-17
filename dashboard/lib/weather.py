"""気象庁（JMA）の天気予報API（登録不要・無料）から、鎌ケ谷市（千葉県北西部）の
天気予報を取得する。

気象庁は登録不要の無料オープンデータとして天気予報のJSONを公開しているが、
次のような制約がある。
- 鎌ケ谷市そのものの区分ではなく「千葉県北西部」という広域区分の予報になる
  （気象庁の予報区分は市区町村単位ではなく、もっと広い区域単位のため）
- 「1時間ごと」の予報は無く、最も細かくても「6時間ごとの降水確率」まで
  （今日・明日の天気そのものは1日単位のテキストで表現される）
- 気温（最高・最低）は千葉県北西部専用のデータが無く、代表地点である
  千葉市の値を使う（気象庁のデータ構造上、天気の区域と気温の観測地点が
  別になっているため）

この開発環境からは気象庁のサイトへ接続して実際のデータ構造を検証できて
いないため（外部サイトへ接続できない）、公開情報をもとにした未検証の実装。
本番環境で表示を確認し、うまく取得できない場合は構造の見直しが必要になる
可能性がある。
"""

from __future__ import annotations

from datetime import datetime

import requests

FORECAST_URL = "https://www.jma.go.jp/bosai/forecast/data/forecast/120000.json"
KAMAGAYA_AREA_CODE = "120010"  # 千葉県北西部（鎌ケ谷市を含む予報区分）
CHIBA_PREF_AREA_CODE = "120000"  # 千葉県全体（週間天気予報の天気・降水確率はこの単位）
CHIBA_CITY_TEMP_CODE = "45148"  # 千葉市（気温の代表地点。鎌ケ谷市専用の気温データは無い）

REQUEST_TIMEOUT_SECONDS = 8
REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BigbossDashboard/1.0)"}

WEEKDAY_JA = ["月", "火", "水", "木", "金", "土", "日"]

# 気象庁の天気コード -> 日本語表記（よく使われるものを中心に収録。
# 収録の無いコードは「（コード番号）」とだけ表示するフォールバックにしている）
WEATHER_CODE_TEXT: dict[str, str] = {
    "100": "晴れ", "101": "晴れ時々曇り", "102": "晴れ一時雨", "103": "晴れ時々雨",
    "104": "晴れ一時雪", "105": "晴れ時々雪", "106": "晴れ一時雨か雪", "107": "晴れ時々雨か雪",
    "108": "晴れ一時雷雨", "110": "晴れのち時々曇り", "111": "晴れのち曇り",
    "112": "晴れのち一時雨", "113": "晴れのち時々雨", "114": "晴れのち雨",
    "115": "晴れのち一時雪", "116": "晴れのち時々雪", "117": "晴れのち雪",
    "118": "晴れのち雨か雪", "119": "晴れのち雨か雷雨", "120": "晴れ朝夕一時雨",
    "121": "晴れ朝の内一時雨", "122": "晴れ夕方一時雨", "123": "晴れ山沿い雷雨",
    "125": "晴れ午後は雷雨", "126": "晴れ昼頃から雨", "127": "晴れ夕方から雨",
    "128": "晴れ夜は雨", "130": "朝の内霧後晴れ", "131": "晴れ明け方霧",
    "140": "晴れ時々雨で雷を伴う",
    "200": "曇り", "201": "曇り時々晴れ", "202": "曇り一時雨", "203": "曇り時々雨",
    "204": "曇り一時雪", "205": "曇り時々雪", "206": "曇り一時雨か雪", "207": "曇り時々雨か雪",
    "208": "曇り一時雷雨", "209": "霧", "210": "曇りのち時々晴れ", "211": "曇りのち晴れ",
    "212": "曇りのち一時雨", "213": "曇りのち時々雨", "214": "曇りのち雨",
    "215": "曇りのち一時雪", "216": "曇りのち時々雪", "217": "曇りのち雪",
    "218": "曇りのち雨か雪", "219": "曇りのち雨か雷雨", "220": "曇り朝夕一時雨",
    "223": "曇り日中時々晴れ", "224": "曇り昼頃から雨", "225": "曇り夕方から雨",
    "226": "曇り夜は雨", "228": "曇り昼頃から雪", "229": "曇り夕方から雪",
    "230": "曇り夜は雪", "231": "曇り海上海岸は霧か霧雨", "240": "曇り時々雨で雷を伴う",
    "250": "曇り時々雪で雷を伴う",
    "300": "雨", "301": "雨時々晴れ", "302": "雨時々止む", "303": "雨時々雪",
    "304": "雨か雪", "306": "大雨", "308": "暴風雨", "309": "雨一時雪",
    "311": "雨のち晴れ", "313": "雨のち曇り", "314": "雨のち時々雪", "315": "雨のち雪",
    "320": "朝の内雨のち晴れ", "321": "朝の内雨のち曇り", "323": "雨昼頃から晴れ",
    "324": "雨夕方から晴れ", "325": "雨夜は晴れ", "328": "雨一時強く降る",
    "329": "雨一時みぞれ", "340": "雪か雨", "350": "雨で雷を伴う",
    "400": "雪", "401": "雪時々晴れ", "402": "雪時々止む", "403": "雪時々雨",
    "405": "大雪", "406": "風雪強し", "407": "暴風雪", "409": "雪一時雨",
    "411": "雪のち晴れ", "413": "雪のち曇り", "414": "雪のち雨", "425": "雪一時強く降る",
    "426": "雪あられを伴う", "427": "雪一時みぞれ", "430": "みぞれ", "450": "雪で雷を伴う",
}


def _weather_text(code: str | None) -> str:
    if not code:
        return "—"
    return WEATHER_CODE_TEXT.get(code, f"（コード{code}）")


def _find_area(areas: list[dict], area_code: str) -> dict | None:
    for area in areas:
        if area.get("area", {}).get("code") == area_code:
            return area
    return None


def _safe_float(value) -> float | None:
    if value in (None, "", "—"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_weather() -> dict | None:
    """鎌ケ谷市（千葉県北西部）の天気予報を取得する。取得・解析に失敗した
    場合はNoneを返す（表示側で「取得できません」に切り替える）。

    戻り値の形式:
    {
        "today_weather": str,                # 本日の天気（テキスト）
        "today_temp_max": float | None,      # 本日の最高気温（℃、千葉市の代表値）
        "tomorrow_temp_min": float | None,   # 明日の最低気温（℃、千葉市の代表値）
        "pop_periods": [{"label": "18時", "pop": "20"}, ...],  # 概ね24時間分、6時間ごと
        "weekly": [{"date": "9/18(木)", "weather": str, "pop": str,
                    "temp_min": str, "temp_max": str}, ...],
    }
    """
    try:
        response = requests.get(FORECAST_URL, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    except Exception:
        return None

    try:
        short_range = data[0]
        weekly_range = data[1]

        # 本日の天気（テキストで直接提供される）
        weather_series = short_range["timeSeries"][0]
        weather_area = _find_area(weather_series["areas"], KAMAGAYA_AREA_CODE)
        today_weather = weather_area["weathers"][0].replace("　", " ").strip() if weather_area else "—"

        # 6時間ごとの降水確率（今後24時間程度、気象庁が公開する中で最も細かい時間単位）
        pop_series = short_range["timeSeries"][1]
        pop_area = _find_area(pop_series["areas"], KAMAGAYA_AREA_CODE)
        pop_time_defines = pop_series["timeDefines"]
        pop_periods = []
        if pop_area:
            for time_str, pop in zip(pop_time_defines, pop_area["pops"]):
                dt = datetime.fromisoformat(time_str)
                pop_periods.append({"label": f"{dt.month}/{dt.day} {dt.hour}時", "pop": pop})

        # 気温（千葉市の代表値。鎌ケ谷市専用のデータは無い）
        temp_series = short_range["timeSeries"][2]
        temp_area = _find_area(temp_series["areas"], CHIBA_CITY_TEMP_CODE)
        temps = temp_area["temps"] if temp_area else []
        today_temp_max = _safe_float(temps[0]) if len(temps) > 0 else None
        tomorrow_temp_min = _safe_float(temps[1]) if len(temps) > 1 else None

        # 週間天気予報（天気・降水確率は千葉県全体、気温は千葉市の代表値）
        weekly_weather_series = weekly_range["timeSeries"][0]
        weekly_weather_area = _find_area(weekly_weather_series["areas"], CHIBA_PREF_AREA_CODE)
        weekly_time_defines = weekly_weather_series["timeDefines"]

        weekly_temp_series = weekly_range["timeSeries"][1]
        weekly_temp_area = _find_area(weekly_temp_series["areas"], CHIBA_CITY_TEMP_CODE)

        weekly = []
        for i, time_str in enumerate(weekly_time_defines):
            dt = datetime.fromisoformat(time_str)
            date_label = f"{dt.month}/{dt.day}({WEEKDAY_JA[dt.weekday()]})"
            weather_code = weekly_weather_area["weatherCodes"][i] if weekly_weather_area else None
            pop = weekly_weather_area["pops"][i] if weekly_weather_area else ""
            temp_min = weekly_temp_area["tempsMin"][i] if weekly_temp_area else ""
            temp_max = weekly_temp_area["tempsMax"][i] if weekly_temp_area else ""
            weekly.append(
                {
                    "date": date_label,
                    "weather": _weather_text(weather_code),
                    "pop": pop if pop else "—",
                    "temp_min": temp_min if temp_min else "—",
                    "temp_max": temp_max if temp_max else "—",
                }
            )

        return {
            "today_weather": today_weather,
            "today_temp_max": today_temp_max,
            "tomorrow_temp_min": tomorrow_temp_min,
            "pop_periods": pop_periods,
            "weekly": weekly,
        }
    except Exception:
        return None
