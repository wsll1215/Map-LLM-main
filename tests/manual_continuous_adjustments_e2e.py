"""Verify multiple adjustments in one session and reload recovery."""

import json
import os
import time

from playwright.sync_api import sync_playwright


BASE_URL = os.getenv("MAP_E2E_BASE_URL", "http://127.0.0.1:8001")
TERMINAL = {"completed", "failed"}


def request_status(page, request_id):
    return page.evaluate(
        """async (id) => await (await fetch(`/mapping/api/map-requests/${id}/`, {
            credentials: 'same-origin', headers: {Accept: 'application/json'}
        })).json()""",
        request_id,
    )


def wait_terminal(page, request_id, timeout=180):
    deadline = time.monotonic() + timeout
    latest = None
    while time.monotonic() < deadline:
        latest = request_status(page, request_id)
        if latest.get("status") in TERMINAL:
            return latest
        page.wait_for_timeout(500)
    raise AssertionError(f"request {request_id} did not finish: {latest}")


def artifacts(page, request_id):
    return page.evaluate(
        """async (id) => (await (await fetch(`/mapping/api/generated-maps/${id}/`, {
            credentials: 'same-origin', headers: {Accept: 'application/json'}
        })).json()).maps || []""",
        request_id,
    )


def submit_adjustment(page, text, request_id):
    page.locator(".composer textarea").fill(text)
    page.get_by_role("button", name="发送调整").click()
    page.wait_for_timeout(300)
    immediate = {
        "button": page.locator(".composer button").inner_text(),
        "disabled": page.locator(".composer button").is_disabled(),
        "status": page.locator(".map-meta .status").inner_text(),
    }
    terminal = wait_terminal(page, request_id)
    maps = artifacts(page, request_id)
    return {"prompt": text, "immediate": immediate, "terminal": terminal, "versions": [item["version"] for item in maps], "maps": maps}


def main():
    username = os.getenv("MAP_E2E_USERNAME")
    password = os.getenv("MAP_E2E_PASSWORD")
    if not username or not password:
        raise SystemExit("Set MAP_E2E_USERNAME and MAP_E2E_PASSWORD before running this test.")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page_errors = []
        console_errors = []
        http_errors = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on("response", lambda response: http_errors.append(f"{response.status} {response.url}") if response.status >= 400 else None)

        page.goto(f"{BASE_URL}/accounts/login", wait_until="networkidle")
        page.get_by_label("用户名").fill(username)
        page.get_by_label("密码").fill(password)
        page.get_by_role("button", name="登录").click()
        page.wait_for_url("**/mapping/**", wait_until="domcontentloaded")
        page.locator(".composer textarea").fill("请使用 data/data4/Henan.shp 绘制河南省行政区划图，显示省界，标题为河南省行政区划图。")
        page.get_by_role("button", name="开始制图").click()
        page.wait_for_function("""() => /^#\\d+$/.test(document.querySelector('.request-id')?.textContent?.trim() || '')""")
        request_id = int(page.locator(".request-id").inner_text().lstrip("#"))
        first = wait_terminal(page, request_id)
        first_maps = artifacts(page, request_id)

        style = submit_adjustment(page, "把当前地图边界线改为深绿色，并把标题改为河南省行政区划图（调整版）。", request_id)
        scale = submit_adjustment(page, "添加比例尺。", request_id)

        page.reload(wait_until="networkidle")
        history = page.locator(".history-item", has_text=f"#{request_id}")
        history.wait_for()
        history.click()
        page.locator(".stored-map-preview").wait_for()
        restored = {
            "preview": page.locator(".stored-map-preview").count() == 1,
            "result_files": page.locator(".file-row").count(),
            "status": page.locator(".map-meta .status").inner_text(),
            "send_adjustment": page.get_by_role("button", name="发送调整").count() == 1,
        }
        result = {
            "request_id": request_id,
            "first": {"status": first.get("status"), "versions": [item["version"] for item in first_maps]},
            "style": style,
            "scale": scale,
            "restored": restored,
            "page_errors": page_errors,
            "console_errors": console_errors,
            "http_errors": http_errors,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        page.screenshot(path="outputs/manual_continuous_adjustments_e2e.png", full_page=True)
        browser.close()

    assert result["first"]["status"] == "completed", result
    assert style["terminal"]["status"] == "completed", result
    assert scale["terminal"]["status"] == "completed", result
    assert style["versions"] == [2, 1], result
    assert scale["versions"] == [3, 2, 1], result
    assert all(restored.values()), result
    assert not result["page_errors"] and not result["console_errors"] and not result["http_errors"], result


if __name__ == "__main__":
    main()
