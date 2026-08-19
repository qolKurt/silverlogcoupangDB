"""Synchronize Homeplus and Emart prices with the Silverlog catalogue."""

from __future__ import annotations

import json
import logging
import os
import random
import shutil
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

from mart_scrapers import MartScraper, SyncStatus
from silverlog_client import SilverlogClient, SilverlogError


LOG = logging.getLogger("catalog-sync")
REPORT_JSON = Path("sync_report.json")
REPORT_TEXT = Path("manual_check_report.txt")
REPORT_MARKDOWN = Path("sync_report.md")


def identify_retailer(item: dict[str, Any]) -> str | None:
    reference = str(item.get("reference") or "").lower()
    source = str(item.get("purchaseSource") or "").strip()
    if "homeplus.co.kr" in reference or source == "홈플러스":
        return "homeplus"
    if "ssg.com" in reference or "emart" in reference or source == "이마트":
        return "emart"
    return None


def calculate_sale_price(buying_price: int) -> int:
    return int((buying_price * 1.07) // 100) * 100 + 90


def is_suspicious_price(previous: Any, current: int, max_ratio: float) -> bool:
    try:
        previous_price = int(previous)
    except (TypeError, ValueError):
        return False
    return previous_price > 0 and abs(current - previous_price) / previous_price > max_ratio


def create_driver():
    chrome_binary = (
        os.getenv("CHROME_BINARY")
        or shutil.which("google-chrome")
        or shutil.which("google-chrome-stable")
        or shutil.which("chrome")
    )
    driver_binary = os.getenv("CHROMEDRIVER") or shutil.which("chromedriver")

    options = Options()
    if chrome_binary:
        options.binary_location = chrome_binary
    if os.getenv("SELENIUM_HEADLESS", "false").lower() in {"1", "true", "yes"}:
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1440,1200")
    options.page_load_strategy = "eager"

    service = Service(driver_binary) if driver_binary else Service()
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(int(os.getenv("PAGE_LOAD_TIMEOUT", "30")))
    driver.set_script_timeout(20)
    return driver


def write_reports(summary: dict[str, Any], manual_checks: list[dict[str, Any]]) -> None:
    REPORT_JSON.write_text(
        json.dumps({**summary, "manual_checks": manual_checks}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "=== 수작업 확인 필요 상품 목록 ===", "",
        f"작성일시(UTC): {summary['finished_at']}",
        f"감지된 항목 수: {len(manual_checks)}개", "-" * 50,
    ]
    lines.extend(
        f"- [{entry['status']}] {entry['name']} | {entry['reason']} | {entry.get('url', '')}"
        for entry in manual_checks
    )
    REPORT_TEXT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    counts = summary["counts"]
    markdown = [
        "## 대형마트 동기화 결과", "",
        f"- 실행 모드: {'DRY RUN' if summary.get('dry_run') else 'LIVE'}",
        f"- 대상 상품: {summary['target_items']}개",
        f"- 가격 갱신: {counts.get('UPDATED', 0)}개",
        f"- 갱신 예정(DRY RUN): {counts.get('WOULD_UPDATE', 0)}개",
        f"- 품절 비활성화: {counts.get('SOLD_OUT', 0)}개",
        f"- 비활성화 예정(DRY RUN): {counts.get('WOULD_DEACTIVATE', 0)}개",
        f"- 변경 없음: {counts.get('UNCHANGED', 0)}개",
        f"- 수동 확인/오류: {len(manual_checks)}개",
    ]
    REPORT_MARKDOWN.write_text("\n".join(markdown) + "\n", encoding="utf-8")


def run_sync() -> int:
    started_at = datetime.now(timezone.utc).isoformat()
    max_change_ratio = float(os.getenv("MAX_PRICE_CHANGE_RATIO", "0.30"))
    retries = int(os.getenv("SCRAPE_RETRIES", "2"))
    dry_run = os.getenv("DRY_RUN", "false").lower() in {"1", "true", "yes"}
    retailer_filter = os.getenv("RETAILER_FILTER", "").strip().lower()
    item_limit = int(os.getenv("ITEM_LIMIT", "0"))
    request_delay_min = float(os.getenv("REQUEST_DELAY_MIN", "6"))
    request_delay_max = float(os.getenv("REQUEST_DELAY_MAX", "12"))
    if request_delay_min < 0 or request_delay_max < request_delay_min:
        raise ValueError("REQUEST_DELAY_MIN/MAX 설정이 올바르지 않습니다.")
    counts: Counter[str] = Counter()
    manual_checks: list[dict[str, Any]] = []
    target_items = 0
    driver = None

    try:
        client = SilverlogClient(timeout=float(os.getenv("API_TIMEOUT", "15")))
        LOG.info("Silverlog 어드민에 로그인합니다.")
        client.login()
        items = client.get_catalogue()
        LOG.info("카탈로그 %d개를 조회했습니다.", len(items))
        driver = create_driver()
        scraper = MartScraper(driver, retries=retries)

        for index, item in enumerate(items, 1):
            retailer = identify_retailer(item)
            if not retailer:
                counts["SKIPPED"] += 1
                continue
            if retailer_filter and retailer != retailer_filter:
                counts["FILTERED"] += 1
                continue
            if item_limit and target_items >= item_limit:
                break

            if target_items:
                delay = random.uniform(request_delay_min, request_delay_max)
                LOG.info("다음 상품 요청 전 %.1f초 대기합니다.", delay)
                time.sleep(delay)
            target_items += 1
            name = str(item.get("name") or "이름 없는 상품")
            url = str(item.get("reference") or "").strip()
            item_id = str(item.get("_id") or "")
            LOG.info("[%d/%d] %s 확인: %s", index, len(items), retailer, name)

            if not item_id or not url.startswith(("http://", "https://")):
                counts["INVALID_ITEM"] += 1
                manual_checks.append({"status": "INVALID_ITEM", "name": name, "reason": "상품 ID 또는 링크 누락", "url": url})
                continue

            result = scraper.scrape(retailer, url)
            if result.status is SyncStatus.ERROR:
                counts["SCRAPE_ERROR"] += 1
                manual_checks.append({"status": "SCRAPE_ERROR", "name": name, "reason": result.reason, "url": url})
                LOG.warning("크롤링 실패: %s (%s)", name, result.reason)
                if result.reason == "접근 차단 페이지 감지":
                    counts["BOT_BLOCKED"] += 1
                    LOG.error("자동화 차단 페이지가 감지되어 추가 요청을 중단합니다.")
                    break
                continue

            try:
                if result.status is SyncStatus.SOLD_OUT:
                    if item.get("active", True):
                        if dry_run:
                            counts["WOULD_DEACTIVATE"] += 1
                        else:
                            client.update_item(item_id, {"active": False})
                            counts["SOLD_OUT"] += 1
                    else:
                        counts["UNCHANGED"] += 1
                    manual_checks.append({"status": "SOLD_OUT", "name": name, "reason": result.reason, "url": url})
                    continue

                assert result.buying_price is not None
                if is_suspicious_price(item.get("buyingPrice"), result.buying_price, max_change_ratio):
                    counts["PRICE_REVIEW"] += 1
                    manual_checks.append({
                        "status": "PRICE_REVIEW", "name": name,
                        "reason": f"가격 변동이 {max_change_ratio:.0%}를 초과함 ({item.get('buyingPrice')} → {result.buying_price})",
                        "url": url,
                    })
                    continue

                payload = {
                    "price": calculate_sale_price(result.buying_price),
                    "originalPrice": result.original_price or result.buying_price,
                    "buyingPrice": result.buying_price,
                    "active": True,
                }
                if {key: item.get(key) for key in payload} == payload:
                    counts["UNCHANGED"] += 1
                elif dry_run:
                    counts["WOULD_UPDATE"] += 1
                else:
                    client.update_item(item_id, payload)
                    counts["UPDATED"] += 1
            except SilverlogError as exc:
                counts["API_ERROR"] += 1
                manual_checks.append({"status": "API_ERROR", "name": name, "reason": str(exc), "url": url})

    except (SilverlogError, RuntimeError, ValueError) as exc:
        LOG.error("동기화를 시작하거나 계속할 수 없습니다: %s", exc)
        counts["FATAL_ERROR"] += 1
        manual_checks.append({"status": "FATAL_ERROR", "name": "동기화 작업", "reason": str(exc), "url": ""})
    finally:
        if driver is not None:
            driver.quit()

    summary = {
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "target_items": target_items,
        "dry_run": dry_run,
        "counts": dict(counts),
    }
    write_reports(summary, manual_checks)
    LOG.info("동기화 종료: %s", dict(counts))

    successful = (
        counts["UPDATED"] + counts["SOLD_OUT"] + counts["UNCHANGED"]
        + counts["WOULD_UPDATE"] + counts["WOULD_DEACTIVATE"]
    )
    failures = counts["SCRAPE_ERROR"] + counts["API_ERROR"] + counts["INVALID_ITEM"] + counts["FATAL_ERROR"]
    return 1 if counts["FATAL_ERROR"] or counts["BOT_BLOCKED"] or (target_items > 0 and successful == 0 and failures > 0) else 0


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(run_sync())
