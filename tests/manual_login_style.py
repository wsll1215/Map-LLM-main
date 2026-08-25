from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> None:
    screenshot = Path(__file__).resolve().parents[1] / "outputs" / "manual_login_style.png"
    screenshot.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path="C:/Program Files/Google/Chrome/Application/chrome.exe",
        )
        page = browser.new_page(viewport={"width": 1186, "height": 698})
        page.goto("http://127.0.0.1/accounts/login", wait_until="networkidle")

        assert page.locator("link[rel='stylesheet']").count() == 4
        assert page.locator(".auth-shell").is_visible()
        assert page.locator(".auth-submit").is_visible()
        assert page.locator(".auth-shell").evaluate(
            "element => getComputedStyle(element).display"
        ) == "grid"
        submit_background = page.locator(".auth-submit").evaluate(
            "element => getComputedStyle(element).backgroundImage"
        )
        assert "gradient" in submit_background

        page.screenshot(path=str(screenshot), full_page=True)
        print("login_style=ok")
        print(f"screenshot={screenshot}")
        browser.close()


if __name__ == "__main__":
    main()
