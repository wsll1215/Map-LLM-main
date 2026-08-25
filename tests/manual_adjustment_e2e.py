import json
import time

from playwright.sync_api import sync_playwright


BASE_URL = "http://127.0.0.1:8001"


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
        page.on("requestfailed", lambda request: failed_requests.append(f"{request.url}: {request.failure}"))

        page.goto(f"{BASE_URL}/accounts/login", wait_until="networkidle")
        page.fill('input[name="username"]', "123456")
        page.fill('input[name="password"]', "123456")
        page.locator("form.auth-form button[type='submit']").click()
        page.wait_for_url("**/mapping/")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1_000)

        history_item = page.locator(".history-item", has_text="已完成").first
        history_item.click()
        page.wait_for_timeout(1_000)
        page.wait_for_function(
            """() => /^#\\d+$/.test(document.querySelector('.request-id')?.textContent?.trim() || '')"""
        )
        request_id = int(page.locator(".request-id").inner_text().lstrip("#"))
        textarea = page.locator(".composer textarea")
        textarea.fill("把高铁路线画出来")
        button = page.get_by_role("button", name="发送调整")
        before = {"disabled": button.is_disabled(), "status": page.locator(".map-meta .status").inner_text()}
        button.click()
        page.wait_for_timeout(300)
        after_click = {
            "button_text": page.locator(".composer button").inner_text(),
            "button_disabled": page.locator(".composer button").is_disabled(),
            "status": page.locator(".map-meta .status").inner_text(),
            "feedback": page.locator(".task-status").inner_text(),
        }

        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            status = page.locator(".map-meta .status").inner_text()
            if status in {"已完成", "生成失败"}:
                break
            page.wait_for_timeout(1_000)

        artifacts = read_artifacts(page, request_id)
        maps = artifacts.get("maps", [])
        retained_versions = [item["version"] for item in maps if item.get("file_exists") is not False]
        retained_result = page.locator(".result-strip").inner_text() if page.locator(".result-strip").count() else ""
        can_continue = page.get_by_role("button", name="发送调整").count() == 1

        result = {
            "request_id": request_id,
            "before": before,
            "after_click": after_click,
            "terminal_status": page.locator(".map-meta .status").inner_text(),
            "error": page.locator(".error-box").inner_text() if page.locator(".error-box").count() else "",
            "latest_feedback": page.locator(".assistant-card").last.inner_text() if page.locator(".assistant-card").count() else "",
            "artifacts": maps,
            "retained_versions": retained_versions,
            "retained_result": retained_result,
            "can_continue": can_continue,
            "logs": page.locator(".log-line").count(),
            "console_errors": console_errors,
            "failed_requests": failed_requests,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        page.screenshot(path="outputs/manual_adjustment_e2e.png", full_page=True)
        if result["terminal_status"] != "生成失败":
            raise AssertionError(f"expected failed adjustment, got {result['terminal_status']}")
        if not result["error"] or not result["retained_versions"]:
            raise AssertionError(f"failure feedback or retained artifact missing: {result}")
        if "本轮调整失败，已保留" not in result["retained_result"] or not can_continue:
            raise AssertionError(f"failed task did not preserve adjustment workflow: {result}")
        browser.close()


if __name__ == "__main__":
    main()
