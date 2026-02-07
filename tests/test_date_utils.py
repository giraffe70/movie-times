"""日期工具函式的單元測試"""
from __future__ import annotations

from datetime import date

import pytest

from utils.date_utils import (
    filter_by_date,
    format_date_with_weekday,
    parse_date_from_string,
)


# ====================================================================
# format_date_with_weekday
# ====================================================================

class TestFormatDateWithWeekday:
    """測試 format_date_with_weekday 函式"""

    def test_saturday(self) -> None:
        # 2026-02-07 是星期六
        result = format_date_with_weekday(date(2026, 2, 7))
        assert result == "2月7日(六)"

    def test_monday(self) -> None:
        # 2026-02-09 是星期一
        result = format_date_with_weekday(date(2026, 2, 9))
        assert result == "2月9日(一)"

    def test_single_digit_month_and_day(self) -> None:
        # 2026-01-05 是星期一
        result = format_date_with_weekday(date(2026, 1, 5))
        assert result == "1月5日(一)"

    def test_double_digit_month_and_day(self) -> None:
        # 2026-12-25 是星期五
        result = format_date_with_weekday(date(2026, 12, 25))
        assert result == "12月25日(五)"


# ====================================================================
# parse_date_from_string
# ====================================================================

class TestParseDateFromString:
    """測試 parse_date_from_string 函式"""

    def test_basic_format(self) -> None:
        result = parse_date_from_string("2月6日(五)")
        assert result is not None
        assert result.month == 2
        assert result.day == 6

    def test_padded_format(self) -> None:
        result = parse_date_from_string("02月06日(四)")
        assert result is not None
        assert result.month == 2
        assert result.day == 6

    def test_with_extra_text(self) -> None:
        result = parse_date_from_string("場次 3月15日(日) 今日")
        assert result is not None
        assert result.month == 3
        assert result.day == 15

    def test_invalid_string(self) -> None:
        result = parse_date_from_string("invalid")
        assert result is None

    def test_empty_string(self) -> None:
        result = parse_date_from_string("")
        assert result is None

    def test_invalid_date(self) -> None:
        # 2月30日不存在
        result = parse_date_from_string("2月30日(一)")
        assert result is None

    def test_year_inference_current_year(self) -> None:
        today = date.today()
        # 使用當前月份，應回傳今年
        date_str = f"{today.month}月15日(一)"
        result = parse_date_from_string(date_str)
        assert result is not None
        assert result.year == today.year

    def test_year_inference_next_year(self) -> None:
        today = date.today()
        if today.month > 1:
            # 使用比當前月份小的月份，應回傳明年
            date_str = f"{today.month - 1}月15日(一)"
            result = parse_date_from_string(date_str)
            assert result is not None
            assert result.year == today.year + 1


# ====================================================================
# filter_by_date
# ====================================================================

class TestFilterByDate:
    """測試 filter_by_date 函式"""

    @pytest.fixture()
    def sample_times_map(self) -> dict[str, list[str]]:
        return {
            "2月6日(五)": ["10:00", "14:00", "18:00"],
            "2月7日(六)": ["11:00", "15:00"],
            "2月8日(日)": ["13:00", "17:00"],
        }

    def test_all_mode(self, sample_times_map: dict[str, list[str]]) -> None:
        result = filter_by_date(sample_times_map, "all", None)
        assert result == sample_times_map

    def test_single_mode_match(
        self, sample_times_map: dict[str, list[str]]
    ) -> None:
        target = date(2026, 2, 7)
        result = filter_by_date(sample_times_map, "single", target)
        assert "2月7日(六)" in result
        assert "2月6日(五)" not in result
        assert "2月8日(日)" not in result

    def test_single_mode_no_match(
        self, sample_times_map: dict[str, list[str]]
    ) -> None:
        target = date(2026, 2, 10)
        result = filter_by_date(sample_times_map, "single", target)
        assert len(result) == 0

    def test_range_mode(
        self, sample_times_map: dict[str, list[str]]
    ) -> None:
        start = date(2026, 2, 6)
        end = date(2026, 2, 7)
        result = filter_by_date(sample_times_map, "range", (start, end))
        assert "2月6日(五)" in result
        assert "2月7日(六)" in result
        assert "2月8日(日)" not in result

    def test_range_mode_all_match(
        self, sample_times_map: dict[str, list[str]]
    ) -> None:
        start = date(2026, 2, 1)
        end = date(2026, 2, 28)
        result = filter_by_date(sample_times_map, "range", (start, end))
        assert len(result) == 3

    def test_unparseable_date_preserved(self) -> None:
        times_map = {
            "未知日期": ["10:00"],
            "2月7日(六)": ["14:00"],
        }
        target = date(2026, 2, 7)
        result = filter_by_date(times_map, "single", target)
        # 無法解析的日期字串應被保留
        assert "未知日期" in result
        assert "2月7日(六)" in result

    def test_empty_map(self) -> None:
        result = filter_by_date({}, "all", None)
        assert result == {}
