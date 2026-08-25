"""Manual end-to-end matrix for the map workbench."""

import argparse
import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


CASES = [
    {
        "id": "natural-wuhan",
        "prompt": "请绘制武汉市行政区划图，显示各区边界，标题为武汉市行政区划图。",
        "expected": "已完成",
    },
    {
        "id": "explicit-henan",
        "prompt": "请使用 data/data4/Henan.shp 绘制河南省行政区划图，显示省界，标题为河南省行政区划图。",
        "expected": "已完成",
    },
    {
        "id": "multi-layer-transport",
        "prompt": "请使用 data/data2/Highway.shp 和 data/data2/Railway.shp 绘制交通图，显示高速公路和铁路，标题为交通线路图。",
        "expected": "已完成",
    },
]


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("MAP_E2E_BASE_URL", "http://127.0.0.1:8001"),
    )
    parser.add_argument("--timeout", type=int, default=180)
    return parser.parse_args()


def wait_for_terminal(page, timeout_seconds):
    deadline = time.monotonic() + timeout_seconds
    progress_seen = False
    while time.monotonic() < deadline:
        status = page.locator(".map-meta .status").inner_text()
        progress_seen = progress_seen or page.locator(".log-line").count() > 0
        if status in {"已完成", "生成失败"}:
            break
        page.wait_for_timeout(2_000)
    status = page.locator(".map-meta .status").inner_text()
    return status, progress_seen


def wait_for_result(page):
    page.locator(".stored-map-preview").wait_for(timeout=30_000)
    page.locator("#result-card").wait_for(timeout=30_000)


def run_case(page, test_case, timeout_seconds):
    page.get_by_role("button", name="新建任务").click()
    page.locator(".composer textarea").fill(test_case["prompt"])
    page.get_by_role("button", name="开始制图").click()
    status, progress_seen = wait_for_terminal(page, timeout_seconds)
    if status == "已完成":
        wait_for_result(page)
    result = {
        "id": test_case["id"],
        "status": status,
        "expected": test_case["expected"],
        "progress_seen": progress_seen,
        "logs": page.locator(".log-line").count(),
        "layers": page.locator(".map-meta").inner_text(),
        "result_card": page.locator("#result-card").count() == 1,
        "stored_preview": page.locator(".stored-map-preview").count() == 1,
        "file_actions": page.locator("#result-card .file-action").count(),
    }
    return result


def main():
    args = parse_args()
    username = os.getenv("MAP_E2E_USERNAME")
    password = os.getenv("MAP_E2E_PASSWORD")
    if not username or not password:
        raise SystemExit("Set MAP_E2E_USERNAME and MAP_E2E_PASSWORD before running this test.")

    output_dir = Path("outputs/e2e")
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
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
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.on(
            "response",
            lambda response: http_errors.append(f"{response.status} {response.url}")
            if response.status >= 400
            else None,
        )

        page.goto(f"{args.base_url}/accounts/login", wait_until="networkidle")
        page.get_by_label("用户名").fill(username)
        page.get_by_label("密码").fill(password)
        page.get_by_role("button", name="登录").click()
        page.wait_for_url("**/mapping/**", wait_until="domcontentloaded")
        page.locator(".composer textarea").wait_for()

        # Client-side validation must prevent empty and whitespace-only submissions.
        submit = page.get_by_role("button", name="开始制图")
        empty_validation = {"empty_disabled": submit.is_disabled()}
        page.locator(".composer textarea").fill("   ")
        empty_validation["whitespace_disabled"] = submit.is_disabled()
        page.locator(".composer textarea").fill("")

        for test_case in CASES:
            results.append(run_case(page, test_case, args.timeout))

        # Continue the last successful session to verify adjustment and versioning.
        adjustment = "请将当前地图边界线改为深绿色，并把标题改为交通线路图（调整版）。"
        page.locator(".composer textarea").fill(adjustment)
        page.get_by_role("button", name="发送调整").click()
        status, progress_seen = wait_for_terminal(page, args.timeout)
        if status == "已完成":
            wait_for_result(page)
        results.append(
            {
                "id": "conversation-adjustment",
                "status": status,
                "expected": "已完成",
                "progress_seen": progress_seen,
                "logs": page.locator(".log-line").count(),
                "result_card": page.locator("#result-card").count() == 1,
                "stored_preview": page.locator(".stored-map-preview").count() == 1,
                "file_actions": page.locator("#result-card .file-action").count(),
            }
        )

        # History selection, preview controls, and page-scroll isolation.
        page.get_by_role("button", name="新建任务").click()
        page.wait_for_timeout(1000)
        history_item = page.locator(".history-item").first
        history_item.wait_for()
        history_deadline = time.monotonic() + 30
        history_status = ""
        while time.monotonic() < history_deadline:
            history_status = history_item.locator(".history-item-meta").inner_text()
            if "已完成" in history_status:
                break
            page.wait_for_timeout(500)
        history_item.click()
        page.locator(".stored-map-preview").wait_for()
        viewport = page.locator(".stored-map-viewport")
        before_transform = viewport.locator("img").get_attribute("style") or ""
        page.get_by_role("button", name="放大地图").click()
        after_zoom = viewport.locator("img").get_attribute("style") or ""
        box = viewport.bounding_box()
        if not box:
            raise AssertionError("Stored map viewport has no layout box")
        page.mouse.move(box["x"] + 240, box["y"] + 200)
        page.mouse.down()
        page.mouse.move(box["x"] + 240, box["y"] + 260)
        page.mouse.up()
        after_drag = viewport.locator("img").get_attribute("style") or ""
        page.evaluate("window.scrollTo(0, 0)")
        page.locator(".map-stage").hover()
        scroll_before = page.evaluate("window.scrollY")
        page.mouse.wheel(0, 500)
        page.wait_for_timeout(250)
        scroll_after = page.evaluate("window.scrollY")
        interaction = {
            "history_preview": True,
            "history_status_completed": "已完成" in history_status,
            "zoom_changed": before_transform != after_zoom,
            "drag_changed": after_zoom != after_drag,
            "page_scroll_locked": scroll_before == scroll_after,
        }
        page.screenshot(path=str(output_dir / "manual_prompt_matrix.png"), full_page=True)

        print(json.dumps({
            "empty_validation": empty_validation,
            "cases": results,
            "interaction": interaction,
            "page_errors": page_errors,
            "console_errors": console_errors,
            "http_errors": http_errors,
        }, ensure_ascii=True))
        context.close()
        browser.close()

    failures = [item for item in results if item["status"] != item["expected"] or not item["progress_seen"]]
    if failures or not all(empty_validation.values()) or not all(interaction.values()):
        raise SystemExit("Prompt matrix failed; inspect outputs/e2e/manual_prompt_matrix.png")
    if page_errors or console_errors or http_errors:
        raise SystemExit("Prompt matrix found browser errors; inspect outputs/e2e/manual_prompt_matrix.png")


if __name__ == "__main__":
    main()
