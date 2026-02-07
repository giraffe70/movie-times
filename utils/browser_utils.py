"""共用 Playwright 瀏覽器工具函式

提供反偵測瀏覽器頁面建立與安全導航功能。
"""
from __future__ import annotations

import logging

from playwright.sync_api import Browser, Page, Playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from config import IS_CLOUD, USER_AGENT

logger = logging.getLogger(__name__)


def create_stealth_page(
    playwright_instance: Playwright,
    label: str = "",
) -> tuple[Browser, Page]:
    """建立具有反偵測措施的瀏覽器頁面。

    啟動策略：
    1. Windows 優先使用 MS Edge headless（本機環境通常有 Edge）
    2. 備用：headless=False 隱藏視窗模式（雲端靠 Xvfb，本機靠螢幕外座標）

    Args:
        playwright_instance: stealth 包裝後的 Playwright 實例
        label: 日誌標籤（如 "威秀"、"秀泰"）

    Returns:
        (browser, page) 元組
    """
    launch_args: list[str] = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
    ]
    hidden_window_args: list[str] = [
        "--window-position=-32000,-32000",
        "--window-size=1,1",
    ]

    browser: Browser | None = None

    # 1. Windows：優先使用 Edge headless
    if not IS_CLOUD:
        try:
            browser = playwright_instance.chromium.launch(
                channel="msedge",
                headless=True,
                args=launch_args,
            )
            logger.info("[%s] 使用 Edge headless 模式", label)
        except Exception as e:
            logger.debug("[%s] Edge 不可用: %s", label, e)

    # 2. 備用：headless=False 隱藏視窗模式
    if browser is None:
        browser = playwright_instance.chromium.launch(
            headless=False,
            args=launch_args + hidden_window_args,
        )
        mode = "雲端 Xvfb" if IS_CLOUD else "隱藏視窗"
        logger.info("[%s] 使用%s模式", label, mode)

    page = browser.new_page(
        user_agent=USER_AGENT,
        viewport={"width": 1920, "height": 1080},
        locale="zh-TW",
    )
    return browser, page


def goto_safe(
    page: Page,
    url: str,
    timeout: int = 60000,
) -> None:
    """安全導航：先嘗試 wait_until='load'，逾時改用 'domcontentloaded'。

    SPA 網站可能永遠不會觸發 load 事件，此函式提供自動降級。
    """
    try:
        page.goto(url, timeout=timeout)
    except (PlaywrightTimeout, Exception) as e:
        if "timeout" in str(e).lower() or "Timeout" in type(e).__name__:
            logger.warning("page.goto load 逾時，改用 domcontentloaded")
            page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        else:
            raise
