"""Manual browser check for the long-history workbench layout."""

import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


BASE_URL = os.getenv("MAP_TEST_URL", "http://127.0.0.1:8001")
OUTPUT_DIR = Path("outputs/playwright")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser_path = os.getenv("MAP_TEST_BROWSER")
        browser = playwright.chromium.launch(headless=True, executable_path=browser_path or None)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        console_errors: list[str] = []
        request_failures: list[str] = []
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on("requestfailed", lambda request: request_failures.append(f"{request.method} {request.url}: {request.failure}"))
        page.goto(f"{BASE_URL}/mapping/", wait_until="domcontentloaded", timeout=20000)

        if "/accounts/login" in page.url:
            page.locator("#username").fill(os.environ["MAP_TEST_USERNAME"])
            page.locator("#password").fill(os.environ["MAP_TEST_PASSWORD"])
            page.locator(".auth-submit").click()
            page.wait_for_url("**/mapping/**", wait_until="domcontentloaded", timeout=20000)

        page.locator(".history-panel").wait_for(state="visible", timeout=20000)
        page.locator("#history-search-input").wait_for(state="visible", timeout=10000)
        page.wait_for_function(
            """() => {
                const total = document.querySelector('.history-total')?.textContent?.trim();
                const empty = document.querySelector('.history-list .muted');
                const emptyText = empty?.textContent || '';
                return (total && total !== '0') || (Boolean(empty) && !emptyText.includes('正在读取'));
            }""",
            timeout=20000,
        )
        metrics = page.evaluate(
            """() => {
                const historyPanel = document.querySelector('.history-panel');
                const historyList = document.querySelector('.history-list');
                const inspector = document.querySelector('.inspector-panel');
                const composer = document.querySelector('.composer');
                const panelRect = historyPanel?.getBoundingClientRect();
                const items = Array.from(document.querySelectorAll('.history-item'));
                return {
                    historyPanel: panelRect?.toJSON(),
                    historyList: {
                        clientHeight: historyList?.clientHeight,
                        scrollHeight: historyList?.scrollHeight,
                        overflowY: historyList ? getComputedStyle(historyList).overflowY : null,
                    },
                    inspector: {
                        position: inspector ? getComputedStyle(inspector).position : null,
                        height: inspector?.getBoundingClientRect().height,
                    },
                    composerTop: composer?.getBoundingClientRect().top,
                    viewportHeight: window.innerHeight,
                    pageScrollHeight: document.documentElement.scrollHeight,
                    historyItemCount: items.length,
                    historyItemRects: items.slice(0, 2).concat(items.slice(-1)).map((item) => item.getBoundingClientRect().toJSON()),
                    historyTotalText: document.querySelector('.history-total')?.textContent,
                    historyListText: document.querySelector('.history-list')?.innerText?.slice(0, 200),
                };
            }"""
        )
        page.screenshot(path=str(OUTPUT_DIR / "workbench-history.png"), full_page=True)

        history_list = page.locator(".history-list")
        if metrics["historyList"]["scrollHeight"] <= metrics["historyList"]["clientHeight"]:
            print(json.dumps(metrics, ensure_ascii=False, indent=2))
            raise AssertionError("历史记录不足以验证独立滚动，请准备至少两屏历史数据")
        page.locator(".history-heading-actions .icon-button").nth(1).click()
        page.wait_for_function(
            """() => {
                const element = document.querySelector('.history-list');
                return Boolean(element && element.scrollTop + element.clientHeight >= element.scrollHeight - 2);
            }""",
            timeout=2000,
        )
        metrics["historyList"]["scrollTopAfterJump"] = history_list.evaluate("element => element.scrollTop")
        metrics["historyList"]["bottomReachable"] = history_list.evaluate(
            "element => element.scrollTop + element.clientHeight >= element.scrollHeight - 2"
        )

        search = page.locator("#history-search-input")
        search.fill("北京")
        metrics["filteredHistoryCount"] = page.locator(".history-item").count()
        page.screenshot(path=str(OUTPUT_DIR / "workbench-history-search.png"), full_page=False)
        metrics["consoleErrors"] = console_errors
        metrics["requestFailures"] = request_failures
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
        browser.close()


if __name__ == "__main__":
    main()
