"""クロスモール(CROSS MALL)への自動ログインと「商品注文分析」CSVのダウンロード。

ログインは1回だけ行い、指定された日付を1日ずつ
「集計対象の開始日=終了日」に設定して検索→CSV出力を繰り返す。
各要素の特定方法は、依頼者から受け取った実際のHTML(outerHTML)に基づく。
"""
import os
import time

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait


class CrossMallError(RuntimeError):
    pass


# ---- 画面要素(受け取ったHTMLより) ----
LOGIN_ID = (By.ID, "mail")
# パスワード欄のid(例: "dd8a78c9")は画面を開くたびに変わる可能性があるため、
# type属性で探す。
LOGIN_PASSWORD = (By.XPATH, "//input[@type='password']")
LOGIN_BUTTON = (By.XPATH, "//input[@type='submit' and @value='ログイン']")
# 左メニュー「注文分析」の見出し(Ext JSのアコーディオン)。
MENU_HEADER = (By.ID, "menu7_header_hd")
# id="menu_icon_sub" は他のメニュー項目と共通の可能性があるため、文字で特定する。
MENU_ITEM = (
    By.XPATH,
    "//div[contains(concat(' ', normalize-space(@class), ' '), ' menu_sub ')"
    " and normalize-space(.)='商品注文']",
)
DATE_FROM = (By.ID, "date_from")
DATE_TO = (By.ID, "date_to")
ITEM_NAME = (By.ID, "item_name")
MAIN_CATEGORY = (By.ID, "main_ctgr1")
SUB_CATEGORY = (By.ID, "sub_ctgr1")
SEARCH_BUTTON = (By.XPATH, "//input[@type='button' and contains(@onclick, 'getList')]")
CSV_BUTTON = (By.ID, "bbtn-btnInnerEl")


def _page_excerpt(driver, length=1000):
    try:
        text = driver.find_element(By.TAG_NAME, "body").text
    except Exception:
        text = ""
    return f"現在の画面のURL: {driver.current_url}\n---画面の内容(抜粋)---\n{text[:length]}"


def _switch_to_frame_with(driver, locator, timeout):
    """locatorの要素がある文書(トップ画面またはiframeの中)に切り替えて要素を返す。

    クロスモールは画面の一部をiframeで表示している可能性があるため、
    トップ画面と、その中のiframe(2階層まで)を順番に探す。
    """
    deadline = time.time() + timeout

    def _search(depth):
        found = driver.find_elements(*locator)
        if found:
            return found[0]
        if depth >= 2:
            return None
        frames = driver.find_elements(By.TAG_NAME, "iframe") + driver.find_elements(
            By.TAG_NAME, "frame"
        )
        for index in range(len(frames)):
            try:
                driver.switch_to.frame(index)
            except Exception:
                continue
            element = _search(depth + 1)
            if element is not None:
                return element
            driver.switch_to.parent_frame()
        return None

    while time.time() < deadline:
        driver.switch_to.default_content()
        element = _search(0)
        if element is not None:
            return element
        time.sleep(1)
    driver.switch_to.default_content()
    return None


def _click(driver, element):
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
    try:
        element.click()
    except Exception:
        driver.execute_script("arguments[0].click();", element)


def _set_text(driver, element, value):
    """入力欄の値を置き換える。キー入力で反映されなければJavaScriptで直接設定する。"""
    element.clear()
    element.send_keys(value)
    if element.get_attribute("value") != value:
        driver.execute_script(
            "arguments[0].value = arguments[1];"
            "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
            element,
            value,
        )
    if element.get_attribute("value") != value:
        raise CrossMallError(
            f"入力欄(id={element.get_attribute('id')})に『{value}』を入力できませんでした。"
        )


def _create_driver(config, download_dir):
    browser = config["browser"]
    prefs = {
        "download.default_directory": os.path.abspath(download_dir),
        # Edgeの「ダウンロード時に保存場所を確認する」設定が有効でも、
        # 保存ダイアログを出さずに指定フォルダへ保存させる。
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
    }
    if browser.get("type", "edge") == "chrome":
        # 開発時の動作確認用。
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service

        options = Options()
        if browser.get("binary_path"):
            options.binary_location = browser["binary_path"]
        options.add_argument("--no-sandbox")
        driver_cls = webdriver.Chrome
    else:
        from selenium.webdriver.edge.options import Options
        from selenium.webdriver.edge.service import Service

        options = Options()
        driver_cls = webdriver.Edge
    options.add_experimental_option("prefs", prefs)
    if browser.get("headless"):
        options.add_argument("--headless=new")
    service = Service(executable_path=browser["edge_driver_path"])
    return driver_cls(service=service, options=options)


