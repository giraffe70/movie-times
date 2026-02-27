"""電影時刻查詢 — Streamlit 主介面

僅包含 UI 邏輯，所有爬蟲、快取、工具函式均由各模組提供。
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import streamlit as st

# --- 頁面設定（必須是第一個 Streamlit 命令）---
st.set_page_config(page_title="電影時刻查詢", page_icon="🎬")

# --- 初始化環境（僅首次執行）---
from config import load_worker_url, setup_environment, setup_logging

setup_logging()
setup_environment()
load_worker_url()

# --- 匯入模組 ---
from cache.cache_layer import (
    cached_showtime_get_movies_and_cinemas,
    cached_showtime_get_movie_times,
    cached_vieshow_get_cinemas_and_movies,
    cached_vieshow_get_movie_times,
)
from utils.date_utils import filter_by_date


# ====================================================================
# 共用 UI 元件
# ====================================================================

def show_results(
    results: dict[str, dict[str, list[str]]],
    selected_movie: str,
    date_mode_key: str,
    date_filter_value: date | tuple[date, date] | None,
    booking_url: str = "",
    booking_label: str = "前往官方網站訂票",
) -> None:
    """顯示查詢結果（威秀 / 秀泰共用）。"""
    if results:
        filtered_results: dict[str, dict[str, list[str]]] = {}
        for cinema_name, times_map in results.items():
            filtered_results[cinema_name] = filter_by_date(
                times_map, date_mode_key, date_filter_value
            )

        has_any_times = any(bool(tm) for tm in filtered_results.values())

        if has_any_times:
            st.success(f"查詢完成！以下是《{selected_movie}》的場次：")

            for cinema_name, times_map in filtered_results.items():
                st.markdown(f"### 🏢 {cinema_name}")
                if not times_map:
                    st.caption("此影城目前無符合條件的場次")
                else:
                    for date_str, times in times_map.items():
                        times_joined = " / ".join(times)
                        st.markdown(f"- **{date_str}**：{times_joined}")
                st.markdown("")

            # 訂票連結
            if booking_url:
                st.markdown("---")
                st.markdown(
                    f"🎟️ **[{booking_label}]({booking_url})**"
                )
        else:
            if date_mode_key != "all":
                st.warning(
                    f"⚠️ 所選影城在指定日期內無《{selected_movie}》的場次，"
                    "請嘗試調整日期條件。"
                )
            else:
                st.warning(
                    f"⚠️ 所選影城目前皆無《{selected_movie}》的場次"
                )
    else:
        st.warning("⚠️ 查無資料或解析失敗")
        st.markdown(
            """
**可能原因：**
1. 所選影城目前沒有此電影的場次。
2. 網頁載入過慢 (Timeout)。
3. 官網結構改變。

