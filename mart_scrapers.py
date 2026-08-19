"""Retailer-specific page parsers and Selenium scraping adapters."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from enum import Enum

from bs4 import BeautifulSoup
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.support.ui import WebDriverWait


class SyncStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    SOLD_OUT = "SOLD_OUT"
    ERROR = "ERROR"


@dataclass(frozen=True)
class ScrapeResult:
    status: SyncStatus
    buying_price: int | None = None
    original_price: int | None = None
    reason: str = ""


BLOCK_MARKERS = ("access denied", "captcha", "robot check", "비정상적인 접근")
SOLD_OUT_MARKERS = ("일시품절", "품절", "판매종료", "판매 중지", "판매가 중지")


def _price_from(element) -> int | None:
    if element is None:
        return None
    raw = element.get("data-prc") or element.get_text(" ", strip=True)
    digits = re.sub(r"[^0-9]", "", raw)
    return int(digits) if digits else None


def _blocked(soup: BeautifulSoup) -> bool:
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    sample = f"{title} {soup.get_text(' ', strip=True)[:1000]}".lower()
    return any(marker in sample for marker in BLOCK_MARKERS)


def parse_homeplus_html(html: str) -> ScrapeResult:
    soup = BeautifulSoup(html, "html.parser")
    if _blocked(soup):
        return ScrapeResult(SyncStatus.ERROR, reason="접근 차단 페이지 감지")
    action_nodes = soup.select("button, [role='button'], .buy, .action, .footer, [class*='purchase'], [class*='cart']")
    action_text = " ".join(node.get_text(" ", strip=True) for node in action_nodes)
    if any(marker in action_text for marker in SOLD_OUT_MARKERS):
        return ScrapeResult(SyncStatus.SOLD_OUT, reason="구매 영역에서 품절 문구 감지")
    buying_price = _price_from(soup.select_one(".priceType, [class*='priceType']"))
    if not buying_price:
        return ScrapeResult(SyncStatus.ERROR, reason="홈플러스 가격 요소를 찾지 못함")
    original_price = _price_from(soup.select_one(".priceItem.dc, [class*='priceItem'][class*='dc']"))
    return ScrapeResult(SyncStatus.AVAILABLE, buying_price, original_price or buying_price)


def parse_emart_html(html: str) -> ScrapeResult:
    soup = BeautifulSoup(html, "html.parser")
    if _blocked(soup):
        return ScrapeResult(SyncStatus.ERROR, reason="접근 차단 페이지 감지")
    action_root = soup.select_one(".cdtl_btn_wrap")
    action_nodes = [action_root] if action_root else soup.select("button, [role='button'], [class*='buy'], [class*='cart'], [class*='action']")
    action_text = " ".join(node.get_text(" ", strip=True) for node in action_nodes if node)
    if any(marker in action_text for marker in SOLD_OUT_MARKERS):
        return ScrapeResult(SyncStatus.SOLD_OUT, reason="구매 영역에서 품절 문구 감지")
    buying_price = _price_from(soup.select_one(".ssg_price[data-prc], .ssg_price"))
    if not buying_price:
        return ScrapeResult(SyncStatus.ERROR, reason="이마트 가격 요소를 찾지 못함")
    original_price = _price_from(soup.select_one(".price_del .ssg_price, .org_price .ssg_price")) or buying_price
    return ScrapeResult(SyncStatus.AVAILABLE, buying_price, original_price)


class MartScraper:
    def __init__(self, driver, *, retries: int = 2, settle_seconds: float = 1.0) -> None:
        self.driver = driver
        self.retries = max(1, retries)
        self.settle_seconds = settle_seconds
        self._emart_prepared = False

    def _prepare_emart_session(self) -> None:
        if self._emart_prepared:
            return
        try:
            self.driver.get("https://emart.ssg.com/")
            WebDriverWait(self.driver, 20).until(
                lambda browser: browser.execute_script("return document.readyState")
                in ("interactive", "complete")
            )
            time.sleep(self.settle_seconds)
        except (TimeoutException, WebDriverException):
            pass
        self._emart_prepared = True

    def scrape(self, retailer: str, url: str) -> ScrapeResult:
        parser = parse_homeplus_html if retailer == "homeplus" else parse_emart_html
        last_result = ScrapeResult(SyncStatus.ERROR, reason="크롤링을 시작하지 못함")
        if retailer == "emart":
            self._prepare_emart_session()
        for attempt in range(1, self.retries + 1):
            try:
                self.driver.get(url)
                WebDriverWait(self.driver, 20).until(
                    lambda browser: browser.execute_script("return document.readyState") in ("interactive", "complete")
                )
                time.sleep(self.settle_seconds)
                last_result = parser(self.driver.page_source)
                if last_result.status is not SyncStatus.ERROR:
                    return last_result
            except TimeoutException:
                last_result = ScrapeResult(SyncStatus.ERROR, reason="페이지 로드 제한시간 초과")
            except WebDriverException as exc:
                last_result = ScrapeResult(SyncStatus.ERROR, reason=f"브라우저 오류: {exc.msg[:160]}")
            if attempt < self.retries:
                time.sleep(attempt * 2)
        return last_result
