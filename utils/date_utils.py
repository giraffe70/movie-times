"""日期解析與格式化工具函式"""
from __future__ import annotations

import re
from datetime import date

from config import WEEKDAY_NAMES


def format_date_with_weekday(dt_obj: date) -> str:
    """將 date/datetime 格式化為 '2月6日(五)' 格式。"""
    wd = WEEKDAY_NAMES[dt_obj.weekday()]
    return f"{dt_obj.month}月{dt_obj.day}日({wd})"


def parse_date_from_string(date_str: str) -> date | None:
    """將爬取到的日期字串（如 '2月6日(五)'、'02月06日(四)'）解析為 date 物件。

    年份推斷邏輯：月份 >= 當前月份時使用今年，否則使用明年。
    若解析失敗回傳 None。
    """
    match = re.search(r"(\d{1,2})月(\d{1,2})日", date_str)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        today = date.today()
        year = today.year if month >= today.month else today.year + 1
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


def filter_by_date(
    times_map: dict[str, list[str]],
    date_mode: str,
    date_value: date | tuple[date, date] | None,
) -> dict[str, list[str]]:
    """根據日期篩選條件過濾場次資料。

    Args:
        times_map: {日期字串: [時間列表]}
        date_mode: "all" / "single" / "range"
        date_value: None / date / (start_date, end_date)

    Returns:
        過濾後的 {日期字串: [時間列表]}
    """
    if date_mode == "all":
        return times_map

    filtered: dict[str, list[str]] = {}
    for date_str, times in times_map.items():
        parsed = parse_date_from_string(date_str)
        if parsed is None:
            # 無法解析的日期字串保留不篩選
            filtered[date_str] = times
            continue

        if date_mode == "single" and date_value:
            if parsed == date_value:
                filtered[date_str] = times
        elif date_mode == "range" and date_value:
            start_d, end_d = date_value
            if start_d <= parsed <= end_d:
                filtered[date_str] = times

    return filtered
