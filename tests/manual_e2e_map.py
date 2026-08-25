"""Manual browser acceptance test for the Guangdong map-generation workflow."""

import argparse
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


PROMPT = "请使用 data/data1/Guangdong.shp 绘制广东省行政区划图，显示省界，标题为广东省行政区划图。"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("MAP_E2E_BASE_URL", "http://127.0.0.1:8001"),
    )
    parser.add_argument("--timeout", type=int, default=180)
    return parser.parse_args()


def main():
    args = parse_args()
    username = os.getenv("MAP_E2E_USERNAME")
    password = os.getenv("MAP_E2E_PASSWORD")
    if not username or not password:
        raise SystemExit("Set MAP_E2E_USERNAME and MAP_E2E_PASSWORD before running this test.")

    output_dir = Path("outputs/e2e")
    output_dir.mkdir(parents=True, exist_ok=True)
    page_errors = []
    console_errors = []
    http_errors = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        )
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.set_default_timeout(30_000)
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "response",
            lambda response: http_errors.append(f"{response.status} {response.url}")
            if response.status >= 400
            else None,
        )
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )

        page.goto(f"{args.base_url}/accounts/login", wait_until="networkidle")
        page.get_by_label("用户名").fill(username)
        page.get_by_label("密码").fill(password)
        page.get_by_role("button", name="登录").click()
        page.wait_for_url("**/mapping/**", wait_until="domcontentloaded")
        page.locator(".composer textarea").fill(PROMPT)
        page.get_by_role("button", name="开始制图").click()

        deadline = time.monotonic() + args.timeout
        progress_seen = False
        final_status = ""
        while time.monotonic() < deadline:
            final_status = page.locator(".map-meta .status").inner_text()
            progress_seen = progress_seen or page.locator(".log-line").count() > 0
            if final_status in {"已完成", "生成失败"}:
                break
            page.wait_for_timeout(2_000)

        page.locator(".stored-map-preview").wait_for(timeout=30_000)
        page.locator("#result-card .file-action", has_text="打开").wait_for()
        page.locator("#result-card .file-action", has_text="下载 PNG").wait_for()
        page.locator(".result-download").wait_for()
        artifact_href = page.locator("#result-card .file-action", has_text="打开").get_attribute("href")
        if not artifact_href or "/generated_maps/" not in artifact_href:
            raise AssertionError(f"Opened artifact URL is invalid: {artifact_href}")
        artifact_response = context.request.get(f"{args.base_url}{artifact_href}")
        if artifact_response.status != 200 or not artifact_response.headers.get("content-type", "").startswith("image/"):
            raise AssertionError(f"Artifact response is invalid: {artifact_response.status}")
        with page.expect_download() as download_info:
            page.locator("#result-card .file-action", has_text="下载 PNG").click()
        download = download_info.value
        if not download.suggested_filename.endswith(".png"):
            raise AssertionError(f"Unexpected download filename: {download.suggested_filename}")
        page.screenshot(path=str(output_dir / "manual_e2e_guangdong.png"), full_page=True)
        print(
            {
                "status": final_status,
                "logs": page.locator(".log-line").count(),
                "result_cards": page.locator("#result-card").count(),
                "progress_seen": progress_seen,
                "page_errors": page_errors,
                "console_errors": console_errors,
                "http_errors": http_errors,
            }
        )
        context.close()
        browser.close()

    if final_status != "已完成" or not progress_seen or page_errors or console_errors or http_errors:
        raise SystemExit("Browser acceptance test failed; inspect outputs/e2e/manual_e2e_guangdong.png")


if __name__ == "__main__":
    main()
