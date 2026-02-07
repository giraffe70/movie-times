import streamlit as st
import asyncio
import sys
import re
import time
import json
from curl_cffi import requests as cffi_requests
from datetime import date, datetime, timedelta, timezone
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# --- 自動安裝 Playwright 瀏覽器 (針對雲端環境) ---
import os
import subprocess

IS_CLOUD = not sys.platform.startswith("win")

def install_playwright_browser():
    try:
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        print(">>> Playwright chromium installed successfully.")
    except Exception as e:
        print(f">>> Error installing Playwright browser: {e}")

if IS_CLOUD:
    install_playwright_browser()
    # 啟動 Xvfb 虛擬顯示器（備用，供 headless=False 模式使用）
    if not os.environ.get("DISPLAY"):
        try:
            subprocess.Popen(
                ["/usr/bin/Xvfb", ":99", "-screen", "0", "1920x1080x24", "-nolisten", "tcp"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            os.environ["DISPLAY"] = ":99"
            time.sleep(1)
            print(">>> Xvfb virtual display started on :99")
        except Exception as e:
            print(f">>> Warning: Failed to start Xvfb: {e}")

# --- 1. 系統環境修正 (必須放在最上面) ---
if not IS_CLOUD:
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# --- 2. 設定頁面 ---
st.set_page_config(page_title="電影時刻表查詢", page_icon="🎬")

# --- 3. 共用工具函式 ---
WEEKDAY_NAMES = ["一", "二", "三", "四", "五", "六", "日"]
TW_TZ = timezone(timedelta(hours=8))


def format_date_with_weekday(dt_obj):
    """將 datetime 格式化為 '2月6日(五)'"""
    wd = WEEKDAY_NAMES[dt_obj.weekday()]
    return f"{dt_obj.month}月{dt_obj.day}日({wd})"


def parse_date_from_string(date_str):
    """
    將爬取到的日期字串（如 '2月6日(五)'、'02月06日(四)'）解析為 date 物件。
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


def filter_by_date(times_map, date_mode, date_value):
    """
    根據日期篩選條件過濾場次資料。

    Args:
        times_map: {日期字串: [時間列表]}
        date_mode: "all" / "single" / "range"
        date_value: None / date / (start_date, end_date)
    Returns:
        過濾後的 {日期字串: [時間列表]}
    """
    if date_mode == "all":
        return times_map

    filtered = {}
    for date_str, times in times_map.items():
        parsed = parse_date_from_string(date_str)
        if parsed is None:
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


# ====================================================================
# 4A. 威秀影城爬蟲機器人
# ====================================================================
class VieshowBot:
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )

    def __init__(self):
        self.url = "https://www.vscinemas.com.tw/ShowTimes/"

    def _create_stealth_page(self, playwright_instance):
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ]
        browser = None

        # 1. 優先使用 MS Edge headless（Windows 本地環境有 Edge）
        try:
            browser = playwright_instance.chromium.launch(
                channel="msedge", headless=True, args=launch_args,
            )
            print(">>> [威秀] 使用 Edge headless 模式")
        except Exception as e:
            print(f">>> [威秀] Edge 不可用 ({e})，改用隱藏視窗模式")

        # 2. 備用：headless=False 隱藏視窗模式（Windows 靠螢幕外座標，雲端靠 Xvfb）
        #    headless=False 是完整 GUI 瀏覽器，不會被反爬蟲偵測
        if browser is None:
            browser = playwright_instance.chromium.launch(
                headless=False,
                args=launch_args + [
                    "--window-position=-32000,-32000",
                    "--window-size=1,1",
                ],
            )
            print(">>> [威秀] 使用隱藏視窗模式")

        # playwright-stealth 已自動注入反偵測腳本，不需手動 add_init_script
        page = browser.new_page(
            user_agent=self.USER_AGENT,
            viewport={"width": 1920, "height": 1080},
            locale="zh-TW",
        )
        return browser, page

    def get_cinemas_and_movies(self):
        cinema_options = {}
        movie_list = []

        with Stealth().use_sync(sync_playwright()) as p:
            browser, page = self._create_stealth_page(p)
            try:
                page.goto(self.url, timeout=60000)
                selector = "#CinemaNameTWInfoF"
                page.wait_for_selector(selector)

                options = page.locator(f"{selector} option").all()
                for option in options:
                    text = option.text_content()
                    value = option.get_attribute("value")
                    if value and text and "請選擇" not in text:
                        cinema_options[text.strip()] = value

                if cinema_options:
                    first_value = list(cinema_options.values())[0]
                    page.select_option(selector, value=first_value)
                    time.sleep(1)
                    page.evaluate(f"""
                        var select = document.querySelector('{selector}');
                        select.dispatchEvent(new Event('change', {{bubbles: true}}));
                    """)

                    try:
                        page.wait_for_function("""
                            () => {
                                if (document.querySelector('.MovieName')) return true;
                                if (document.body.innerText.includes('查無資料')) return true;
                                return false;
                            }
                        """, timeout=15000)
                        time.sleep(2)
                    except:
                        print("[警告] 等待電影清單超時...")

                    content = page.content()
                    soup = BeautifulSoup(content, "html.parser")
                    movie_tags = soup.select("strong.MovieName.LangTW")
                    seen = set()
                    for tag in movie_tags:
                        name = tag.get_text(strip=True)
                        if name and name not in seen:
                            movie_list.append(name)
                            seen.add(name)

                print(f">>> [威秀] 取得 {len(cinema_options)} 間影城、{len(movie_list)} 部電影。")

            except Exception as e:
                print(f"[Error] get_cinemas_and_movies: {e}")
            finally:
                browser.close()

        return cinema_options, movie_list

    def get_movie_times_for_cinemas(self, cinema_dict, target_movie):
        results = {}

        with Stealth().use_sync(sync_playwright()) as p:
            print(f">>> [威秀] 啟動爬蟲，查詢《{target_movie}》於 {len(cinema_dict)} 間影城")
            browser, page = self._create_stealth_page(p)

            try:
                for cinema_name, cinema_value in cinema_dict.items():
                    print(f">>> [威秀] 正在查詢：{cinema_name} ...")
                    page.goto(self.url, timeout=60000)

                    target_select_id = "#CinemaNameTWInfoF"
                    page.wait_for_selector(target_select_id)

                    page.select_option(target_select_id, value=cinema_value)
                    time.sleep(1)
                    page.evaluate(f"""
                        var select = document.querySelector('{target_select_id}');
                        select.dispatchEvent(new Event('change', {{bubbles: true}}));
                    """)

                    try:
                        page.wait_for_function("""
                            () => {
                                if (document.querySelector('.MovieName')) return true;
                                if (document.body.innerText.includes('查無資料')) return true;
                                if (document.body.innerText.includes('目前無場次')) return true;
                                return false;
                            }
                        """, timeout=15000)
                        time.sleep(2)
                    except:
                        print(f"[警告] {cinema_name} 等待超時...")

                    content = page.content()
                    soup = BeautifulSoup(content, "html.parser")

                    if "查無資料" in soup.get_text() or "目前無場次" in soup.get_text():
                        results[cinema_name] = {}
                        continue

                    movie_tags = soup.select("strong.MovieName.LangTW")
                    date_times = {}

                    for movie_tag in movie_tags:
                        movie_name = movie_tag.get_text(strip=True)
                        if movie_name != target_movie:
                            continue

                        parent_div = movie_tag.find_parent("div", class_="col-xs-12")
                        if not parent_div:
                            continue

                        date_tags = parent_div.select("strong.RealShowDate.LangTW")

                        for date_tag in date_tags:
                            date_str = date_tag.get_text(strip=True)
                            times_list = []
                            next_elem = date_tag.find_next_sibling()

                            while next_elem:
                                classes = next_elem.get("class", [])

                                if "SessionTimeInfo" in classes:
                                    block_text = next_elem.get_text()
                                    found_times = re.findall(r"\d{1,2}:\d{2}", block_text)
                                    if found_times:
                                        times_list.extend(found_times)
                                    break

                                if "RealShowDate" in classes and "LangTW" in classes:
                                    break

                                next_elem = next_elem.find_next_sibling()

                            if times_list:
                                clean_date = date_str.replace("場次", "").strip()
                                unique_times = sorted(list(set(times_list)))
                                date_times[clean_date] = unique_times

                    results[cinema_name] = date_times
                    print(f">>> [威秀] {cinema_name} 完成，找到 {len(date_times)} 天場次。")

            except Exception as e:
                print(f"[Error] get_movie_times_for_cinemas: {e}")
            finally:
                browser.close()

        return results


# ====================================================================
# 4B. 秀泰影城爬蟲機器人
# ====================================================================

# --- 秀泰 HTTP API 工具函式 (使用 curl_cffi 模擬 Chrome TLS 指紋) ---

_SHOWTIME_API_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": "https://www.showtimes.com.tw",
    "Referer": "https://www.showtimes.com.tw/",
}


def _showtime_api_get(url):
    """用 curl_cffi 發送 GET，模擬 Chrome 131 TLS 指紋以繞過 Cloudflare。"""
    resp = cffi_requests.get(
        url,
        headers=_SHOWTIME_API_HEADERS,
        impersonate="chrome131",
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _fetch_showtime_programs_via_http():
    """HTTP API: 取得秀泰電影清單"""
    movies = {}
    try:
        data = _showtime_api_get("https://capi.showtimes.com.tw/1/programs")
        progs = data.get("payload", {}).get("programs", [])
        seen = set()
        for prog in progs:
            name = prog.get("name", "")
            pid = prog.get("id")
            if name and pid and name not in seen:
                movies[name] = pid
                seen.add(name)
        print(f">>> [秀泰] HTTP API (curl_cffi) 取得 {len(movies)} 部電影")
    except Exception as e:
        print(f">>> [秀泰] HTTP API 電影清單失敗: {e}")
    return movies


def _fetch_showtime_cinemas_via_http(program_id):
    """HTTP API: 取得有此電影場次的秀泰影城列表"""
    cinemas = []
    try:
        today_str = date.today().isoformat()
        url = (
            f"https://capi.showtimes.com.tw/1/events/listForProgram/"
            f"{program_id}?date={today_str}&forVista=false"
        )
        data = _showtime_api_get(url)
        events = data.get("payload", {}).get("events", [])
        venue_ids = list(set(
            str(e.get("venueId", "")) for e in events if e.get("venueId")
        ))
        if venue_ids:
            ids_str = ",".join(venue_ids)
            vdata = _showtime_api_get(
                f"https://capi.showtimes.com.tw/1/venues/ids/{ids_str}"
            )
            for v in vdata.get("payload", {}).get("venues", []):
                name = v.get("name", "")
                if "秀泰影城" in name and name not in cinemas:
                    cinemas.append(name)
        print(f">>> [秀泰] HTTP API (curl_cffi) 取得 {len(cinemas)} 間影城")
    except Exception as e:
        print(f">>> [秀泰] HTTP API 影城列表失敗: {e}")
    return cinemas


def _fetch_showtime_events_via_http(program_id):
    """HTTP API: 取得場次資料"""
    try:
        today_str = date.today().isoformat()
        url = (
            f"https://capi.showtimes.com.tw/1/events/listForProgram/"
            f"{program_id}?date={today_str}&forVista=false"
        )
        data = _showtime_api_get(url)
        events = data.get("payload", {}).get("events", [])
        print(f">>> [秀泰] HTTP API (curl_cffi) 取得 {len(events)} 筆場次")
        return events
    except Exception as e:
        print(f">>> [秀泰] HTTP API 場次失敗: {e}")
        return []


def _fetch_showtime_venues_via_http(venue_ids):
    """HTTP API: 取得影城詳細資訊"""
    venues = {}
    if not venue_ids:
        return venues
    try:
        ids_str = ",".join(str(vid) for vid in venue_ids)
        vdata = _showtime_api_get(
            f"https://capi.showtimes.com.tw/1/venues/ids/{ids_str}"
        )
        for v in vdata.get("payload", {}).get("venues", []):
            venues[v["id"]] = {
                "name": v.get("name", ""),
                "room": v.get("room", ""),
            }
        print(f">>> [秀泰] HTTP API (curl_cffi) 取得 {len(venues)} 間影城資訊")
    except Exception as e:
        print(f">>> [秀泰] HTTP API 影城資訊失敗: {e}")
    return venues


def _process_showtime_events(captured_events, captured_venues, selected_cinemas):
    """
    將場次原始資料處理成最終顯示結果。
    (從 ShowtimeBot.get_movie_times 提取出來的共用邏輯)
    """
    results = {}

    def match_cinema(api_name, selected_list):
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
        dt_local = dt.astimezone(TW_TZ)

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
    print(
        f">>> [秀泰] 處理完成，"
        f"找到 {len(results)} 間影城、共 {total_dates} 天場次。"
    )
    return results


class ShowtimeBot:
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )

    PROGRAMS_URL = "https://www.showtimes.com.tw/programs"
    BOOKING_URL_TEMPLATE = "https://www.showtimes.com.tw/ticketing/forProgram/{}"

    def _create_stealth_page(self, playwright_instance):
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ]
        browser = None

        # 1. Windows: 優先使用 Edge headless
        if not IS_CLOUD:
            try:
                browser = playwright_instance.chromium.launch(
                    channel="msedge", headless=True, args=launch_args,
                )
                print(">>> [秀泰] 使用 Edge headless 模式")
            except Exception as e:
                print(f">>> [秀泰] Edge 不可用 ({e})")

        # 2. 雲端: 使用 headless=False + Xvfb（與威秀相同策略）
        #    完整 GUI 瀏覽器更不容易被 Cloudflare Turnstile 偵測
        if browser is None and IS_CLOUD:
            try:
                browser = playwright_instance.chromium.launch(
                    headless=False,
                    args=launch_args + [
                        "--window-position=-32000,-32000",
                        "--window-size=1,1",
                    ],
                )
                print(">>> [秀泰] 使用隱藏視窗模式 (雲端 Xvfb)")
            except Exception as e:
                print(f">>> [秀泰] 雲端隱藏視窗模式失敗: {e}")

        # 3. 備用：headless=False 隱藏視窗模式（本機 fallback）
        if browser is None:
            browser = playwright_instance.chromium.launch(
                headless=False,
                args=launch_args + [
                    "--window-position=-32000,-32000",
                    "--window-size=1,1",
                ],
            )
            print(">>> [秀泰] 使用隱藏視窗模式 (fallback)")

        # playwright-stealth 已自動注入反偵測腳本，不需手動 add_init_script
        page = browser.new_page(
            user_agent=self.USER_AGENT,
            viewport={"width": 1920, "height": 1080},
            locale="zh-TW",
        )
        return browser, page

    def _goto_safe(self, page, url, timeout=60000):
        """
        安全導航：先嘗試預設 wait_until="load"，
        若逾時（SPA 不會完成 load），改用 "domcontentloaded"。
        """
        try:
            page.goto(url, timeout=timeout)
            return
        except Exception as e:
            if "timeout" in str(e).lower() or "Timeout" in str(type(e).__name__):
                print(f">>> [秀泰] page.goto load 逾時，改用 domcontentloaded...")
                page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            else:
                raise

    def _wait_for_cloudflare(self, page, label=""):
        """
        輪詢等待 Cloudflare Turnstile 挑戰自動通過。
        最多等待 35 秒（7 次 × 5 秒），若通過則提前結束。
        """
        CF_KEYWORDS = [
            "Just a moment", "Checking your browser",
            "Enable JavaScript", "Attention Required",
        ]
        page_text = page.evaluate(
            "() => (document.body ? document.body.innerText.substring(0, 500) : '')"
        )
        if not any(kw in page_text for kw in CF_KEYWORDS):
            return True  # 沒有 Cloudflare 擋住

        print(f">>> [秀泰]{label} 偵測到 Cloudflare 驗證頁，等待挑戰自動解決...")
        for attempt in range(7):  # 最多等 35 秒 (7 x 5秒)
            time.sleep(5)
            check_text = page.evaluate(
                "() => (document.body ? document.body.innerText.substring(0, 500) : '')"
            )
            if not any(kw in check_text for kw in CF_KEYWORDS):
                print(f">>> [秀泰]{label} Cloudflare 驗證已通過（等待了 {(attempt+1)*5} 秒）")
                time.sleep(3)  # 通過後再多等一下讓頁面渲染
                return True
            print(f">>> [秀泰]{label} 仍在等待 Cloudflare 驗證... ({(attempt+1)*5}秒)")

        print(f">>> [秀泰]{label} Cloudflare 驗證未能在 35 秒內通過")
        return False

    def get_movies_and_cinemas(self):
        movies = {}
        cinemas = []

        # ============================================================
        # 雲端：優先使用 curl_cffi HTTP API（繞過 Cloudflare TLS 偵測）
        # ============================================================
        if IS_CLOUD:
            print(">>> [秀泰] 雲端環境，優先使用 HTTP API (curl_cffi)...")
            movies = _fetch_showtime_programs_via_http()
            if movies:
                first_id = list(movies.values())[0]
                cinemas = _fetch_showtime_cinemas_via_http(first_id)
            if movies and cinemas:
                return movies, cinemas
            print(">>> [秀泰] HTTP API 未取得完整資料，嘗試瀏覽器方式...")
            movies = {}
            cinemas = []

        # ============================================================
        # 本機 或 雲端 HTTP 失敗：瀏覽器渲染 + React fiber 擷取
        # ============================================================
        with Stealth().use_sync(sync_playwright()) as p:
            browser, page = self._create_stealth_page(p)
            try:
                print(">>> [秀泰] 正在讀取電影清單 (瀏覽器)...")
                self._goto_safe(page, self.PROGRAMS_URL)
                time.sleep(8 if not IS_CLOUD else 15)

                # 檢查頁面是否被 Cloudflare 擋住，輪詢等待最多 35 秒
                self._wait_for_cloudflare(page, " (電影清單)")

                # 從 React fiber 擷取電影資料
                raw_movies = page.evaluate("""
                    () => {
                        const results = [];
                        const seen = new Set();
                        const bookingBtns = Array.from(document.querySelectorAll('div')).filter(
                            el => el.textContent.trim() === '線上訂票' &&
                                  el.className && typeof el.className === 'string' &&
                                  el.className.includes('sc-')
                        );

                        for (const btn of bookingBtns) {
                            const fiberKey = Object.keys(btn).find(
                                k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance')
                            );
                            if (!fiberKey) continue;

                            let fiber = btn[fiberKey];
                            for (let i = 0; i < 25 && fiber; i++) {
                                if (fiber.memoizedProps && fiber.memoizedProps.program) {
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

                seen_names = set()
                for movie in raw_movies:
                    name = movie.get("name", "")
                    pid = movie.get("id")
                    if name and pid and name not in seen_names:
                        movies[name] = pid
                        seen_names.add(name)

                print(f">>> [秀泰] 瀏覽器方式取得 {len(movies)} 部電影")

                # 取得影城列表
                if movies:
                    first_id = list(movies.values())[0]
                    self._goto_safe(page, self.BOOKING_URL_TEMPLATE.format(first_id))
                    time.sleep(5 if not IS_CLOUD else 8)

                    raw_cinemas = page.evaluate("""
                        () => {
                            return Array.from(document.querySelectorAll('button'))
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
                    print(f">>> [秀泰] 取得 {len(cinemas)} 間影城")

            except Exception as e:
                print(f"[Error] ShowtimeBot.get_movies_and_cinemas (browser): {e}")
            finally:
                browser.close()

        # ============================================================
        # 最終備援：瀏覽器也失敗時嘗試 curl_cffi HTTP API
        # ============================================================
        if not movies:
            print(">>> [秀泰] 瀏覽器方式失敗，嘗試 HTTP API 備援...")
            movies = _fetch_showtime_programs_via_http()
            if movies:
                first_id = list(movies.values())[0]
                cinemas = _fetch_showtime_cinemas_via_http(first_id)

        return movies, cinemas

    def get_movie_times(self, program_id, selected_cinemas):
        # ============================================================
        # 雲端：優先使用 curl_cffi HTTP API（快速、繞過 Cloudflare）
        # ============================================================
        if IS_CLOUD:
            print(f">>> [秀泰] 雲端環境，使用 HTTP API 查詢 programId={program_id}")
            events = _fetch_showtime_events_via_http(program_id)
            if events:
                venue_ids = list(set(
                    e.get("venueId") for e in events if e.get("venueId")
                ))
                venues = _fetch_showtime_venues_via_http(venue_ids)
                results = _process_showtime_events(
                    events, venues, selected_cinemas
                )
                if results:
                    return results
            print(">>> [秀泰] HTTP API 未取得有效場次，嘗試瀏覽器方式...")

        # ============================================================
        # 本機 或 雲端 HTTP 失敗：使用瀏覽器
        # ============================================================
        results = {}
        captured_events = []
        captured_venues = {}

        with Stealth().use_sync(sync_playwright()) as p:
            print(f">>> [秀泰] 啟動爬蟲，查詢 programId={program_id}")
            browser, page = self._create_stealth_page(p)

            try:
                def on_response(response):
                    try:
                        url = response.url
                        if "events/listForProgram" in url:
                            data = response.json()
                            evts = data.get("payload", {}).get("events", [])
                            captured_events.extend(evts)
                        elif "/venues/ids/" in url and "/assets/" not in url:
                            data = response.json()
                            for v in data.get("payload", {}).get("venues", []):
                                captured_venues[v["id"]] = {
                                    "name": v.get("name", ""),
                                    "room": v.get("room", ""),
                                }
                    except Exception:
                        pass

                page.on("response", on_response)

                self._goto_safe(page, self.BOOKING_URL_TEMPLATE.format(program_id))
                time.sleep(3 if not IS_CLOUD else 6)

                # 等待 Cloudflare 驗證通過
                self._wait_for_cloudflare(page, " (場次查詢)")

                target_cinema = selected_cinemas[0]
                cinema_btn = page.locator(f"button:has-text('{target_cinema}')")
                if cinema_btn.count() > 0:
                    cinema_btn.first.click()
                    print(f">>> [秀泰] 已點選 {target_cinema}")
                    time.sleep(5 if not IS_CLOUD else 8)
                else:
                    print(f">>> [秀泰] 找不到 {target_cinema} 按鈕")

                # 攔截未取得資料時，嘗試在瀏覽器內呼叫 API
                if not captured_events:
                    print(">>> [秀泰] 攔截未取得資料，嘗試瀏覽器內 API 呼叫...")
                    today_str = date.today().isoformat()
                    try:
                        events_data = page.evaluate(
                            """async (args) => {
                                const controller = new AbortController();
                                const tid = setTimeout(() => controller.abort(), 15000);
                                try {
                                    const resp = await fetch(
                                        'https://capi.showtimes.com.tw/1/events/listForProgram/'
                                        + args.pid + '?date=' + args.today + '&forVista=false',
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
                        if isinstance(events_data, dict) and "error" not in events_data:
                            captured_events = (
                                events_data.get("payload", {}).get("events", [])
                            )
                        else:
                            err = events_data.get("error", "unknown") if isinstance(events_data, dict) else str(events_data)
                            print(f">>> [秀泰] 瀏覽器 API 呼叫失敗: {err}")
                    except Exception as e:
                        print(f">>> [秀泰] 瀏覽器 API 例外: {e}")

                # 備援：用 curl_cffi HTTP API
                if not captured_events:
                    print(">>> [秀泰] 嘗試 curl_cffi HTTP API 取得場次...")
                    captured_events = _fetch_showtime_events_via_http(program_id)

                if not captured_events:
                    print(">>> [秀泰] 此電影目前無場次資料")
                    browser.close()
                    return {}

                print(f">>> [秀泰] 取得 {len(captured_events)} 筆場次")

                # 補齊缺少的影城資訊
                event_venue_ids = set(e["venueId"] for e in captured_events)
                missing_ids = event_venue_ids - set(captured_venues.keys())

                if missing_ids:
                    ids_str = ",".join(str(vid) for vid in missing_ids)
                    print(f">>> [秀泰] 取得 {len(missing_ids)} 間影城的名稱資訊...")
                    # 先嘗試瀏覽器內 fetch
                    try:
                        extra = page.evaluate(
                            """async (idsStr) => {
                                const controller = new AbortController();
                                const tid = setTimeout(() => controller.abort(), 10000);
                                try {
                                    const resp = await fetch(
                                        'https://capi.showtimes.com.tw/1/venues/ids/' + idsStr,
                                        { signal: controller.signal }
                                    );
                                    clearTimeout(tid);
                                    return await resp.json();
                                } catch(e) {
                                    clearTimeout(tid);
                                    return {error: e.toString()};
                                }
                            }""",
                            ids_str,
                        )
                        if isinstance(extra, dict) and "error" not in extra:
                            for v in extra.get("payload", {}).get("venues", []):
                                captured_venues[v["id"]] = {
                                    "name": v.get("name", ""),
                                    "room": v.get("room", ""),
                                }
                    except Exception:
                        pass

                    # curl_cffi HTTP 備援
                    still_missing = event_venue_ids - set(captured_venues.keys())
                    if still_missing:
                        http_venues = _fetch_showtime_venues_via_http(
                            list(still_missing)
                        )
                        captured_venues.update(http_venues)

                # 使用共用邏輯處理場次資料
                results = _process_showtime_events(
                    captured_events, captured_venues, selected_cinemas
                )

            except Exception as e:
                print(f"[Error] ShowtimeBot.get_movie_times: {e}")
            finally:
                browser.close()

        return results


# ====================================================================
# 5. 快取層
# ====================================================================

# --- 威秀 ---
@st.cache_data(show_spinner=False)
def cached_vieshow_get_cinemas_and_movies():
    bot = VieshowBot()
    return bot.get_cinemas_and_movies()


@st.cache_data(show_spinner=False)
def cached_vieshow_get_movie_times(cinema_json, target_movie):
    cinema_dict = json.loads(cinema_json)
    bot = VieshowBot()
    return bot.get_movie_times_for_cinemas(cinema_dict, target_movie)


# --- 秀泰 ---
@st.cache_data(show_spinner=False, ttl=3600)  # 快取 1 小時，避免快取失敗結果
def cached_showtime_get_movies_and_cinemas():
    bot = ShowtimeBot()
    return bot.get_movies_and_cinemas()


@st.cache_data(show_spinner=False)
def cached_showtime_get_movie_times(program_id, selected_cinemas_json):
    selected_cinemas = json.loads(selected_cinemas_json)
    bot = ShowtimeBot()
    return bot.get_movie_times(program_id, selected_cinemas)


# ====================================================================
# 6. 共用 UI 元件：顯示查詢結果
# ====================================================================
def show_results(results, selected_movie, date_mode_key, date_filter_value):
    """顯示查詢結果（威秀 / 秀泰共用）"""
    if results:
        filtered_results = {}
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
        else:
            if date_mode_key != "all":
                st.warning(
                    f"⚠️ 所選影城在指定日期內無《{selected_movie}》的場次，"
                    "請嘗試調整日期條件。"
                )
            else:
                st.warning(f"⚠️ 所選影城目前皆無《{selected_movie}》的場次")
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


def date_filter_ui(key_prefix):
    """共用日期篩選 UI，回傳 (date_mode_key, date_filter_value)"""
    st.subheader("3️⃣ 選擇日期")
    date_mode = st.radio(
        "篩選方式：",
        ["全部日期", "特定日期", "日期區間"],
        horizontal=True,
        label_visibility="collapsed",
        key=f"{key_prefix}_date_mode",
    )

    date_filter_value = None
    if date_mode == "特定日期":
        date_filter_value = st.date_input(
            "選擇日期：", value=date.today(), key=f"{key_prefix}_date_single"
        )
    elif date_mode == "日期區間":
        col_start, col_end = st.columns(2)
        with col_start:
            start_date = st.date_input(
                "起始日期：", value=date.today(), key=f"{key_prefix}_date_start"
            )
        with col_end:
            end_date = st.date_input(
                "結束日期：",
                value=date.today() + timedelta(days=6),
                key=f"{key_prefix}_date_end",
            )
        date_filter_value = (start_date, end_date)

    date_mode_key = {
        "全部日期": "all",
        "特定日期": "single",
        "日期區間": "range",
    }[date_mode]

    return date_mode_key, date_filter_value


# ====================================================================
# 7. 前端介面 (UI) — 使用 st.tabs
# ====================================================================
st.title("🎬 電影時刻表查詢")
st.divider()

tab_vieshow, tab_showtime = st.tabs(["🍿 威秀影城", "🎬 秀泰影城"])

# ----------------------------------------------------------------------
# Tab 1: 威秀影城
# ----------------------------------------------------------------------
with tab_vieshow:
    with st.spinner("正在讀取威秀影城與電影清單..."):
        vs_cinema_map, vs_movie_list = cached_vieshow_get_cinemas_and_movies()

    if not vs_cinema_map:
        st.error("無法讀取威秀影城清單，請查看終端機錯誤訊息。")
    elif not vs_movie_list:
        st.warning("無法取得威秀電影清單。")
    else:
        # Step 1: 選擇電影
        st.subheader("1️⃣ 選擇電影")
        vs_selected_movie = st.selectbox(
            "請選擇電影：", vs_movie_list,
            label_visibility="collapsed", key="vs_movie"
        )

        # Step 2: 選擇影城
        st.subheader("2️⃣ 選擇影城（可多選）")
        vs_selected_cinemas = st.multiselect(
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
            st.button("🔍 查詢時刻表", type="primary", disabled=True, key="vs_btn")
            st.info("請先選擇至少一間影城，再點擊查詢。")
        else:
            if st.button("🔍 查詢時刻表", type="primary", key="vs_btn"):
                selected_cinema_dict = {
                    name: vs_cinema_map[name] for name in vs_selected_cinemas
                }
                cinema_json = json.dumps(selected_cinema_dict, ensure_ascii=False)

                with st.spinner(
                    f"正在查詢 {len(vs_selected_cinemas)} 間威秀影城的"
                    f"《{vs_selected_movie}》場次（每間約 5-10 秒）..."
                ):
                    cached_vieshow_get_movie_times.clear()
                    results = cached_vieshow_get_movie_times(
                        cinema_json, vs_selected_movie
                    )

                show_results(
                    results, vs_selected_movie,
                    vs_date_mode_key, vs_date_filter_value
                )

# ----------------------------------------------------------------------
# Tab 2: 秀泰影城
# ----------------------------------------------------------------------
with tab_showtime:
    with st.spinner("正在讀取秀泰電影與影城清單..."):
        st_movies_map, st_cinema_list = cached_showtime_get_movies_and_cinemas()

    if not st_movies_map:
        st.error("無法讀取秀泰電影清單，請查看終端機錯誤訊息。")
    elif not st_cinema_list:
        st.warning("無法取得秀泰影城清單。")
    else:
        # Step 1: 選擇電影
        st.subheader("1️⃣ 選擇電影")
        st_movie_names = list(st_movies_map.keys())
        st_selected_movie = st.selectbox(
            "請選擇電影：", st_movie_names,
            label_visibility="collapsed", key="st_movie"
        )
        st_selected_program_id = st_movies_map[st_selected_movie]

        # Step 2: 選擇影城
        st.subheader("2️⃣ 選擇影城（可多選）")
        st_selected_cinemas = st.multiselect(
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
            st.button("🔍 查詢時刻表", type="primary", disabled=True, key="st_btn")
            st.info("請先選擇至少一間影城，再點擊查詢。")
        else:
            if st.button("🔍 查詢時刻表", type="primary", key="st_btn"):
                cinemas_json = json.dumps(
                    st_selected_cinemas, ensure_ascii=False
                )

                with st.spinner(
                    f"正在查詢《{st_selected_movie}》的場次..."
                ):
                    cached_showtime_get_movie_times.clear()
                    results = cached_showtime_get_movie_times(
                        st_selected_program_id, cinemas_json
                    )

                show_results(
                    results, st_selected_movie,
                    st_date_mode_key, st_date_filter_value
                )
