"""Read-only diagnostic for comparing SSG access from hosted runner networks."""

from __future__ import annotations

import os

import requests
from selenium import webdriver

from mart_scrapers import EMART_NAVIGATION_HEADERS, SyncStatus, parse_emart_html


def main() -> int:
    url = os.environ["PROBE_URL"]
    successes: list[str] = []

    try:
        response = requests.get(url, headers=EMART_NAVIGATION_HEADERS, timeout=25)
        http_result = parse_emart_html(response.text) if response.status_code == 200 else None
        print(
            "HTTP",
            f"status={response.status_code}",
            f"result={http_result.status.value if http_result else 'HTTP_ERROR'}",
            f"price={http_result.buying_price if http_result else None}",
        )
        if http_result and http_result.status is not SyncStatus.ERROR:
            successes.append("http")
    except Exception as exc:  # Diagnostic output; production code remains stricter.
        print(f"HTTP exception={type(exc).__name__}: {str(exc)[:160]}")

    driver = None
    try:
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1440,1200")
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(40)
        driver.get(url)
        browser_result = parse_emart_html(driver.page_source)
        print(
            "CHROME",
            f"title={driver.title!r}",
            f"result={browser_result.status.value}",
            f"price={browser_result.buying_price}",
            f"reason={browser_result.reason!r}",
        )
        if browser_result.status is not SyncStatus.ERROR:
            successes.append("chrome")
    except Exception as exc:
        print(f"CHROME exception={type(exc).__name__}: {str(exc)[:240]}")
    finally:
        if driver is not None:
            driver.quit()

    print(f"SUCCESS_PATHS={','.join(successes) if successes else 'none'}")
    return 0 if successes else 1


if __name__ == "__main__":
    raise SystemExit(main())
