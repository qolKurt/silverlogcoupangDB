"""Retailer-specific page parsers and Selenium scraping adapters."""

from __future__ import annotations

import re
import os
import time
from dataclasses import dataclass
from enum import Enum

from bs4 import BeautifulSoup
import requests
from requests import RequestException
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
EMART_NAVIGATION_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "accept-language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "cache-control": "max-age=0",
    "priority": "u=0, i",
    "sec-ch-ua": '"Not=A?Brand";v="99", "Google Chrome";v="151", "Chromium";v="151"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
}


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
    def __init__(self, driver, *, retries: int = 2, settle_seconds: float = 1.0,
                 http_session: requests.Session | None = None) -> None:
        self.driver = driver
        self.retries = max(1, retries)
        self.settle_seconds = settle_seconds
        self.http_session = http_session or requests.Session()

    def _scrape_emart_http(self, url: str) -> ScrapeResult:
        last_result = ScrapeResult(SyncStatus.ERROR, reason="이마트 HTTP 수집을 시작하지 못함")
        clean_url = url.split()[0]
        proxy_url = os.getenv("EMART_PROXY_URL", "").strip()
        proxy_token = os.getenv("EMART_PROXY_TOKEN", "").strip()
        for attempt in range(1, self.retries + 1):
            try:
                if proxy_url and proxy_token:
                    response = self.http_session.post(
                        proxy_url,
                        headers={"Authorization": f"Bearer {proxy_token}"},
                        json={"url": clean_url},
                        timeout=30,
                    )
                    if response.status_code == 200:
                        payload = response.json()
                        return ScrapeResult(
                            SyncStatus(payload["status"]),
                            payload.get("buying_price"),
                            payload.get("original_price"),
                            payload.get("reason", ""),
                        )
                else:
                    response = self.http_session.get(
                        clean_url,
                        headers=EMART_NAVIGATION_HEADERS,
                        timeout=25,
                        allow_redirects=True,
                    )
                    if response.status_code == 200:
                        response.encoding = response.apparent_encoding or "utf-8"
                        return parse_emart_html(response.text)
                if response.status_code == 200:
                    last_result = ScrapeResult(SyncStatus.ERROR, reason="이마트 프록시 응답 형식 오류")
                    continue
                last_result = ScrapeResult(
                    SyncStatus.ERROR,
                    reason=f"이마트 가격 요청 실패 (HTTP {response.status_code})",
                )
            except (RequestException, ValueError, KeyError) as exc:
                last_result = ScrapeResult(
                    SyncStatus.ERROR,
                    reason=f"이마트 가격 요청 오류: {str(exc)[:160]}",
                )
            if attempt < self.retries:
                time.sleep(attempt * 2)
        return last_result

    def scrape(self, retailer: str, url: str) -> ScrapeResult:
        if retailer == "emart":
            return self._scrape_emart_http(url)
        parser = parse_homeplus_html if retailer == "homeplus" else parse_emart_html
        last_result = ScrapeResult(SyncStatus.ERROR, reason="크롤링을 시작하지 못함")
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
