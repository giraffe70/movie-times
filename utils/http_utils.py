"""HTTP 請求工具函式

提供秀泰影城 API 呼叫功能，支援：
- 本機：直接呼叫 + curl_cffi Chrome TLS 模擬
- 雲端：透過 Cloudflare Worker 代理（繞過 IP 封鎖）
"""
from __future__ import annotations

import logging

from curl_cffi import requests as cffi_requests

import config

logger = logging.getLogger(__name__)


def showtime_api_get(url: str) -> dict:
    """呼叫秀泰 API，根據環境自動選擇直連或代理方式。

    Args:
        url: 目標 API URL

    Returns:
        API 回應的 JSON dict

    Raises:
        requests.HTTPError: HTTP 狀態碼非 2xx
    """
    if config.IS_CLOUD and config.SHOWTIME_WORKER_URL:
        # 透過 Cloudflare Worker 代理
        logger.info("[秀泰] 透過 Worker 代理: %s", url)
        headers: dict[str, str] = {}
        if config.SHOWTIME_WORKER_SECRET:
            headers["X-Worker-Auth"] = config.SHOWTIME_WORKER_SECRET
        resp = cffi_requests.get(
            config.SHOWTIME_WORKER_URL,
            params={"target": url},
            headers=headers,
            timeout=20,
        )
    else:
        # 本機直接呼叫
        resp = cffi_requests.get(
            url,
            headers=config.SHOWTIME_API_HEADERS,
            impersonate="chrome131",
            timeout=15,
        )
    resp.raise_for_status()
    return resp.json()
