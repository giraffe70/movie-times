"""秀泰影城爬蟲機器人

支援兩種資料取得方式：
- HTTP API（透過 curl_cffi / Cloudflare Worker 代理）
- Playwright 瀏覽器渲染 + React fiber 擷取
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime

from playwright.sync_api import sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright_stealth import Stealth

import config
from bots.base_bot import BaseBot
from utils.browser_utils import goto_safe
from utils.date_utils import format_date_with_weekday, parse_date_from_string
from utils.http_utils import showtime_api_get

logger = logging.getLogger(__name__)


# ====================================================================
# 秀泰 HTTP API 工具函式
# ====================================================================

def fetch_programs_via_http() -> dict[str, str]:
    """HTTP API：取得秀泰電影清單。

    Returns:
        {電影名稱: program_id}
    """
    movies: dict[str, str] = {}
    try:
        data = showtime_api_get(
            f"{config.SHOWTIME_API_BASE}/1/app/bootstrap?appVersion=2.9.200"
        )
        progs = data.get("payload", {}).get("programs", [])
        seen: set[str] = set()
        for prog in progs:
            name = prog.get("name", "")
            pid = prog.get("id")
            if name and pid and name not in seen:
                movies[name] = pid
                seen.add(name)
        logger.info("[秀泰] HTTP API 取得 %d 部電影", len(movies))
    except Exception as e:
        logger.error("[秀泰] HTTP API 電影清單失敗: %s", e)
    return movies


def fetch_cinemas_via_http(program_id: str) -> list[str]:
    """HTTP API：取得有此電影場次的秀泰影城列表。

    Args:
        program_id: 電影 ID

    Returns:
        [影城名稱, ...]
    """
    cinemas: list[str] = []
    try:
        today_str = date.today().isoformat()
        url = (
            f"{config.SHOWTIME_API_BASE}/1/events/listForProgram/"
            f"{program_id}?date={today_str}&forVista=false"
        )
        data = showtime_api_get(url)
        events = data.get("payload", {}).get("events", [])
        venue_ids = list(set(
            str(e.get("venueId", "")) for e in events if e.get("venueId")
        ))
        if venue_ids:
            ids_str = ",".join(venue_ids)
            vdata = showtime_api_get(
                f"{config.SHOWTIME_API_BASE}/1/venues/ids/{ids_str}"
            )
            for v in vdata.get("payload", {}).get("venues", []):
                name = v.get("name", "")
                if "秀泰影城" in name and name not in cinemas:
                    cinemas.append(name)
        logger.info("[秀泰] HTTP API 取得 %d 間影城", len(cinemas))
    except Exception as e:
        logger.error("[秀泰] HTTP API 影城列表失敗: %s", e)
    return cinemas


def fetch_events_via_http(program_id: str) -> list[dict]:
    """HTTP API：取得場次資料。

    Args:
        program_id: 電影 ID

    Returns:
        場次事件列表
    """
    try:
        today_str = date.today().isoformat()
        url = (
            f"{config.SHOWTIME_API_BASE}/1/events/listForProgram/"
            f"{program_id}?date={today_str}&forVista=false"
        )
        data = showtime_api_get(url)
        events = data.get("payload", {}).get("events", [])
        logger.info("[秀泰] HTTP API 取得 %d 筆場次", len(events))
        return events
    except Exception as e:
        logger.error("[秀泰] HTTP API 場次失敗: %s", e)
        return []


def fetch_venues_via_http(venue_ids: list) -> dict[str, dict[str, str]]:
    """HTTP API：取得影城詳細資訊。

    Args:
        venue_ids: 影城 ID 列表

    Returns:
        {venue_id: {"name": ..., "room": ...}}
    """
    venues: dict[str, dict[str, str]] = {}
    if not venue_ids:
        return venues
    try:
        ids_str = ",".join(str(vid) for vid in venue_ids)
        vdata = showtime_api_get(
            f"{config.SHOWTIME_API_BASE}/1/venues/ids/{ids_str}"
        )
        for v in vdata.get("payload", {}).get("venues", []):
            venues[v["id"]] = {
                "name": v.get("name", ""),
                "room": v.get("room", ""),
            }
        logger.info("[秀泰] HTTP API 取得 %d 間影城資訊", len(venues))
    except Exception as e:
        logger.error("[秀泰] HTTP API 影城資訊失敗: %s", e)
    return venues


def process_events(
    captured_events: list[dict],
    captured_venues: dict[str, dict[str, str]],
    selected_cinemas: list[str],
) -> dict[str, dict[str, list[str]]]:
    """將場次原始資料處理成最終顯示結果。

    Args:
        captured_events: API 回傳的場次列表
        captured_venues: {venue_id: {"name": ..., "room": ...}}
        selected_cinemas: 使用者選擇的影城名稱列表

    Returns:
        {影城名稱: {日期字串: [時間列表]}}
    """
    results: dict[str, dict[str, list[str]]] = {}

    def match_cinema(
        api_name: str, selected_list: list[str]
    ) -> str | None:
        for sel in selected_list:
            if sel in api_name or api_name in sel:
                return sel
        return None

    for event in captured_events:
        venue_id = event.get("venueId")
        venue_info = captured_venues.get(venue_id, {})
        cinema_name = venue_info.get("name", f"未知影城({venue_id})")

        matched = match_cinema(cinema_name, selected_cinemas)
        if matched is None:
            continue

        started_at = event.get("startedAt", "")
        if not started_at:
            continue

        dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        dt_local = dt.astimezone(config.TW_TZ)

        date_str = format_date_with_weekday(dt_local)
        time_str = dt_local.strftime("%H:%M")
        format_info = event.get("meta", {}).get("format", "")

        display_name = matched

        if display_name not in results:
            results[display_name] = {}
        if date_str not in results[display_name]:
            results[display_name][date_str] = []

        display = time_str
        if format_info:
            display = f"{time_str} [{format_info}]"
        results[display_name][date_str].append(display)

    # 排序日期與時間
    for cinema in results:
        sorted_dates = sorted(
            results[cinema].keys(),
            key=lambda d: parse_date_from_string(d) or date.max,
        )
        results[cinema] = {
            d: sorted(list(set(results[cinema][d])))
            for d in sorted_dates
        }

    total_dates = sum(len(dm) for dm in results.values())
    logger.info(
        "[秀泰] 處理完成，找到 %d 間影城、共 %d 天場次",
        len(results),
        total_dates,
    )
    return results


# ====================================================================
# 秀泰影城爬蟲機器人
# ====================================================================

class ShowtimeBot(BaseBot):
    """秀泰影城爬蟲機器人"""

    LABEL: str = "秀泰"

    # Cloudflare Turnstile 驗證頁面關鍵字
    _CF_KEYWORDS: list[str] = [
        "Just a moment",
        "Checking your browser",
        "Enable JavaScript",
        "Attention Required",
    ]

    def _wait_for_cloudflare(self, page, label: str = "") -> bool:
        """輪詢等待 Cloudflare Turnstile 挑戰自動通過。

        最多等待 35 秒（7 次 × 5 秒），若通過則提前結束。
        """
        page_text: str = page.evaluate(
            "() => (document.body "
            "? document.body.innerText.substring(0, 500) : '')"
        )
        if not any(kw in page_text for kw in self._CF_KEYWORDS):
            return True  # 沒有 Cloudflare 擋住

        logger.info("[秀泰]%s 偵測到 Cloudflare 驗證頁，等待挑戰自動解決...", label)
        for attempt in range(7):  # 最多等 35 秒
            # Cloudflare 驗證需要等待 JS 執行，time.sleep 是合理的輪詢方式
            time.sleep(5)
            check_text = page.evaluate(
                "() => (document.body "
                "? document.body.innerText.substring(0, 500) : '')"
            )
            if not any(kw in check_text for kw in self._CF_KEYWORDS):
                logger.info(
                    "[秀泰]%s Cloudflare 驗證已通過（等待了 %d 秒）",
                    label,
                    (attempt + 1) * 5,
                )
                # 通過後等待頁面渲染完成
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except PlaywrightTimeout:
                    pass
                return True
            logger.info(
                "[秀泰]%s 仍在等待 Cloudflare 驗證... (%d秒)",
                label,
                (attempt + 1) * 5,
            )

        logger.warning("[秀泰]%s Cloudflare 驗證未能在 35 秒內通過", label)
        return False

    def get_movies_and_cinemas(
        self,
    ) -> tuple[dict[str, str], list[str]]:
        """取得秀泰電影清單與影城清單。

        - 雲端：使用 HTTP API（透過 Cloudflare Worker 代理）
        - 本機：使用 Playwright 瀏覽器 + React fiber 擷取，失敗時 HTTP API 備援

        Returns:
            (movies, cinemas)
            - movies: {電影名稱: program_id}
            - cinemas: [影城名稱, ...]
        """
        movies: dict[str, str] = {}
        cinemas: list[str] = []

        if config.IS_CLOUD:
            # === 雲端：只走 HTTP API ===
            logger.info("[秀泰] 雲端環境，使用 HTTP API...")
            movies = fetch_programs_via_http()
            if movies:
                first_id = list(movies.values())[0]
                cinemas = fetch_cinemas_via_http(first_id)
            if not movies:
                logger.warning("[秀泰] HTTP API 無法取得電影清單")
            elif not cinemas:
                logger.warning("[秀泰] HTTP API 無法取得影城清單")
            return movies, cinemas

        # === 本機：Playwright 瀏覽器 + React fiber ===
        with Stealth().use_sync(sync_playwright()) as p:
            browser, page = self._create_stealth_page(p)
            try:
                logger.info("[秀泰] 正在讀取電影清單 (瀏覽器)...")
                goto_safe(page, config.SHOWTIME_PROGRAMS_URL)

                # 等待 React 渲染電影卡片
                try:
                    page.locator("text=線上訂票").first.wait_for(timeout=15000)
                except PlaywrightTimeout:
                    logger.warning("[秀泰] 等待電影卡片渲染超時，繼續嘗試擷取")

                # 從 React fiber 擷取電影資料
                raw_movies = page.evaluate("""
                    () => {
                        const results = [];
                        const seen = new Set();
                        const bookingBtns = Array.from(
                            document.querySelectorAll('div')
                        ).filter(
                            el => el.textContent.trim() === '線上訂票' &&
                                  el.className &&
                                  typeof el.className === 'string' &&
                                  el.className.includes('sc-')
                        );

                        for (const btn of bookingBtns) {
                            const fiberKey = Object.keys(btn).find(
                                k => k.startsWith('__reactFiber') ||
                                     k.startsWith('__reactInternalInstance')
                            );
                            if (!fiberKey) continue;

                            let fiber = btn[fiberKey];
                            for (let i = 0; i < 25 && fiber; i++) {
                                if (fiber.memoizedProps &&
                                    fiber.memoizedProps.program) {
                                    const prog = fiber.memoizedProps.program;
                                    const key = prog.id + '_' + prog.name;
                                    if (!seen.has(key)) {
                                        seen.add(key);
                                        results.push({
                                            id: prog.id,
                                            name: prog.name || '',
                                            type: prog.type || '',
                                            rating: prog.rating || ''
                                        });
                                    }
                                    break;
                                }
                                fiber = fiber.return;
                            }
                        }
                        return results;
                    }
                """)

                seen_names: set[str] = set()
                for movie in raw_movies:
                    name = movie.get("name", "")
                    pid = movie.get("id")
                    if name and pid and name not in seen_names:
                        movies[name] = pid
                        seen_names.add(name)

                logger.info("[秀泰] 瀏覽器方式取得 %d 部電影", len(movies))

                # 取得影城列表
                if movies:
                    first_id = list(movies.values())[0]
                    goto_safe(
                        page,
                        config.SHOWTIME_BOOKING_URL_TEMPLATE.format(first_id),
                    )

                    # 等待影城按鈕出現
                    try:
                        page.locator(
                            "button:has-text('秀泰影城')"
                        ).first.wait_for(timeout=10000)
                    except PlaywrightTimeout:
                        logger.warning("[秀泰] 等待影城按鈕超時")

                    raw_cinemas: list[str] = page.evaluate("""
                        () => {
                            return Array.from(
                                document.querySelectorAll('button')
                            )
                            .filter(btn => {
                                const text = btn.textContent.trim();
                                return text.includes('秀泰影城') &&
                                       text.length < 20 &&
                                       !text.includes('登入');
                            })
                            .map(btn => btn.textContent.trim());
                        }
                    """)
                    cinemas = raw_cinemas
                    logger.info("[秀泰] 取得 %d 間影城", len(cinemas))

            except Exception as e:
                logger.error(
                    "ShowtimeBot.get_movies_and_cinemas (browser) 失敗: %s", e
                )
            finally:
                browser.close()

        # 本機瀏覽器失敗時，用 HTTP API 備援
        if not movies:
            logger.info("[秀泰] 瀏覽器方式失敗，嘗試 HTTP API 備援...")
            movies = fetch_programs_via_http()
            if movies:
                first_id = list(movies.values())[0]
                cinemas = fetch_cinemas_via_http(first_id)

        return movies, cinemas

    def get_movie_times(
        self,
        program_id: str,
        selected_cinemas: list[str],
    ) -> dict[str, dict[str, list[str]]]:
        """查詢指定電影在選定影城的場次。

        Args:
            program_id: 電影 ID
            selected_cinemas: 使用者選擇的影城名稱列表

        Returns:
            {影城名稱: {日期字串: [時間列表]}}
        """
        if config.IS_CLOUD:
            # === 雲端：只走 HTTP API ===
            logger.info(
                "[秀泰] 雲端環境，使用 HTTP API 查詢 programId=%s", program_id
            )
            events = fetch_events_via_http(program_id)
            if events:
                venue_ids = list(set(
                    e.get("venueId") for e in events if e.get("venueId")
                ))
                venues = fetch_venues_via_http(venue_ids)
                return process_events(events, venues, selected_cinemas)
            logger.warning("[秀泰] HTTP API 無法取得場次資料")
            return {}

        # === 本機：Playwright 瀏覽器 ===
        results: dict[str, dict[str, list[str]]] = {}
        captured_events: list[dict] = []
        captured_venues: dict[str, dict[str, str]] = {}

        with Stealth().use_sync(sync_playwright()) as p:
            logger.info("[秀泰] 啟動爬蟲，查詢 programId=%s", program_id)
            browser, page = self._create_stealth_page(p)

            try:
                def on_response(response) -> None:
                    try:
                        url = response.url
                        if "events/listForProgram" in url:
                            data = response.json()
                            evts = (
                                data.get("payload", {}).get("events", [])
                            )
                            captured_events.extend(evts)
                        elif (
                            "/venues/ids/" in url
                            and "/assets/" not in url
                        ):
                            data = response.json()
                            for v in (
                                data.get("payload", {}).get("venues", [])
                            ):
                                captured_venues[v["id"]] = {
                                    "name": v.get("name", ""),
                                    "room": v.get("room", ""),
                                }
                    except Exception:
                        pass

                page.on("response", on_response)

                goto_safe(
                    page,
                    config.SHOWTIME_BOOKING_URL_TEMPLATE.format(program_id),
                )

                # 等待頁面按鈕出現
                try:
                    page.locator("button").first.wait_for(timeout=10000)
                except PlaywrightTimeout:
                    logger.warning("[秀泰] 等待頁面渲染超時")

                target_cinema = selected_cinemas[0]
                cinema_btn = page.locator(
                    f"button:has-text('{target_cinema}')"
                )
                if cinema_btn.count() > 0:
                    cinema_btn.first.click()
                    logger.info("[秀泰] 已點選 %s", target_cinema)
                    # 等待場次資料載入
                    try:
                        page.wait_for_load_state(
                            "networkidle", timeout=8000
                        )
                    except PlaywrightTimeout:
                        pass
                else:
                    logger.warning("[秀泰] 找不到 %s 按鈕", target_cinema)

                # 攔截未取得資料時，嘗試在瀏覽器內呼叫 API
                if not captured_events:
                    logger.info(
                        "[秀泰] 攔截未取得資料，嘗試瀏覽器內 API 呼叫..."
                    )
                    today_str = date.today().isoformat()
                    try:
                        events_data = page.evaluate(
                            """async (args) => {
                                const controller = new AbortController();
                                const tid = setTimeout(
                                    () => controller.abort(), 15000
                                );
                                try {
                                    const resp = await fetch(
                                        'https://capi.showtimes.com.tw'
                                        + '/1/events/listForProgram/'
                                        + args.pid + '?date=' + args.today
                                        + '&forVista=false',
                                        { signal: controller.signal }
                                    );
                                    clearTimeout(tid);
                                    return await resp.json();
                                } catch(e) {
                                    clearTimeout(tid);
                                    return {error: e.toString()};
                                }
                            }""",
                            {"pid": str(program_id), "today": today_str},
                        )
                        if (
                            isinstance(events_data, dict)
                            and "error" not in events_data
                        ):
                            captured_events = (
                                events_data.get("payload", {})
                                .get("events", [])
                            )
                        else:
                            err = (
                                events_data.get("error", "unknown")
                                if isinstance(events_data, dict)
                                else str(events_data)
                            )
                            logger.warning("[秀泰] 瀏覽器 API 呼叫失敗: %s", err)
                    except Exception as e:
                        logger.warning("[秀泰] 瀏覽器 API 例外: %s", e)

                # 瀏覽器備援：用 HTTP API 取得場次
                if not captured_events:
                    logger.info("[秀泰] 嘗試 HTTP API 取得場次...")
                    captured_events = fetch_events_via_http(program_id)

                if not captured_events:
                    logger.info("[秀泰] 此電影目前無場次資料")
                    browser.close()
                    return {}

                logger.info("[秀泰] 取得 %d 筆場次", len(captured_events))

                # 補齊缺少的影城資訊
                event_venue_ids = set(
                    e["venueId"] for e in captured_events
                )
                missing_ids = event_venue_ids - set(captured_venues.keys())

                if missing_ids:
                    http_venues = fetch_venues_via_http(list(missing_ids))
                    captured_venues.update(http_venues)

                results = process_events(
                    captured_events, captured_venues, selected_cinemas
                )

            except Exception as e:
                logger.error("ShowtimeBot.get_movie_times 失敗: %s", e)
            finally:
                browser.close()

        return results
