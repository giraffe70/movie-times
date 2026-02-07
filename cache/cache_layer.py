"""快取層封裝

使用 Streamlit 的 @st.cache_data 裝飾器快取爬蟲結果，
搭配 TTL（Time-to-Live）參數確保資料自動過期。

快取策略：
- 影城 / 電影清單：TTL = 1 小時（3600 秒）
- 場次查詢結果：TTL = 30 分鐘（1800 秒）
"""
from __future__ import annotations

import json

import streamlit as st

from bots.showtime_bot import ShowtimeBot
from bots.vieshow_bot import VieshowBot


# ====================================================================
# 威秀影城快取
# ====================================================================

@st.cache_data(show_spinner=False, ttl=3600)
def cached_vieshow_get_cinemas_and_movies() -> (
    tuple[dict[str, str], list[str]]
):
    """快取威秀影城清單與電影清單（TTL: 1 小時）。"""
    bot = VieshowBot()
    return bot.get_cinemas_and_movies()


@st.cache_data(show_spinner=False, ttl=1800)
def cached_vieshow_get_movie_times(
    cinema_json: str, target_movie: str
) -> dict[str, dict[str, list[str]]]:
    """快取威秀場次查詢結果（TTL: 30 分鐘）。

    Args:
        cinema_json: JSON 序列化的 {影城名稱: 影城代碼}
        target_movie: 目標電影名稱
    """
    cinema_dict: dict[str, str] = json.loads(cinema_json)
    bot = VieshowBot()
    return bot.get_movie_times_for_cinemas(cinema_dict, target_movie)


# ====================================================================
# 秀泰影城快取
# ====================================================================

@st.cache_data(show_spinner=False, ttl=3600)
def cached_showtime_get_movies_and_cinemas() -> (
    tuple[dict[str, str], list[str]]
):
    """快取秀泰電影清單與影城清單（TTL: 1 小時）。"""
    bot = ShowtimeBot()
    return bot.get_movies_and_cinemas()


@st.cache_data(show_spinner=False, ttl=1800)
def cached_showtime_get_movie_times(
    program_id: str, selected_cinemas_json: str
) -> dict[str, dict[str, list[str]]]:
    """快取秀泰場次查詢結果（TTL: 30 分鐘）。

    Args:
        program_id: 電影 ID
        selected_cinemas_json: JSON 序列化的 [影城名稱, ...]
    """
    selected_cinemas: list[str] = json.loads(selected_cinemas_json)
    bot = ShowtimeBot()
    return bot.get_movie_times(program_id, selected_cinemas)