def _wait_for_new_file(download_dir, before_files, timeout):
    """ダウンロードが完全に終わった.csvファイルが出現するまで待つ。

    ダウンロード中は「.tmp」「.crdownload」といった仮の名前で保存されるため、
    拡張子が.csvのものだけを対象にし、サイズが変化しなくなってから完了とみなす。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        current = set(os.listdir(download_dir))
        new_csv_files = [f for f in current - before_files if f.lower().endswith(".csv")]
        if new_csv_files:
            path = os.path.join(download_dir, new_csv_files[0])
            size_before = os.path.getsize(path)
            time.sleep(1)
            if os.path.exists(path) and os.path.getsize(path) == size_before:
                return path
        time.sleep(1)
    raise CrossMallError("CSVファイル(.csv)のダウンロードがタイムアウトしました。")


def _wait_until_loaded(driver, timeout):
    """検索結果の読み込み中表示(Ext JSのマスク)が消えるまで待つ。"""

    def _no_visible_mask(d):
        masks = d.find_elements(By.CSS_SELECTOR, ".x-mask-msg, .x-mask-loading")
        return not any(m.is_displayed() for m in masks)

    try:
        WebDriverWait(driver, timeout).until(_no_visible_mask)
    except TimeoutException:
        raise CrossMallError(
            f"検索結果の表示が{timeout}秒以内に終わりませんでした。\n{_page_excerpt(driver)}"
        )


class CrossMallSession:
    def __init__(self, config, password):
        self.config = config
        self.password = password
        self.download_dir = config["browser"]["download_dir"]
        os.makedirs(self.download_dir, exist_ok=True)
        self.driver = _create_driver(config, self.download_dir)
        self.wait = WebDriverWait(self.driver, 30)

    def close(self):
        self.driver.quit()

    def login(self):
        d = self.driver
        d.get(self.config["site"]["login_url"])
        try:
            login_id = self.wait.until(EC.presence_of_element_located(LOGIN_ID))
        except TimeoutException:
            raise CrossMallError(f"ログイン画面が表示されませんでした。\n{_page_excerpt(d)}")
        login_id.clear()
        login_id.send_keys(self.config["site"]["login_id"])
        password = d.find_element(*LOGIN_PASSWORD)
        password.clear()
        password.send_keys(self.password)
        _click(d, d.find_element(*LOGIN_BUTTON))

        # ログイン処理が終わり、左メニューが表示されるまで待ってから次に進む。
        if _switch_to_frame_with(d, MENU_HEADER, timeout=30) is None:
            raise CrossMallError(
                "ログインに失敗している可能性があります(ログイン後の画面に進めませんでした)。\n"
                "ログインIDとパスワードを確認してください。\n"
                f"{_page_excerpt(d, 1500)}"
            )

    def open_order_analysis(self):
        """左メニュー「注文分析」→「商品注文」を開き、検索条件の画面を表示する。"""
        d = self.driver
        header = _switch_to_frame_with(d, MENU_HEADER, timeout=10)
        item = _switch_to_frame_with(d, MENU_ITEM, timeout=1)
        # 「注文分析」がすでに開いている状態で見出しを押すと閉じてしまうため、
        # 「商品注文」が見えていないときだけ見出しを押す。
        if item is None or not item.is_displayed():
            if header is None:
                raise CrossMallError(f"メニュー『注文分析』が見つかりません。\n{_page_excerpt(d)}")
            _switch_to_frame_with(d, MENU_HEADER, timeout=1)
            _click(d, header)
            time.sleep(1)
            item = _switch_to_frame_with(d, MENU_ITEM, timeout=10)
        if item is None:
            raise CrossMallError(f"メニュー『商品注文』が見つかりません。\n{_page_excerpt(d)}")
        _click(d, item)

        if _switch_to_frame_with(d, DATE_FROM, timeout=30) is None:
            raise CrossMallError(
                f"『商品注文分析』の画面が表示されませんでした。\n{_page_excerpt(d)}"
            )

    def download_day(self, day):
        """dayの1日分(開始日=終了日)を検索してCSVを出力し、ダウンロードしたパスを返す。"""
        d = self.driver
        browser = self.config["browser"]
        search = self.config["search"]
        date_str = day.strftime("%Y/%m/%d")

        if _switch_to_frame_with(d, DATE_FROM, timeout=10) is None:
            raise CrossMallError(f"集計対象の日付欄が見つかりません。\n{_page_excerpt(d)}")
        _set_text(d, d.find_element(*DATE_FROM), date_str)
        _set_text(d, d.find_element(*DATE_TO), date_str)
        _set_text(d, d.find_element(*ITEM_NAME), search["item_name"])

        Select(d.find_element(*MAIN_CATEGORY)).select_by_value(search["main_category_value"])
        # カテゴリ1を変えると、カテゴリ2の選択肢が作り直される(onchange="chng_ctgr(2)")。
        # 目的の選択肢が現れるまで待ってから選ぶ。
        sub_value = search["sub_category_value"]
        try:
            WebDriverWait(d, 15).until(
                lambda drv: drv.find_elements(
                    By.CSS_SELECTOR, f"#sub_ctgr1 option[value='{sub_value}']"
                )
            )
        except TimeoutException:
            raise CrossMallError(f"カテゴリ2に選択肢(値 {sub_value})が表示されませんでした。")
        time.sleep(0.5)
        Select(d.find_element(*SUB_CATEGORY)).select_by_value(sub_value)

        _click(d, d.find_element(*SEARCH_BUTTON))
        # 押した直後はまだ読み込み中の表示が出ていないことがあるため、少し待ってから確認する。
        time.sleep(1)
        _wait_until_loaded(d, browser.get("search_timeout_seconds", 180))
        # 前の日の検索結果が残ったままCSVを出力しないよう、表示完了後も少し待つ。
        time.sleep(browser.get("wait_after_search_seconds", 3))

        csv_button = _switch_to_frame_with(d, CSV_BUTTON, timeout=10)
        if csv_button is None:
            raise CrossMallError(f"『CSV出力』ボタンが見つかりません。\n{_page_excerpt(d)}")
        before_files = set(os.listdir(self.download_dir))
        _click(d, csv_button)
        downloaded = _wait_for_new_file(self.download_dir, before_files, timeout=120)
        # CSV出力の後に再び検索条件の画面へ戻っておく。
        _switch_to_frame_with(d, DATE_FROM, timeout=10)
        return downloaded
