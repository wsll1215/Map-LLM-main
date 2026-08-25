"""Verify that multiple clarification replies retain the original request context."""

import argparse
import json
import os
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("MAP_E2E_BASE_URL", "http://127.0.0.1:8001"))
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--output-dir", default="outputs/e2e/stepwise-clarification")
    return parser.parse_args()


def wait_for_status(page, expected, timeout_seconds, *, leave_status=None):
    deadline = time.monotonic() + timeout_seconds
    if leave_status is not None:
        while time.monotonic() < deadline:
            if page.locator(".status-card strong").inner_text() != leave_status:
                break
            page.wait_for_timeout(250)
    while time.monotonic() < deadline:
        status = page.locator(".status-card strong").inner_text()
        if status in expected:
            return status
        page.wait_for_timeout(500)
    return page.locator(".status-card strong").inner_text()


def request_id(page):
    value = page.locator(".request-id").inner_text()
    match = re.search(r"#(\d+)", value)
    if not match:
        raise AssertionError(f"request id not found in {value!r}")
    return int(match.group(1))


def fetch_json(page, url):
    return page.evaluate(
        """async (url) => {
          const response = await fetch(url, {credentials: 'same-origin'});
          return {status: response.status, body: await response.json().catch(() => ({}))};
        }""",
        url,
    )


def main():
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        )
        api = playwright.request.new_context()
        login_page = api.get(f"{args.base_url}/accounts/login")
        csrf = re.search(
            r'name="csrfmiddlewaretoken"[^>]+value="([^"]+)', login_page.text()
        ).group(1)
        login_response = api.post(
            f"{args.base_url}/accounts/login",
            form={
                "csrfmiddlewaretoken": csrf,
                "username": os.getenv("MAP_E2E_USERNAME", "123456"),
                "password": os.getenv("MAP_E2E_PASSWORD", "123456"),
            },
            max_redirects=0,
        )
        if login_response.status != 302:
            raise AssertionError(f"login failed with status {login_response.status}")
        context = browser.new_context(
            storage_state=api.storage_state(), viewport={"width": 1440, "height": 900}
        )
        page = context.new_page()
        page.set_default_timeout(30_000)
        page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
        page.on("console", lambda message: errors.append(f"console: {message.text}") if message.type == "error" else None)

        page.goto(f"{args.base_url}/mapping/", wait_until="domcontentloaded")
        page.locator(".composer textarea").wait_for()
        page.get_by_role("button", name="新建任务").click()

        steps = ["帮我画个图", "北京", "道路图"]
        observed = []
        for index, prompt in enumerate(steps):
            page.locator(".composer textarea").fill(prompt)
            page.get_by_role("button", name="开始制图" if index == 0 else "继续处理").click()
            status = wait_for_status(
                page,
                {"等待补充信息", "已完成", "生成失败"},
                args.timeout,
                leave_status="等待补充信息" if index else None,
            )
            observed.append({"prompt": prompt, "status": status})
            if index < len(steps) - 1 and status != "等待补充信息":
                break

        rid = request_id(page)
        detail = fetch_json(page, f"/mapping/api/map-requests/{rid}/")
        messages = fetch_json(page, f"/mapping/api/chat-messages/{rid}/")
        report = {
            "steps": observed,
            "request_id": rid,
            "detail": detail,
            "messages": messages,
            "errors": errors,
        }
        (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        context.close()
        api.dispose()
        browser.close()

    if observed != [
        {"prompt": "帮我画个图", "status": "等待补充信息"},
        {"prompt": "北京", "status": "等待补充信息"},
        {"prompt": "道路图", "status": "已完成"},
    ]:
        raise SystemExit(f"Stepwise clarification failed; report: {output_dir / 'report.json'}")
    if detail["status"] != 200 or detail["body"].get("status") != "completed" or errors:
        raise SystemExit(f"Stepwise clarification failed; report: {output_dir / 'report.json'}")


if __name__ == "__main__":
    main()
