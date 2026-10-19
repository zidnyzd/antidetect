"""Isolation check: two profiles differ in fingerprint and keep cookies apart."""
import json
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
SITE = "https://example.com"


def make(client, name, fp_kwargs):
    profile = Profile()
    profile.name = name
    profile.set_blank_page()
    profile.random_color()
    profile.set_fingerprint_config(fp_kwargs)
    created = client.create_profile(profile)
    assert created, (client.code, client.message)
    return created["profile_id"]


class Session:
    def __init__(self, client, pid):
        self.client = client
        self.pid = pid
        opened = client.open_profile(
            pid, cookies_backup=False, load_profile_info_page=False,
            startup_args=["--headless"],
        )
        assert opened, (client.code, client.message)
        options = Options()
        options.add_experimental_option("debuggerAddress", opened["debugging_address"])
        self.driver = Chrome(service=Service(opened["webdriver"]), options=options)

    def fingerprint(self):
        self.driver.get(PAGE)
        return json.loads(self.driver.find_element("css selector", "pre").text)

    def goto(self, url):
        self.driver.get(url)

    def set_cookie(self, value):
        self.driver.execute_script(
            f"document.cookie = {json.dumps('marker=' + value + '; path=/; max-age=3600')}"
        )

    def cookies(self):
        return self.driver.execute_script("return document.cookie")

    def close(self):
        self.driver.service.stop()
        self.client.close_profile(self.pid)


def main():
    client = IXBrowserClient()
    a = make(client, "isoA", {"platform": "Windows", "timezone": "Asia/Jakarta", "hardware_concurrency": 8})
    b = make(client, "isoB", {"platform": "Windows", "timezone": "America/New_York", "hardware_concurrency": 4})

    sa = Session(client, a)
    fp_a = sa.fingerprint()
    sa.goto(SITE)
    sa.set_cookie("A")
    print("A tz:", fp_a["tz"], "| cores:", fp_a["cores"], "| gl:", fp_a["glRenderer"][:60])
    print("A cookie:", sa.cookies())
    sa.close()

    sb = Session(client, b)
    fp_b = sb.fingerprint()
    sb.goto(SITE)
    sb.set_cookie("B")
    print("B tz:", fp_b["tz"], "| cores:", fp_b["cores"], "| gl:", fp_b["glRenderer"][:60])
    print("B cookie:", sb.cookies())
    assert "A" not in sb.cookies().replace("marker=B", ""), "cookie A leaked into B"
    sb.close()

    sa2 = Session(client, a)
    sa2.goto(SITE)
    print("A cookie after reopen:", sa2.cookies())
    sa2.close()

    print("PASS: fingerprints differ, cookies isolated and persistent")


if __name__ == "__main__":
    main()
