"""Repeatable desktop/mobile/error-path check. Run as a script, after a build."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os
import shutil
import threading

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=ROOT / "docs"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            executable = os.environ.get("CHROMIUM_BIN") or shutil.which("chromium")
            browser = p.chromium.launch(headless=True, executable_path=executable)
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}")
            page.locator("#app").wait_for(state="visible")
            assert page.title() == "Quant Lab 2 · Research audit"
            assert page.locator("#positions tr").count() == 7
            assert page.locator("#metrics tr").count() == 3
            assert page.locator("#chart path").count() == 1
            assert not errors, errors
            out = ROOT / "artifacts"
            out.mkdir(exist_ok=True)
            page.screenshot(path=out / "dashboard-desktop.png", full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path=out / "dashboard-mobile.png", full_page=True)
            page.route("**/data.json", lambda route: route.fulfill(status=500, body="error"))
            page.reload()
            page.wait_for_function("document.getElementById('status').textContent === 'REPORT UNAVAILABLE'")
            assert page.locator("#loading").is_visible()
            assert not errors, errors
            browser.close()
            print("PASS: desktop/mobile report, chart, JavaScript, overflow and HTTP error state")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
