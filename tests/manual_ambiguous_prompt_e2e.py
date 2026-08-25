"""Browser matrix for ambiguous, incomplete, and conflicting map prompts."""

import argparse
import json
import os
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


CASES = [
    {"id": "vague-create", "prompt": "帮我画个图", "expected": "needs_clarification"},
    {"id": "location-only", "prompt": "北京", "expected": "needs_clarification"},
    {"id": "vague-style", "prompt": "弄漂亮点", "expected": "needs_clarification"},
    {"id": "vague-adjustment", "prompt": "再改一下", "expected": "needs_clarification"},
    {"id": "layer-without-scope", "prompt": "画交通", "expected": "needs_clarification"},
    {"id": "contradiction", "prompt": "只显示道路，但加上所有建筑", "expected": "needs_clarification"},
    {"id": "missing-source", "prompt": "画高铁", "expected": "needs_clarification"},
]


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("MAP_E2E_BASE_URL", "http://127.0.0.1:8001"))
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--output-dir", default="outputs/e2e/ambiguous")
    return parser.parse_args()


def login(page, base_url):
    page.goto(f"{base_url}/accounts/login", wait_until="networkidle")
    if page.locator("#username").count():
        page.get_by_label("用户名").fill(os.getenv("MAP_E2E_USERNAME", "123456"))
        page.get_by_label("密码").fill(os.getenv("MAP_E2E_PASSWORD", "123456"))
        page.get_by_role("button", name="登录").click()
    page.wait_for_url("**/mapping/**", wait_until="domcontentloaded")
    page.locator(".composer textarea").wait_for()


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


def wait_for_terminal(page, timeout_seconds, *, leave_status=None):
    deadline = time.monotonic() + timeout_seconds
    if leave_status is not None:
        while time.monotonic() < deadline:
            if page.locator(".status-card strong").inner_text() != leave_status:
                break
            page.wait_for_timeout(250)
    while time.monotonic() < deadline:
        status = page.locator(".status-card strong").inner_text()
        if status in {"等待补充信息", "已完成", "生成失败"}:
            return status
        page.wait_for_timeout(500)
    return page.locator(".status-card strong").inner_text()


def wait_for_label(page, label, timeout_seconds):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if page.locator(".status-card strong").inner_text() == label:
            return label
        page.wait_for_timeout(250)
    return page.locator(".status-card strong").inner_text()


def run_case(page, base_url, case, timeout_seconds, output_dir):
    page.get_by_role("button", name="新建任务").click()
    page.locator(".composer textarea").fill(case["prompt"])
    page.get_by_role("button", name="开始制图").click()
    started_at = time.monotonic()
    final_label = wait_for_terminal(page, timeout_seconds)
    elapsed = round(time.monotonic() - started_at, 2)
    rid = request_id(page)
    detail = fetch_json(page, f"/mapping/api/map-requests/{rid}/")
    messages = fetch_json(page, f"/mapping/api/chat-messages/{rid}/")
    logs = fetch_json(page, f"/mapping/api/process-logs/{rid}/")
    screenshot = output_dir / f"{case['id']}.png"
    page.screenshot(path=str(screenshot), full_page=True)
    return {
        "id": case["id"],
        "prompt": case["prompt"],
        "expected_status": case["expected"],
        "ui_status": final_label,
        "elapsed_seconds": elapsed,
        "request_id": rid,
        "rest_status": detail["status"],
        "business_status": detail["body"].get("status"),
        "run_status": (detail["body"].get("latest_run") or {}).get("status"),
        "rest_body": detail["body"],
        "messages": messages["body"],
        "process_logs": logs["body"],
        "next_step_visible": page.get_by_role("button", name="继续处理").count() == 1,
        "clarification_visible": page.get_by_text("需要补充制图信息").count() == 1,
        "screenshot": str(screenshot),
    }


def run_clarification_continuation(page, base_url, timeout_seconds):
    page.get_by_role("button", name="新建任务").click()
    page.locator(".composer textarea").fill("帮我画个图")
    page.get_by_role("button", name="开始制图").click()
    initial_status = wait_for_terminal(page, timeout_seconds)
    if initial_status != "等待补充信息":
        return {"initial_status": initial_status, "final_status": None, "request_id": request_id(page)}

    page.locator(".composer textarea").fill("请绘制武汉市行政区划图，显示各区边界，标题为武汉市行政区划图。")
    page.get_by_role("button", name="继续处理").click()
    processing_status = wait_for_label(page, "生成中", timeout_seconds)
    final_status = wait_for_terminal(page, timeout_seconds, leave_status="生成中")
    rid = request_id(page)
    detail = fetch_json(page, f"/mapping/api/map-requests/{rid}/")
    return {
        "initial_status": initial_status,
        "processing_status": processing_status,
        "final_status": final_status,
        "request_id": rid,
        "rest_status": detail["status"],
        "business_status": detail["body"].get("status"),
        "run_status": (detail["body"].get("latest_run") or {}).get("status"),
        "has_available_result": detail["body"].get("has_available_result"),
        "assistant_feedback_visible": page.get_by_text("地图已经生成").count() > 0,
    }


def main():
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    page_errors = []
    console_errors = []
    http_errors = []
    results = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        )
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.set_default_timeout(30_000)
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on("response", lambda response: http_errors.append(f"{response.status} {response.url}") if response.status >= 400 else None)
        login(page, args.base_url)
        for case in CASES:
            results.append(run_case(page, args.base_url, case, args.timeout, output_dir))
        continuation = run_clarification_continuation(page, args.base_url, args.timeout)
        report = {
            "cases": results,
            "clarification_continuation": continuation,
            "page_errors": page_errors,
            "console_errors": console_errors,
            "http_errors": http_errors,
        }
        report_path = output_dir / "report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        context.close()
        browser.close()

    failures = [
        item for item in results
        if item["rest_status"] != 200
        or item["business_status"] != item["expected_status"]
        or item["run_status"] != "awaiting_input"
        or item["ui_status"] != "等待补充信息"
        or not item["next_step_visible"]
        or not item["clarification_visible"]
    ]
    if failures or page_errors or console_errors or http_errors:
        raise SystemExit(f"Ambiguous prompt matrix failed; report: {output_dir / 'report.json'}")
    if (
        continuation.get("initial_status") != "等待补充信息"
        or continuation.get("final_status") != "已完成"
        or continuation.get("rest_status") != 200
        or continuation.get("business_status") != "completed"
        or continuation.get("run_status") != "completed"
        or not continuation.get("has_available_result")
    ):
        raise SystemExit(f"Clarification continuation failed; report: {output_dir / 'report.json'}")


if __name__ == "__main__":
    main()
