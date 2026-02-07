"""全域設定與環境初始化

包含：
- 環境偵測（雲端 / 本機）
- 共用常數（User-Agent、時區、URL 等）
- Cloudflare Worker 設定
- 日誌系統設定
- 雲端環境初始化（Playwright 安裝、Xvfb 啟動）
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import time
from datetime import timedelta, timezone

logger = logging.getLogger(__name__)

# ====================================================================
# 環境偵測
# ====================================================================
IS_CLOUD: bool = not sys.platform.startswith("win")

# ====================================================================
# 共用常數
# ====================================================================
USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

WEEKDAY_NAMES: list[str] = ["一", "二", "三", "四", "五", "六", "日"]
TW_TZ = timezone(timedelta(hours=8))

# ====================================================================
# 威秀影城
# ====================================================================
VIESHOW_URL: str = "https://www.vscinemas.com.tw/ShowTimes/"

# ====================================================================
# 秀泰影城
# ====================================================================
SHOWTIME_PROGRAMS_URL: str = "https://www.showtimes.com.tw/programs"
SHOWTIME_BOOKING_URL_TEMPLATE: str = (
    "https://www.showtimes.com.tw/ticketing/forProgram/{}"
)
SHOWTIME_API_BASE: str = "https://capi.showtimes.com.tw"
SHOWTIME_API_HEADERS: dict[str, str] = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": "https://www.showtimes.com.tw",
    "Referer": "https://www.showtimes.com.tw/",
}

# ====================================================================
# Cloudflare Worker 代理
# ====================================================================
SHOWTIME_WORKER_URL: str = ""
SHOWTIME_WORKER_SECRET: str = ""


def load_worker_url() -> None:
    """從 Streamlit secrets 載入 Cloudflare Worker URL 與認證密鑰。

    需在 Streamlit Cloud → App settings → Secrets 中設定：
      SHOWTIME_WORKER_URL = "https://showtime-proxy.<your-subdomain>.workers.dev"
      SHOWTIME_WORKER_SECRET = "<your-shared-secret>"  (選填)
    """
    global SHOWTIME_WORKER_URL, SHOWTIME_WORKER_SECRET  # noqa: PLW0603
    import streamlit as st

    try:
        SHOWTIME_WORKER_URL = st.secrets["SHOWTIME_WORKER_URL"]
        logger.info("Cloudflare Worker 代理已設定: %s", SHOWTIME_WORKER_URL)
    except (KeyError, FileNotFoundError):
        SHOWTIME_WORKER_URL = ""
        logger.warning("未設定 SHOWTIME_WORKER_URL，雲端環境可能無法查詢秀泰")

    try:
        SHOWTIME_WORKER_SECRET = st.secrets["SHOWTIME_WORKER_SECRET"]
    except (KeyError, FileNotFoundError):
        SHOWTIME_WORKER_SECRET = ""


# ====================================================================
# 日誌系統
# ====================================================================
def setup_logging() -> None:
    """設定日誌系統。雲端使用 INFO 等級，本機使用 DEBUG 等級。"""
    level = logging.INFO if IS_CLOUD else logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ====================================================================
# 環境初始化
# ====================================================================
_environment_initialized: bool = False


def setup_environment() -> None:
    """初始化執行環境（僅在首次呼叫時執行）。

    - Windows：設定 asyncio 事件迴圈策略
    - 雲端：安裝 Playwright chromium、啟動 Xvfb 虛擬顯示器
    """
    global _environment_initialized  # noqa: PLW0603
    if _environment_initialized:
        return
    _environment_initialized = True

    # --- Windows 事件迴圈策略 ---
    if not IS_CLOUD:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        return

    # --- 雲端環境 ---
    # 安裝 Playwright chromium
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
        )
        logger.info("Playwright chromium 安裝成功")
    except Exception as e:
        logger.error("Playwright chromium 安裝失敗: %s", e)

    # 啟動 Xvfb 虛擬顯示器
    if not os.environ.get("DISPLAY"):
        try:
            subprocess.Popen(
                [
                    "/usr/bin/Xvfb", ":99",
                    "-screen", "0", "1920x1080x24",
                    "-nolisten", "tcp",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            os.environ["DISPLAY"] = ":99"
            time.sleep(1)  # 等待 Xvfb 啟動
            logger.info("Xvfb 虛擬顯示器已啟動 (:99)")
        except Exception as e:
            logger.warning("Xvfb 啟動失敗: %s", e)
