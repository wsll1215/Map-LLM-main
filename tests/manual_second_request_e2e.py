"""End-to-end regression for a second map adjustment.

The browser status is only a presentation layer. This test also verifies the
same request through the REST status/artifact endpoints and compares the
stored PNG bytes, so a stale v1 preview cannot be reported as a successful v2.
"""

import json
import hashlib
import time

from playwright.sync_api import sync_playwright


BASE_URL = "http://127.0.0.1:8001"
TERMINAL_STATUSES = {"completed", "failed"}


def wait_for_request_terminal(page, request_id, timeout=180):
    deadline = time.monotonic() + timeout
    latest = None
    while time.monotonic() < deadline:
        latest = page.evaluate(
            """async (id) => {
                const response = await fetch(`/mapping/api/map-requests/${id}/`, {
                    credentials: "same-origin",
                    headers: {Accept: "application/json"},
                });
                return await response.json();
            }""",
            request_id,
        )
        if latest.get("status") in TERMINAL_STATUSES:
            return latest
        page.wait_for_timeout(500)
    raise AssertionError(f"request {request_id} did not reach a terminal state: {latest}")


def read_artifacts(page, request_id):
    return page.evaluate(
        """async (id) => {
            const response = await fetch(`/mapping/api/generated-maps/${id}/`, {
                credentials: "same-origin",
                headers: {Accept: "application/json"},
            });
            return await response.json();
        }""",
        request_id,
    )


def artifact_hashes(page, maps):
    hashes = []
    for item in maps:
        digest = page.evaluate(
            """async (url) => {
                const bytes = await (await fetch(url, {credentials: "same-origin"})).arrayBuffer();
                const hash = await crypto.subtle.digest("SHA-256", bytes);
                return Array.from(new Uint8Array(hash)).map((value) => value.toString(16).padStart(2, "0")).join("");
            }""",
            item["file_path"],
        )
        hashes.append({"version": item["version"], "sha256": digest, "size": item.get("file_size")})
    return hashes


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        )
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        console_errors = []
        failed_requests = []
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on("requestfailed", lambda request: failed_requests.append({"url": request.url, "failure": request.failure}))

        page.goto(f"{BASE_URL}/accounts/login", wait_until="networkidle")
        page.fill('input[name="username"]', "123456")
        page.fill('input[name="password"]', "123456")
        page.locator("form.auth-form button[type='submit']").click()
        page.wait_for_url("**/mapping/")
        page.wait_for_load_state("networkidle")

        prompt = page.locator(".composer textarea")
        prompt.fill("帮我绘制北京的道路地图")
        page.get_by_role("button", name="开始制图").click()

        page.wait_for_function(
            """() => /^#\\d+$/.test(document.querySelector('.request-id')?.textContent?.trim() || '')"""
        )
        request_id = int(page.locator(".request-id").inner_text().lstrip("#"))
        first_api = wait_for_request_terminal(page, request_id)
        first_maps_payload = read_artifacts(page, request_id)
        first_maps = first_maps_payload.get("maps", [])
        first_status = page.locator(".map-meta .status").inner_text()

        if first_status != "已完成":
            raise AssertionError(
                f"first request must complete before adjustment, got {first_status!r}: {first_api}"
            )

        second_immediate = {}
        prompt.fill("标注清华大学的位置")
        page.get_by_role("button", name="发送调整").click()
        page.wait_for_timeout(300)
        second_immediate = {
            "button_text": page.locator(".composer button").inner_text(),
            "button_disabled": page.locator(".composer button").is_disabled(),
            "status": page.locator(".map-meta .status").inner_text(),
            "feedback": page.locator(".task-status").inner_text(),
        }
        second_api = wait_for_request_terminal(page, request_id)
        second_maps_payload = read_artifacts(page, request_id)
        second_maps = second_maps_payload.get("maps", [])
        page.wait_for_function(
            """(expected) => document.querySelectorAll('.file-row').length >= expected""",
            arg=len(second_maps),
        )

        result = {
            "first_status": first_status,
            "second_immediate": second_immediate,
            "request_id": request_id,
            "first_api": first_api,
            "first_maps": first_maps,
            "second_api": second_api,
            "second_maps": second_maps,
            "terminal_status": page.locator(".map-meta .status").inner_text(),
            "history_count": page.locator(".history-item").count(),
            "result_files": page.locator(".file-row").count(),
            "v2_visible": page.get_by_text("地图文件 v2").count() > 0,
            "error": page.locator(".error-box").inner_text() if page.locator(".error-box").count() else "",
            "console_errors": console_errors,
            "failed_requests": failed_requests,
        }
        result["hashes"] = artifact_hashes(page, second_maps or first_maps)
        result["v1_v2_differ"] = len(result["hashes"]) >= 2 and result["hashes"][0]["sha256"] != result["hashes"][1]["sha256"]
        result["unexpected_failed_requests"] = [
            item for item in failed_requests
            if not (item["failure"] and "aborted" in item["failure"].lower())
        ]
        print(json.dumps(result, ensure_ascii=False, indent=2))
        page.screenshot(path="outputs/manual_second_request_e2e.png", full_page=True)
        if first_api["status"] != "completed":
            raise AssertionError(f"first map did not complete: {first_api}")
        if second_api is None or second_api["status"] != "completed":
            raise AssertionError(f"second adjustment did not complete: {second_api}")
        if [item["version"] for item in second_maps] != [2, 1] and [item["version"] for item in second_maps] != [1, 2]:
            raise AssertionError(f"expected v1 and v2 artifacts, got: {second_maps}")
        if not result["v1_v2_differ"]:
            raise AssertionError(f"v1/v2 PNG hashes are identical: {result['hashes']}")
        if result["unexpected_failed_requests"]:
            raise AssertionError(f"unexpected browser request failures: {result['unexpected_failed_requests']}")
        browser.close()


if __name__ == "__main__":
    main()