請查看終端機 (Terminal) 的詳細 Log 進行除錯。
"""
        )


def date_filter_ui(
    key_prefix: str,
) -> tuple[str, date | tuple[date, date] | None]:
    """共用日期篩選 UI。

    Args:
        key_prefix: Streamlit widget key 前綴（避免 key 衝突）

    Returns:
        (date_mode_key, date_filter_value)
    """
    st.subheader("3️⃣ 選擇日期")
    date_mode: str = st.radio(
        "篩選方式：",
        ["全部日期", "特定日期", "日期區間"],
        horizontal=True,
        label_visibility="collapsed",
        key=f"{key_prefix}_date_mode",
    )

    date_filter_value: date | tuple[date, date] | None = None
    if date_mode == "特定日期":
        date_filter_value = st.date_input(
            "選擇日期：",
            value=date.today(),
            key=f"{key_prefix}_date_single",
        )
    elif date_mode == "日期區間":
        col_start, col_end = st.columns(2)
        with col_start:
            start_date = st.date_input(
                "起始日期：",
                value=date.today(),
                key=f"{key_prefix}_date_start",
            )
        with col_end:
            end_date = st.date_input(
                "結束日期：",
                value=date.today() + timedelta(days=6),
                key=f"{key_prefix}_date_end",
            )
        date_filter_value = (start_date, end_date)

    date_mode_key: str = {
        "全部日期": "all",
        "特定日期": "single",
        "日期區間": "range",
    }[date_mode]

    return date_mode_key, date_filter_value


# ====================================================================
# 主介面
# ====================================================================

st.title("🎬 電影時刻查詢")
st.divider()

tab_vieshow, tab_showtime = st.tabs(["🍿 威秀影城", "🎬 秀泰影城"])

# ----------------------------------------------------------------------
# Tab 1: 威秀影城（自動載入）
# ----------------------------------------------------------------------
VIESHOW_OFFICIAL_URL = "https://www.vscinemas.com.tw/"
SHOWTIME_OFFICIAL_URL = "https://www.showtimes.com.tw/programs"

with tab_vieshow:
    st.markdown(
        f"🌐 官方網站：[威秀影城]({VIESHOW_OFFICIAL_URL})"
    )
    # 自動載入威秀影城資料
    if st.session_state.get("vs_data") is None:
        with st.spinner("正在讀取威秀影城與電影清單..."):
            vs_data = cached_vieshow_get_cinemas_and_movies()
        st.session_state["vs_data"] = vs_data
        st.rerun()
    else:
        vs_cinema_map, vs_movie_list = st.session_state["vs_data"]

        if not vs_cinema_map:
            st.error("無法讀取威秀影城清單，請查看終端機錯誤訊息。")
        elif not vs_movie_list:
            st.warning("無法取得威秀電影清單。")
        else:
            # Step 1: 選擇電影
            st.subheader("1️⃣ 選擇電影")
            vs_selected_movie: str = st.selectbox(
                "請選擇電影：",
                vs_movie_list,
                label_visibility="collapsed",
                key="vs_movie",
            )

            # Step 2: 選擇影城
            st.subheader("2️⃣ 選擇影城（可多選）")
            vs_selected_cinemas: list[str] = st.multiselect(
                "請選擇影城：",
                list(vs_cinema_map.keys()),
                default=[],
                label_visibility="collapsed",
                key="vs_cinemas",
            )

            # Step 3: 日期篩選
            vs_date_mode_key, vs_date_filter_value = date_filter_ui("vs")

            st.divider()

            # 查詢按鈕
            if not vs_selected_cinemas:
                st.button(
                    "🔍 查詢時刻表",
                    type="primary",
                    disabled=True,
                    key="vs_btn",
                )
                st.info("請先選擇至少一間影城，再點擊查詢。")
            else:
                if st.button(
                    "🔍 查詢時刻表", type="primary", key="vs_btn"
                ):
                    selected_cinema_dict = {
                        name: vs_cinema_map[name]
                        for name in vs_selected_cinemas
                    }
                    cinema_json = json.dumps(
                        selected_cinema_dict, ensure_ascii=False
                    )

                    with st.spinner(
                        f"正在查詢 {len(vs_selected_cinemas)} 間威秀影城的"
                        f"《{vs_selected_movie}》場次..."
                    ):
                        results = cached_vieshow_get_movie_times(
                            cinema_json, vs_selected_movie
                        )

                    show_results(
                        results,
                        vs_selected_movie,
                        vs_date_mode_key,
                        vs_date_filter_value,
                        booking_url=VIESHOW_OFFICIAL_URL,
                        booking_label="前往威秀影城官網訂票",
                    )

        # 重新載入按鈕
        st.divider()
        if st.button("🔄 重新載入清單", key="refresh_vs"):
            cached_vieshow_get_cinemas_and_movies.clear()
            st.session_state["vs_data"] = None
            st.rerun()


# ----------------------------------------------------------------------
# Tab 2: 秀泰影城（自動載入）
# ----------------------------------------------------------------------
with tab_showtime:
    st.markdown(
        f"🌐 官方網站：[秀泰影城]({SHOWTIME_OFFICIAL_URL})"
    )
    # 自動載入秀泰影城資料
    if st.session_state.get("st_data") is None:
        with st.spinner("正在讀取秀泰電影與影城清單..."):
            st_data = cached_showtime_get_movies_and_cinemas()
        st.session_state["st_data"] = st_data
        st.rerun()
    else:
        st_movies_map, st_cinema_list = st.session_state["st_data"]

        if not st_movies_map:
            st.error("無法讀取秀泰電影清單，請查看終端機錯誤訊息。")
        elif not st_cinema_list:
            st.warning("無法取得秀泰影城清單。")
        else:
            # Step 1: 選擇電影
            st.subheader("1️⃣ 選擇電影")
            st_movie_names: list[str] = list(st_movies_map.keys())
            st_selected_movie: str = st.selectbox(
                "請選擇電影：",
                st_movie_names,
                label_visibility="collapsed",
                key="st_movie",
            )
            st_selected_program_id: str = st_movies_map[st_selected_movie]

            # Step 2: 選擇影城
            st.subheader("2️⃣ 選擇影城（可多選）")
            st_selected_cinemas: list[str] = st.multiselect(
                "請選擇影城：",
                st_cinema_list,
                default=[],
                label_visibility="collapsed",
                key="st_cinemas",
            )

            # Step 3: 日期篩選
            st_date_mode_key, st_date_filter_value = date_filter_ui("st")

            st.divider()

            # 查詢按鈕
            if not st_selected_cinemas:
                st.button(
                    "🔍 查詢時刻表",
                    type="primary",
                    disabled=True,
                    key="st_btn",
                )
                st.info("請先選擇至少一間影城，再點擊查詢。")
            else:
                if st.button(
                    "🔍 查詢時刻表", type="primary", key="st_btn"
                ):
                    cinemas_json = json.dumps(
                        st_selected_cinemas, ensure_ascii=False
                    )

                    with st.spinner(
                        f"正在查詢《{st_selected_movie}》的場次..."
                    ):
                        results = cached_showtime_get_movie_times(
                            st_selected_program_id, cinemas_json
                        )

                    show_results(
                        results,
                        st_selected_movie,
                        st_date_mode_key,
                        st_date_filter_value,
                        booking_url=SHOWTIME_OFFICIAL_URL,
                        booking_label="前往秀泰影城官網訂票",
                    )

        # 重新載入按鈕
        st.divider()
        if st.button("🔄 重新載入清單", key="refresh_st"):
            cached_showtime_get_movies_and_cinemas.clear()
            st.session_state["st_data"] = None
            st.rerun()
