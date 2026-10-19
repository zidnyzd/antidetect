"""End-to-end check: official ixBrowser SDK -> our API -> engine -> Selenium.

Run with the repo venv, after `python3 -m antidetect serve`:
    venv/bin/python scripts/selftest.py
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

try:
    from ixbrowser_local_api import IXBrowserClient, Profile, Fingerprint
except ImportError:
    from ixbrowser_local_api.client import IXBrowserClient
    from ixbrowser_local_api.entities import Profile, Fingerprint

PAGE = (REPO / "assets" / "fptest.html").as_uri()


def main():
    client = IXBrowserClient()
    try:
        client.session.get("http://127.0.0.1:53200/health", timeout=5).raise_for_status()
    except Exception:
        sys.exit("API server is not running on 127.0.0.1:53200")

    profile = Profile()
    profile.name = "selftest"
    profile.set_blank_page()
    profile.random_color()
    profile.set_fingerprint_config(
        {
            "platform": "Windows",
            "system_version": "11",
            "hardware_concurrency": 8,
            "device_memory": 8,
            "timezone": "Asia/Jakarta",
            "language": "en-US",
        }
    )
    created = client.create_profile(profile)
    if created is None:
        sys.exit(f"create failed code={client.code} message={client.message}")
    pid = created["profile_id"]
    print("created:", created)

    opened = client.open_profile(pid, cookies_backup=False, load_profile_info_page=False)
    if opened is None:
        sys.exit(f"open failed code={client.code} message={client.message}")
    print("open:", opened)

    options = Options()
    options.add_experimental_option("debuggerAddress", opened["debugging_address"])
    driver = Chrome(service=Service(opened["webdriver"]), options=options)
    driver.get(PAGE)
    print("FINGERPRINT:", driver.find_element("css selector", "pre").text)
    driver.service.stop()

    print("closed:", client.close_profile(pid))


if __name__ == "__main__":
    main()
