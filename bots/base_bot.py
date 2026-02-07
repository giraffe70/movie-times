"""爬蟲機器人共用基底類別"""
from __future__ import annotations

import logging

from playwright.sync_api import Browser, Page, Playwright

from utils.browser_utils import create_stealth_page

logger = logging.getLogger(__name__)


class BaseBot:
    """所有影城爬蟲機器人的共用基底類別。

    提供共用的瀏覽器頁面建立功能。
    """

    # 子類別應覆寫此屬性作為日誌標籤
    LABEL: str = "BaseBot"

    def _create_stealth_page(
        self, playwright_instance: Playwright
    ) -> tuple[Browser, Page]:
        """建立具有反偵測措施的瀏覽器頁面。

        委派給 utils.browser_utils.create_stealth_page 統一處理。
        """
        return create_stealth_page(playwright_instance, label=self.LABEL)
