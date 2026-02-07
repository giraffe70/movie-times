"""威秀影城爬蟲機器人

透過 Playwright 爬取威秀影城官網，取得影城清單、電影清單及場次資料。
"""
from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright_stealth import Stealth

from bots.base_bot import BaseBot
from config import VIESHOW_URL

logger = logging.getLogger(__name__)


class VieshowBot(BaseBot):
    """威秀影城爬蟲機器人"""

    LABEL: str = "威秀"

    def __init__(self) -> None:
        self.url: str = VIESHOW_URL

    def get_cinemas_and_movies(self) -> tuple[dict[str, str], list[str]]:
        """取得威秀影城清單與電影清單。

        Returns:
            (cinema_options, movie_list)
            - cinema_options: {影城名稱: 影城代碼}
            - movie_list: [電影名稱, ...]
        """
        cinema_options: dict[str, str] = {}
        movie_list: list[str] = []

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
                    page.evaluate(f"""
                        var select = document.querySelector('{selector}');
                        select.dispatchEvent(
                            new Event('change', {{bubbles: true}})
                        );
                    """)

                    try:
                        page.wait_for_function(
                            """() => {
                                if (document.querySelector('.MovieName'))
                                    return true;
                                if (document.body.innerText.includes('查無資料'))
                                    return true;
                                return false;
                            }""",
                            timeout=15000,
                        )
                        # 等待網路請求完成，取代固定 time.sleep
                        try:
                            page.wait_for_load_state(
                                "networkidle", timeout=5000
                            )
                        except PlaywrightTimeout:
                            pass
                    except PlaywrightTimeout:
                        logger.warning("等待電影清單超時")
                    except Exception as e:
                        logger.warning("等待電影清單時發生錯誤: %s", e)

                    content = page.content()
                    soup = BeautifulSoup(content, "html.parser")
                    movie_tags = soup.select("strong.MovieName.LangTW")
                    seen: set[str] = set()
                    for tag in movie_tags:
                        name = tag.get_text(strip=True)
                        if name and name not in seen:
                            movie_list.append(name)
                            seen.add(name)

                logger.info(
                    "[威秀] 取得 %d 間影城、%d 部電影",
                    len(cinema_options),
                    len(movie_list),
                )

            except Exception as e:
                logger.error("get_cinemas_and_movies 失敗: %s", e)
            finally:
                browser.close()

        return cinema_options, movie_list

    def get_movie_times_for_cinemas(
        self,
        cinema_dict: dict[str, str],
        target_movie: str,
    ) -> dict[str, dict[str, list[str]]]:
        """查詢指定電影在多間影城的場次。

        Args:
            cinema_dict: {影城名稱: 影城代碼}
            target_movie: 目標電影名稱

        Returns:
            {影城名稱: {日期字串: [時間列表]}}
        """
        results: dict[str, dict[str, list[str]]] = {}

        with Stealth().use_sync(sync_playwright()) as p:
            logger.info(
                "[威秀] 啟動爬蟲，查詢《%s》於 %d 間影城",
                target_movie,
                len(cinema_dict),
            )
            browser, page = self._create_stealth_page(p)

            try:
                for cinema_name, cinema_value in cinema_dict.items():
                    logger.info("[威秀] 正在查詢：%s", cinema_name)
                    page.goto(self.url, timeout=60000)

                    target_select_id = "#CinemaNameTWInfoF"
                    page.wait_for_selector(target_select_id)

                    page.select_option(target_select_id, value=cinema_value)
                    page.evaluate(f"""
                        var select = document.querySelector(
                            '{target_select_id}'
                        );
                        select.dispatchEvent(
                            new Event('change', {{bubbles: true}})
                        );
                    """)

                    try:
                        page.wait_for_function(
                            """() => {
                                if (document.querySelector('.MovieName'))
                                    return true;
                                if (document.body.innerText.includes('查無資料'))
                                    return true;
                                if (document.body.innerText.includes('目前無場次'))
                                    return true;
                                return false;
                            }""",
                            timeout=15000,
                        )
                        try:
                            page.wait_for_load_state(
                                "networkidle", timeout=5000
                            )
                        except PlaywrightTimeout:
                            pass
                    except PlaywrightTimeout:
                        logger.warning("%s 等待超時", cinema_name)
                    except Exception as e:
                        logger.warning("%s 等待時發生錯誤: %s", cinema_name, e)

                    content = page.content()
                    soup = BeautifulSoup(content, "html.parser")

                    page_text = soup.get_text()
                    if "查無資料" in page_text or "目前無場次" in page_text:
                        results[cinema_name] = {}
                        continue

                    movie_tags = soup.select("strong.MovieName.LangTW")
                    date_times: dict[str, list[str]] = {}

                    for movie_tag in movie_tags:
                        movie_name = movie_tag.get_text(strip=True)
                        if movie_name != target_movie:
                            continue

                        parent_div = movie_tag.find_parent(
                            "div", class_="col-xs-12"
                        )
                        if not parent_div:
                            continue

                        date_tags = parent_div.select(
                            "strong.RealShowDate.LangTW"
                        )
                        for date_tag in date_tags:
                            date_str = date_tag.get_text(strip=True)
                            times_list: list[str] = []
                            next_elem = date_tag.find_next_sibling()

                            while next_elem:
                                classes = next_elem.get("class", [])

                                if "SessionTimeInfo" in classes:
                                    block_text = next_elem.get_text()
                                    found_times = re.findall(
                                        r"\d{1,2}:\d{2}", block_text
                                    )
                                    if found_times:
                                        times_list.extend(found_times)
                                    break

                                if (
                                    "RealShowDate" in classes
                                    and "LangTW" in classes
                                ):
                                    break

                                next_elem = next_elem.find_next_sibling()

                            if times_list:
                                clean_date = (
                                    date_str.replace("場次", "").strip()
                                )
                                unique_times = sorted(list(set(times_list)))
                                date_times[clean_date] = unique_times

                    results[cinema_name] = date_times
                    logger.info(
                        "[威秀] %s 完成，找到 %d 天場次",
                        cinema_name,
                        len(date_times),
                    )

            except Exception as e:
                logger.error("get_movie_times_for_cinemas 失敗: %s", e)
            finally:
                browser.close()

        return results
