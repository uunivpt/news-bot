"""Browser regression for the sticky header. Requires Playwright and Chromium.

Run: python scripts/check_scroll_layout.py
Set BROWSER_EXECUTABLE to override /usr/bin/chromium.
External requests (including ads) are blocked to isolate the site's layout.
"""
import functools
import http.server
import os
from pathlib import Path
import threading

from playwright.sync_api import sync_playwright


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main():
    root = Path(__file__).resolve().parents[1] / "public"
    handler = functools.partial(QuietHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("BROWSER_EXECUTABLE", "/usr/bin/chromium"),
                args=["--no-sandbox"],
            )
            for width in (390, 768, 1280, 1440):
                page = browser.new_page(viewport={"width": width, "height": 800}, service_workers="block")
                page.route("**/*", lambda route: route.continue_()
                           if route.request.url.startswith(origin + "/") else route.abort())
                for route in ("/", "/#/c/india"):
                    page.goto(origin + route, wait_until="domcontentloaded")
                    page.wait_for_function("document.querySelector('#app h1') && document.querySelector('#nav a')")
                    for theme in ("light", "dark"):
                        page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
                        page.evaluate("window.scrollTo(0, 0)")
                        page.wait_for_timeout(400)
                        initial = page.locator("#hd").bounding_box()["height"]
                        page.evaluate("window.scrollTo(0, 300)")
                        page.wait_for_function("window.scrollY > 20")
                        page.wait_for_timeout(400)
                        header = page.locator("#hd").bounding_box()
                        assert header["height"] <= initial + 2, (width, route, theme, initial, header)
                        assert abs(header["y"]) <= 1, (width, route, theme, header)
                        page.evaluate("window.scrollTo(0, 0)")
                        page.wait_for_timeout(400)
                        assert abs(page.locator("#hd").bounding_box()["height"] - initial) <= 2
                        print(f"PASS {width}px {route} {theme}: header {initial}px -> {header['height']}px")
                page.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
