import re
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> None:
    output = Path(__file__).resolve().parents[1] / "output" / "playwright"
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        )
        api = playwright.request.new_context()
        login = api.get("http://127.0.0.1:8001/accounts/login")
        csrf = re.search(r'name="csrfmiddlewaretoken"[^>]+value="([^"]+)', login.text())
        if not csrf:
            raise AssertionError("登录页没有 CSRF token")
        response = api.post(
            "http://127.0.0.1:8001/accounts/login",
            form={
                "csrfmiddlewaretoken": csrf.group(1),
                "username": "123456",
                "password": "123456",
            },
            max_redirects=0,
        )
        if response.status not in (302, 303):
            raise AssertionError(f"登录失败: {response.status}")

        context = browser.new_context(
            storage_state=api.storage_state(), viewport={"width": 1440, "height": 900}
        )
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://127.0.0.1:8001/mapping/", wait_until="networkidle")
        page.wait_for_selector(".map-canvas")
        page.screenshot(path=str(output / "trace-ui-check.png"), full_page=True)
        print("page_url", page.url)
        print("scripts", page.locator("script").evaluate_all("nodes => nodes.map(node => node.src)"))
        print("workbench", page.get_by_text("智能制图工作台").count())
        print("canvas", page.locator(".map-canvas canvas").count())
        print("trace_button", page.get_by_role("button", name="打开 Trace").count())
        print("page_errors", errors)
        if errors:
            raise AssertionError(errors)
        if page.locator(".history-item").count():
            page.locator(".history-item").first.click()
            page.wait_for_timeout(5000)
            print("historical_canvas", page.locator(".map-canvas canvas").count())
            print("historical_status", page.locator(".status-card strong").inner_text())
            print("historical_log_count", page.locator(".log-count").first.inner_text())
            print("historical_trace_count", page.locator(".trace-count").inner_text())
            trace_button = page.get_by_role("button", name="打开 Trace")
            print("historical_trace_enabled", trace_button.is_enabled())
            if trace_button.is_enabled():
                trace_button.click()
                page.wait_for_timeout(800)
                print("trace_drawer", page.get_by_text("调用链详情").count())
                print("trace_rows", page.locator(".trace-row").count())
                trace_pane = page.locator(".trace-visual-pane")
                dimensions = trace_pane.evaluate(
                    "element => ({ scrollHeight: element.scrollHeight, clientHeight: element.clientHeight })"
                )
                print("trace_scroll_dimensions", dimensions)
                trace_pane.evaluate("element => element.scrollTo({ top: element.scrollHeight })")
                page.wait_for_timeout(150)
                page.locator(".trace-row").last.scroll_into_view_if_needed()
                print("trace_last_row", page.locator(".trace-row").last.inner_text())
                page.screenshot(path=str(output / "trace-drawer-check.png"), full_page=True)
            page.screenshot(path=str(output / "trace-ui-history-check.png"), full_page=True)
        context.close()
        api.dispose()
        browser.close()


if __name__ == "__main__":
    main()
