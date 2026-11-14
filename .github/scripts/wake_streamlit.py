import os
import re
import sys

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

WAKE_BUTTON = re.compile(r"get this app back up", re.IGNORECASE)

url = os.environ.get("APP_URL", "")
if not url:
    print("Secrets に STREAMLIT_APP_URL（ダッシュボードのURL）が設定されていません")
    sys.exit(1)

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(10_000)

    wake = page.get_by_role("button", name=WAKE_BUTTON)
    if wake.count() > 0:
        print("スリープ中だったので起こします")
        wake.first.click()
        try:
            wake.first.wait_for(state="detached", timeout=300_000)
        except PlaywrightTimeoutError:
            pass
        # 起動後にアプリ本体への接続（＝アクセス）が成立するまで開いたままにする
        page.wait_for_timeout(60_000)
        if page.get_by_role("button", name=WAKE_BUTTON).count() > 0:
            print("5分待ってもアプリが起動しませんでした")
            browser.close()
            sys.exit(1)
        print("起動しました")
    else:
        # 単純なHTTPアクセスではスリープまでの時間がリセットされないため、
        # 実際のブラウザで開いてアプリとの接続をしばらく保つ
        print("起きていました（アクセスしてスリープまでの時間をリセット）")
        page.wait_for_timeout(30_000)

    browser.close()
