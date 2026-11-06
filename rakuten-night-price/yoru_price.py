# -*- coding: utf-8 -*-
"""楽天 夜売価: Excelで指定した時刻に、ビッグボス楽天の価格だけを変えて出品し、指定の時刻に元の価格へ戻して出品する。

タスクスケジューラから5分ごとに起動する。やることがなければ、Chromeに触らず1秒ほどで終わる。
Chromeは --remote-debugging-port=9222 で、クロスモールにログイン済みのものを使う(予約テキスト削除と同じ)。

Excel(1枚目のシート、2行目から)で読むのは A〜D列だけ。
  A 商品管理番号 / B 変更後の価格 / C 変更する日時 / D 戻す日時
  F列・G列などはメモ。プログラムは一切読まない(読み込み範囲を A〜D列に限定している)。

安全のための決まり:
  - 書き換えるのは、ビッグボス楽天(店舗ID 5255)の店舗別詳細編集の「通常購入販売価格」(mall_rakuten[unit_price])だけ。
    編集を開く直前に、編集対象が 5255 になっていることを毎回確かめる。
  - 出品は「一括出品処理」で、出品先のチェックがビッグボス楽天だけであることを確かめてから行う。違えば中止。
  - 元の価格は、変える直前にクロスモールから読み取り、state.json に記録する。戻すときはこの記録を使う(Excelの価格は使わない)。
  - 戻すときに、今の価格が変更後の価格と違えば(誰かが手で変えた等)、戻さずに知らせる。

使い方:
  python yoru_price.py                     通常(タスクスケジューラから)
  python yoru_price.py --dry-run           画面を読むだけ。価格の保存も出品もしない
  python yoru_price.py --dry-run --now "2026-11-20 21:55"   その時刻になったつもりで、何をするか確かめる
  python yoru_price.py --list              Excelの読み取り結果と、各行の状態を表示するだけ(Chromeに触らない)
  python yoru_price.py --snapshot 商品管理番号   全店舗の価格欄を読み取って記録し、前回の記録と比べる(読むだけ)
"""
import argparse
import datetime
import glob
import json
import logging
import os
import re
import subprocess
import sys
import time
import traceback
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("YORU_CDP_PORT", "9222"))
BASE = "http://127.0.0.1:%d" % PORT
CHROME_EXES = [r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
               r"C:\Program Files\Google\Chrome\Application\chrome.exe"]
CHROME_ARGS = ["--remote-debugging-port=%d" % PORT, r"--user-data-dir=C:\chrome-claude-profile"]
ITEM_BATCH_URL = os.environ.get("YORU_ITEM_BATCH_URL", "https://www.crossmall.jp/item_batch/?mId=&umId=0")
SITE_KEY = os.environ.get("YORU_SITE_KEY", "crossmall.jp")

RAKUTEN_SHOP = "5255"
RAKUTEN_SHOP_NAME = "ビッグボス楽天"
PRICE_SEL = "#mall_rakuten_unit_price"
MARK_ID = "1100"
ALL_SHOPS = [("5255", "ビッグボス楽天"), ("5256", "ドリームクラフト"), ("5257", "Yahoo"),
             ("8581", "wine.com"), ("8014", "Wowma"), ("9365", "Wowma2店舗目")]

DEFAULT_CONFIG = {
    "excel_folder": r"D:\楽天claude\楽天夜売価",
    "excel_file": "",           # 空なら、フォルダ内の .xlsx が1つだけのとき、それを使う
    "early_minutes": 5,         # 楽天への反映に数分かかるため、指定時刻の何分前から処理を始めるか
    "min_ratio": 0.5,           # 変更後の価格が、元の価格のこの割合より安ければ、打ち間違いとみなして実行しない
    "max_items": 50,            # 1回に処理する上限。超えたら実行しない
    "max_attempts": 3,          # 同じ行がこの回数失敗したら、それ以上やり直さず「要確認」にする
    "avoid": ["06:10-06:50"],   # この時間帯は動かない(毎朝6:15の予約テキスト削除とぶつからないように)
}

ATTENTION_FILE = "要確認.txt"


class LoginRequired(Exception):
    pass


# ================================================================ 設定・Excel・記録
def load_config():
    cfg = dict(DEFAULT_CONFIG)
    p = os.path.join(HERE, "config.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8-sig") as f:
            cfg.update(json.load(f))
    return cfg


def find_excel(cfg):
    folder = cfg["excel_folder"]
    if cfg.get("excel_file"):
        return os.path.join(folder, cfg["excel_file"])
    files = [f for f in glob.glob(os.path.join(folder, "*.xlsx"))
             if not os.path.basename(f).startswith("~$")]  # ~$ はExcelを開いている間の一時ファイル
    if len(files) != 1:
        raise RuntimeError("フォルダ %s の .xlsx が %d 個あります。1つにするか、config.json の excel_file に"
                           "ファイル名を書いてください: %s" % (folder, len(files), [os.path.basename(f) for f in files]))
    return files[0]


def parse_price(v):
    if isinstance(v, bool) or v is None:
        raise ValueError("価格が空欄です")
    if isinstance(v, (int, float)):
        if float(v) != int(v):
            raise ValueError("価格が整数ではありません: %s" % v)
        n = int(v)
    else:
        s = str(v).strip().replace(",", "").replace("，", "").replace("円", "").replace("¥", "")
        s = s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
        if not re.fullmatch(r"\d+", s):
            raise ValueError("価格が数字ではありません: %s" % v)
        n = int(s)
    if n <= 0 or n > 999999999:
        raise ValueError("価格の範囲がおかしいです: %s" % v)
    return n


def parse_dt(v, label):
    if isinstance(v, datetime.datetime):
        return v.replace(second=0, microsecond=0)
    if isinstance(v, datetime.date):
        return datetime.datetime(v.year, v.month, v.day)
    if v is None or str(v).strip() == "":
        raise ValueError("%sが空欄です" % label)
    s = str(v).strip().replace("　", " ")
    s = re.sub(r"\s+", " ", s)
    for fmt in ("%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(s, fmt)
        except ValueError:
            pass
    raise ValueError("%sが読めません(例 2026/11/20 21:00): %s" % (label, v))


def read_excel(path):
    """A〜D列だけ読む。戻り値: (正常な行のリスト, エラーのリスト)。F列・G列は読み込み範囲に入れていない。"""
    import openpyxl  # 使うときだけ読み込む(メモリー節約)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows, errors = [], []
    try:
        ws = wb.worksheets[0]
        for i, (a, b, c, d) in enumerate(ws.iter_rows(min_row=2, min_col=1, max_col=4, values_only=True), start=2):
            if all(x is None or str(x).strip() == "" for x in (a, b, c, d)):
                continue
            try:
                code = str(a or "").strip()
                if not code:
                    raise ValueError("商品管理番号が空欄です")
                if not re.fullmatch(r"[0-9A-Za-z_\-]+", code):
                    raise ValueError("商品管理番号に使えない文字があります: %s" % code)
                price = parse_price(b)
                start = parse_dt(c, "変更する日時")
                end = parse_dt(d, "戻す日時")
                if end <= start:
                    raise ValueError("戻す日時(%s)が、変更する日時(%s)と同じか前です" % (fmt_dt(end), fmt_dt(start)))
                rows.append({"row": i, "code": code, "price": price, "start": start, "end": end,
                             "key": "%s|%s|%s" % (code, start.strftime("%Y%m%d%H%M"), end.strftime("%Y%m%d%H%M"))})
            except ValueError as e:
                errors.append("Excel %d行目: %s" % (i, e))
    finally:
        wb.close()
    # 同じ商品で期間が重なる行は、どちらも実行しない
    bad = set()
    for x in rows:
        for y in rows:
            if x is not y and x["code"] == y["code"] and x["start"] < y["end"] and y["start"] < x["end"]:
                bad.add(x["row"])
    for r in sorted(bad):
        errors.append("Excel %d行目: 同じ商品で期間が重なる行があるため実行しません" % r)
    return [r for r in rows if r["row"] not in bad], errors


def fmt_dt(d):
    return d.strftime("%Y/%m/%d %H:%M")


def state_path():
    return os.path.join(HERE, "state.json")


def load_state():
    p = state_path()
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    p = state_path()
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)  # 途中で止まっても記録が壊れないように


def in_avoid(now, avoid):
    t = now.strftime("%H:%M")
    for w in avoid:
        a, b = w.split("-")
        if a <= t < b:
            return w
    return None


def plan(rows, state, now, early):
    """今やることを決める。戻り値: (変更する行, 戻す行, 出品だけ残っている行, 期限切れで飛ばす行)"""
    lead = datetime.timedelta(minutes=early)
    change, revert, upload_only, expired = [], [], [], []
    for r in rows:
        st = state.get(r["key"], {}).get("status", "")
        if st in ("reverted", "expired", "failed"):
            continue
        if st == "":  # まだ何もしていない
            if now >= r["end"] - lead:
                expired.append(r)
            elif now >= r["start"] - lead:
                change.append(r)
        elif st == "change_failed":
            if now >= r["end"] - lead and state[r["key"]].get("original_price") is not None:
                revert.append(r)
        elif st in ("changing", "changed_edit", "changed"):
            if now >= r["end"] - lead:
                revert.append(r)
            elif st == "changing":
                change.append(r)  # 前回、保存の途中で止まった
            elif st == "changed_edit":
                upload_only.append(r)  # 前回、価格は変えたが出品できていない
        elif st in ("reverting", "revert_edit"):
            if st == "reverting":
                revert.append(r)
            else:
                upload_only.append(r)
    return change, revert, upload_only, expired


def attention(cfg, lines):
    """パソコンを見たときに気づけるよう、Excelと同じフォルダに「要確認.txt」を書き足す。"""
    if not lines:
        return
    try:
        p = os.path.join(cfg["excel_folder"], ATTENTION_FILE)
        with open(p, "a", encoding="utf-8-sig") as f:
            for ln in lines:
                f.write("%s  %s\n" % (datetime.datetime.now().strftime("%Y/%m/%d %H:%M"), ln))
    except Exception as e:
        logging.error("要確認.txt に書けません: %s", e)


# ================================================================ Chrome(CDP)
def http_json(path, method="GET"):
    req = urllib.request.Request(BASE + path, method=method)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def ensure_chrome():
    try:
        http_json("/json/version")
        return
    except Exception:
        pass
    exe = next((e for e in CHROME_EXES if os.path.exists(e)), None)
    if exe is None:
        raise RuntimeError("chrome.exeが見つかりません: %s" % CHROME_EXES)
    logging.info("Chrome(9222)が起動していないため起動します")
    subprocess.Popen([exe] + CHROME_ARGS)
    for _ in range(40):
        time.sleep(1)
        try:
            http_json("/json/version")
            return
        except Exception:
            pass
    raise RuntimeError("Chrome(9222)に接続できません。開いているChromeをすべて閉じてから、もう一度実行してください")


def list_pages():
    return [t for t in http_json("/json/list") if t.get("type") == "page"]


class Page:
    def __init__(self, target):
        import websocket
        self.id = target["id"]
        self.ws = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=90, suppress_origin=True)
        self._n = 0
        self.dialogs = []
        self.call("Page.enable")

    def call(self, method, **params):
        self._n += 1
        n = self._n
        self.ws.send(json.dumps({"id": n, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("method") == "Page.javascriptDialogOpening":
                text = msg["params"].get("message", "")
                self.dialogs.append(text)
                logging.info("ダイアログ(自動OK): %s", text)
                self._n += 1
                self.ws.send(json.dumps({"id": self._n, "method": "Page.handleJavaScriptDialog",
                                         "params": {"accept": True}}))
                continue
            if msg.get("id") == n:
                if "error" in msg:
                    raise RuntimeError("%s: %s" % (method, msg["error"]))
                return msg.get("result", {})

    def ev(self, expr):
        r = self.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            raise RuntimeError("JS error: %s" % (d.get("exception", {}).get("description") or d.get("text")))
        return r.get("result", {}).get("value")

    def wait_for(self, expr, timeout=60, interval=0.5):
        end = time.time() + timeout
        while time.time() < end:
            try:
                if self.ev(expr):
                    return True
            except Exception:
                pass
            time.sleep(interval)
        return False

    def detach(self):
        try:
            self.ws.close()
        except Exception:
            pass

    def close(self):
        self.detach()
        try:
            urllib.request.urlopen(BASE + "/json/close/" + self.id, timeout=10).read()
        except Exception:
            pass


def wait_for_popup(before_ids, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        for t in list_pages():
            if t["id"] not in before_ids:
                return Page(t)
        time.sleep(0.5)
    return None


def popup_gone(pid, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        if pid not in [t["id"] for t in list_pages()]:
            return True
        time.sleep(0.5)
    return False


# ================================================================ 商品一括処理の画面
def find_crossmall_page():
    for t in list_pages():
        if SITE_KEY in t.get("url", ""):
            return Page(t)
    logging.info("クロスモールのタブがないため、新しいタブで開きます")
    p = Page(http_json("/json/new?" + ITEM_BATCH_URL, method="PUT"))
    p.wait_for("document.readyState==='complete'", 60)
    return p


def open_bulk_page(page):
    if "login" in page.ev("location.href").lower():
        raise LoginRequired()
    if page.wait_for("!!document.getElementById('shop_id') || !!document.querySelector('input[type=password]')", 30):
        if page.ev("!!document.querySelector('input[type=password]')"):
            raise LoginRequired()
        return
    page.ev("(()=>{const h=document.getElementById('menu2_header_hd'); if(h) h.click();})()")
    time.sleep(1)
    page.ev("""(()=>{const e=[...document.querySelectorAll('.menu_sub')]
        .find(x=>x.textContent.trim()==='商品一括処理'); if(!e) throw new Error('商品一括処理メニューなし'); e.click();})()""")
    if not page.wait_for("!!document.getElementById('shop_id')", 60):
        if "login" in page.ev("location.href").lower():
            raise LoginRequired()
        raise RuntimeError("商品一括処理画面が開きません")


def current_shop(page):
    return page.ev("""(()=>{const s=document.getElementById('shop_id'); if(!s) return null;
      const o=s.options[s.selectedIndex]; return [s.value, o ? o.textContent.trim() : ''];})()""")


def assert_rakuten(page):
    """編集・出品の直前に必ず呼ぶ。編集対象がビッグボス楽天でなければ止める。"""
    cur = current_shop(page)
    if not cur or cur[0] != RAKUTEN_SHOP or cur[1] != RAKUTEN_SHOP_NAME:
        raise RuntimeError("編集対象がビッグボス楽天ではありません(%s)。安全のため中止します" % (cur,))


def switch_shop(page, shop_id):
    if (current_shop(page) or [None])[0] == shop_id:
        return
    page.ev("window.__cm_mark=1")
    page.ev("(()=>{const s=document.getElementById('shop_id'); s.value='%s'; chngShop();})()" % shop_id)
    time.sleep(1)
    page.wait_for("!window.__cm_mark", 10)
    if not page.wait_for("document.readyState==='complete' && !!document.getElementById('shop_id') "
                         "&& document.getElementById('shop_id').value==='%s'" % shop_id, 60):
        raise RuntimeError("店舗切替失敗 %s" % shop_id)


def set_code_conditions(page, codes):
    """前回の検索条件(商品名・商品登録・Mark・日付)を空にしてから、商品コードだけで絞る。"""
    page.ev("""(()=>{
      const set=(id,v)=>{const e=document.getElementById(id); if(e){e.value=v;
        e.dispatchEvent(new Event('change',{bubbles:true}));}};
      ['item_cd1','item_cd2','item_name','stc_flag','mark_set%s'].forEach(i=>set(i,''));
      set('item_cd_plural', %s);
      const a=[...document.querySelectorAll('a')].find(x=>(x.getAttribute('onclick')||'').includes('clearDate'));
      if(a) a.click();
    })()""" % (MARK_ID, json.dumps(",".join(codes))))


LINKS = "document.querySelectorAll('a[href*=\"doEditShopItem\"]')"

LOADING_JS = """(()=>{
  let loading=false;
  try{ if(window.Ext && Ext.StoreManager) Ext.StoreManager.each(s=>{ if(s.isLoading && s.isLoading()) loading=true;}); }catch(e){}
  const vis=e=>e.offsetParent!==null && getComputedStyle(e).visibility!=='hidden';
  return loading || [...document.querySelectorAll('.x-mask,.x-mask-msg')].some(vis);
})()"""


def search(page, zero_wait=40):
    """検索して件数を返す。表示まで数十秒かかるため、読み込み中表示が終わるまで待つ。"""
    page.ev("onSrch()")
    start, seen_loading, last, same = time.time(), False, -1, 0
    while time.time() - start < 180:
        time.sleep(1.5)
        try:
            loading = bool(page.ev(LOADING_JS))
            n = page.ev("(document.readyState==='complete') ? %s.length : -1" % LINKS)
        except Exception:
            continue
        seen_loading = seen_loading or loading
        if loading or n < 0:
            same = 0
            continue
        same = same + 1 if n == last else 0
        last = n
        elapsed = time.time() - start
        if same >= 3 and n > 0 and elapsed >= 5:
            break
        if same >= 3 and n == 0 and ((seen_loading and elapsed >= 8) or elapsed >= zero_wait):
            break
    return max(last, 0)


ROWS_FOR_CODE_JS = r"""(()=>{const code=%s; const esc=code.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  const re=new RegExp('(^|[^0-9A-Za-z_\\-])'+esc+'($|[^0-9A-Za-z_\\-])');
  const out=[]; [...%s].forEach((a,i)=>{const tr=a.closest('tr'); if(tr && re.test(tr.innerText||'')) out.push(i);});
  return out;})()"""


def rows_for_code(page, code):
    """検索結果のうち、行の文字に商品管理番号がそのまま(前後に別の文字が続かずに)含まれる行の番号。"""
    return page.ev(ROWS_FOR_CODE_JS % (json.dumps(code), LINKS))


def find_one_row(page, code):
    set_code_conditions(page, [code])
    n = search(page)
    idx = rows_for_code(page, code)
    if len(idx) != 1:
        raise RuntimeError("商品 %s が1件に絞れません(検索%d件 / 一致%d件)" % (code, n, len(idx)))
    return idx[0]


def open_editor(page, idx):
    assert_rakuten(page)
    before = {t["id"] for t in list_pages()}
    page.ev("%s[%d].click()" % (LINKS, idx))
    pop = wait_for_popup(before, 20)
    if pop is None:
        raise RuntimeError("店舗別詳細編集が開きません")
    if not pop.wait_for("!!document.querySelector('%s')" % PRICE_SEL, 30):
        pop.close()
        raise RuntimeError("楽天の価格欄(mall_rakuten_unit_price)が見つかりません")
    if pop.ev("!!document.querySelector('[name^=\"mall_yahoo[\"],[name^=\"mall_basic[\"]')"):
        pop.close()
        raise RuntimeError("楽天以外の編集画面が開きました。安全のため中止します")
    return pop


def read_price(page, code):
    idx = find_one_row(page, code)
    pop = open_editor(page, idx)
    try:
        return parse_price(pop.ev("document.querySelector('%s').value" % PRICE_SEL))
    finally:
        pop.close()


def write_price(page, code, new_price, expect_old):
    """価格を書き換えて更新する。開いた時点の価格が expect_old(集合)に入っていなければ、触らずにエラー。
    戻り値: 書き換える前の価格。すでに new_price になっていれば、何もせずにそれを返す。"""
    idx = find_one_row(page, code)
    pop = open_editor(page, idx)
    try:
        old = parse_price(pop.ev("document.querySelector('%s').value" % PRICE_SEL))
        if old == new_price:
            logging.info("  %s すでに %d 円のため保存は不要", code, new_price)
            return old
        if expect_old is not None and old not in expect_old:
            raise RuntimeError("今の価格(%d円)が想定(%s)と違うため、触りません。手で変えられた可能性があります"
                               % (old, "・".join("%d円" % x for x in sorted(expect_old))))
        pop.ev("""(()=>{const e=document.querySelector('%s'); e.value=%s;
          e.dispatchEvent(new Event('input',{bubbles:true})); e.dispatchEvent(new Event('change',{bubbles:true}));})()"""
               % (PRICE_SEL, json.dumps(str(new_price))))
        pop.ev("document.getElementById('update').click()")
        if not popup_gone(pop.id, 30):
            raise RuntimeError("更新後も画面が閉じません(入力エラーの可能性)。メッセージ: %s"
                               % (pop.dialogs[-1] if pop.dialogs else "なし"))
        logging.info("  %s 価格 %d円 → %d円 を保存", code, old, new_price)
        return old
    finally:
        pop.close()


def bulk_upload_rakuten(page, codes):
    """商品コードで絞って表示し、その行だけ選んで、ビッグボス楽天だけに一括出品処理する。戻り値: 出品した商品コード"""
    assert_rakuten(page)
    set_code_conditions(page, codes)
    n = search(page)
    chosen = []
    for code in codes:
        idx = rows_for_code(page, code)
        if len(idx) != 1:
            logging.error("  出品: %s が1件に絞れません(一致%d件)。この商品は次回もう一度出品します", code, len(idx))
            continue
        page.ev("""(()=>{const a=%s[%d]; const tr=a.closest('tr');
          const c=tr.querySelector('.x-grid-row-checker') || [...document.querySelectorAll('.x-grid-row-checker')][%d];
          c.click();})()""" % (LINKS, idx[0], idx[0]))
        chosen.append(code)
    logging.info("=== 一括出品処理(ビッグボス楽天のみ) 検索%d件 / 選択%d件 ===", n, len(chosen))
    if not chosen:
        return []
    time.sleep(1)
    assert_rakuten(page)
    before = {t["id"] for t in list_pages()}
    page.ev("onMultiMallUpload()")
    pop = wait_for_popup(before, 15)
    target = pop or page
    try:
        if not target.wait_for("!!document.querySelector('input[value=\"処理開始\"]')", 30):
            raise RuntimeError("一括出品処理の確認画面が出ません")
        checked = target.ev("""(()=>{const want='select_shop_id_%s';
          const all=[...document.querySelectorAll('input[type=checkbox]')].filter(e=>/^select_shop_id_/.test(e.id||e.name||''));
          all.forEach(e=>{const on=(e.id||e.name)===want; if(e.checked!==on) e.click();});
          return all.filter(e=>e.checked).map(e=>e.id||e.name);})()""" % RAKUTEN_SHOP)
        if checked != ["select_shop_id_%s" % RAKUTEN_SHOP]:
            raise RuntimeError("出品先のチェックがビッグボス楽天だけになっていません: %s。出品を中止します" % checked)
        time.sleep(1)
        target.ev("document.querySelector('input[value=\"処理開始\"]').click()")
        time.sleep(3)
        for t in (target, page):
            try:
                t.ev("""(()=>{const b=[...document.querySelectorAll('input[type=button],button,a')]
                  .find(x=>(x.value||x.textContent||'').trim()==='はい'); if(b) b.click();})()""")
            except Exception:
                pass
        time.sleep(5)
        if any("選択してください" in d for d in target.dialogs):
            raise RuntimeError("出品先店舗が未選択でした: %s" % target.dialogs)
    finally:
        if pop:
            time.sleep(5)
            pop.close()
    logging.info("  出品処理を開始しました: %s", ", ".join(chosen))
    return chosen


def reset_search_form(page):
    """終了時に検索条件を空に戻す(他の自動化の検索が絞られて0件になるのを防ぐ)。"""
    try:
        if page is None or not page.ev("!!document.getElementById('shop_id')"):
            return
        set_code_conditions(page, [])
        search(page, zero_wait=8)
    except Exception as e:
        logging.warning("検索条件のリセットに失敗: %s", e)


# ================================================================ 本体
def do_work(page, change, revert, upload_only, state, cfg, dry_run, problems):
    def mark(r, **kw):
        if dry_run:
            return
        s = state.setdefault(r["key"], {"code": r["code"], "row": r["row"]})
        s.update(kw)
        s["updated_at"] = datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        save_state(state)

    def fail(r, msg):
        logging.error("  失敗 %s (Excel %d行目): %s", r["code"], r["row"], msg)
        if dry_run:
            problems.append("%s: %s" % (r["code"], msg))
            return
        s = state.setdefault(r["key"], {"code": r["code"], "row": r["row"]})
        s["attempts"] = s.get("attempts", 0) + 1
        s["last_error"] = msg
        if s["attempts"] >= cfg["max_attempts"]:
            s["status_before_fail"] = s.get("status", "")
            if s.get("status") in ("changing", "changed_edit"):
                # 変更の途中で止めた。価格が変わっている可能性があるので、戻す日時には戻しを試みる
                s["status"] = "change_failed"
                s["attempts"] = 0
                problems.append("%s (Excel %d行目): 変更が%d回失敗したため止めました(戻す日時には、元の価格に戻します)。%s"
                                % (r["code"], r["row"], cfg["max_attempts"], msg))
            else:
                s["status"] = "failed"
                problems.append("%s (Excel %d行目): %d回失敗したため止めました。クロスモールで価格を確認してください。%s"
                                % (r["code"], r["row"], cfg["max_attempts"], msg))
        save_state(state)

    to_upload = []
    switch_shop(page, RAKUTEN_SHOP)

    for r in change:
        s = state.get(r["key"], {})
        try:
            if dry_run:
                cur = read_price(page, r["code"])
                logging.info("  [練習] %s 今 %d円 → %d円 に変える予定", r["code"], cur, r["price"])
                if r["price"] < cur * cfg["min_ratio"]:
                    problems.append("%s: 変更後の価格(%d円)が今の価格(%d円)の%d%%より安いため、本番では実行しません"
                                    % (r["code"], r["price"], cur, cfg["min_ratio"] * 100))
                continue
            if s.get("status") == "changing":  # 前回、保存の途中で止まった
                orig = s["original_price"]
            else:
                orig = read_price(page, r["code"])
                if r["price"] < orig * cfg["min_ratio"]:
                    mark(r, status="failed", original_price=orig)
                    problems.append("%s (Excel %d行目): 変更後の価格(%d円)が元の価格(%d円)の%d%%より安いため、"
                                    "打ち間違いとみなして実行しませんでした"
                                    % (r["code"], r["row"], r["price"], orig, cfg["min_ratio"] * 100))
                    continue
                mark(r, status="changing", original_price=orig, sale_price=r["price"])  # 書き換える前に元の価格を記録
            write_price(page, r["code"], r["price"], {orig})
            mark(r, status="changed_edit")
            to_upload.append(r)
        except LoginRequired:
            raise
        except Exception as e:
            fail(r, str(e))

    for r in revert:
        s = state.get(r["key"], {})
        orig, sale = s.get("original_price"), s.get("sale_price")
        try:
            if dry_run:
                cur = read_price(page, r["code"])
                logging.info("  [練習] %s 今 %d円 → 元の %s円 に戻す予定", r["code"], cur, orig)
                continue
            if orig is None:
                raise RuntimeError("元の価格の記録がありません")
            if s.get("status") not in ("reverting",):
                mark(r, status="reverting", attempts=0)
            write_price(page, r["code"], orig, {sale, orig})
            mark(r, status="revert_edit")
            to_upload.append(r)
        except LoginRequired:
            raise
        except Exception as e:
            fail(r, str(e))

    if dry_run:
        for r in upload_only:
            logging.info("  [練習] %s 出品だけ残っています", r["code"])
        return
    to_upload += upload_only
    if not to_upload:
        return
    codes = sorted({r["code"] for r in to_upload})
    try:
        done = set(bulk_upload_rakuten(page, codes))
    except LoginRequired:
        raise
    except Exception as e:
        for r in to_upload:
            fail(r, "出品処理: %s" % e)
        return
    for r in to_upload:
        if r["code"] not in done:
            fail(r, "出品できませんでした(次回もう一度出品します)")
            continue
        st = state[r["key"]]["status"]
        mark(r, status="changed" if st == "changed_edit" else "reverted", attempts=0)


def snapshot(page, code):
    """全店舗の店舗別詳細編集を開き、名前に price を含む欄の値を読むだけ。前回の記録と比べて違いを出す。"""
    snap = {}
    for sid, name in ALL_SHOPS:
        try:
            switch_shop(page, sid)
            set_code_conditions(page, [code])
            search(page)
            idx = rows_for_code(page, code)
            if len(idx) != 1:
                snap[name] = "1件に絞れません(%d件)" % len(idx)
                continue
            before = {t["id"] for t in list_pages()}
            page.ev("%s[%d].click()" % (LINKS, idx[0]))
            pop = wait_for_popup(before, 20)
            if pop is None:
                snap[name] = "編集画面が開きません"
                continue
            try:
                pop.wait_for("document.readyState==='complete' && !!document.getElementById('update')", 30)
                snap[name] = pop.ev("""(()=>{const o={}; document.querySelectorAll('input,select').forEach(e=>{
                  const n=e.name||e.id||''; if(/price/i.test(n) && e.type!=='hidden') o[n]=e.value;}); return o;})()""")
            finally:
                pop.close()  # 更新ボタンは押さない(読むだけ)
        except LoginRequired:
            raise
        except Exception as e:
            snap[name] = "エラー: %s" % e
    p = os.path.join(HERE, "logs", "snapshot_%s.json" % code)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            prev = json.load(f)
        logging.info("=== 前回の記録(%s)との比較 ===", prev.get("_time"))
        for name in [n for _, n in ALL_SHOPS]:
            a, b = prev.get(name), snap.get(name)
            logging.info("  %s: %s", name, "変わらず" if a == b else "変わった %s → %s" % (a, b))
    snap["_time"] = datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)
    for k, v in snap.items():
        logging.info("  %s: %s", k, v)


def acquire_lock():
    p = os.path.join(HERE, "run.lock")
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < 90 * 60:
        return None
    with open(p, "w") as f:
        f.write(str(os.getpid()))
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--now", help='この時刻になったつもりで動く(練習用) 例 "2026-11-20 21:55"')
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--snapshot", metavar="CODE")
    a = ap.parse_args()

    cfg = load_config()
    os.makedirs(os.path.join(HERE, "logs"), exist_ok=True)
    now = datetime.datetime.strptime(a.now, "%Y-%m-%d %H:%M") if a.now else datetime.datetime.now()
    log_file = os.path.join(HERE, "logs", datetime.date.today().strftime("%Y%m%d") + ".log")
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    def start_file_log():  # やることがあるときだけ、ログファイルに書く(5分ごとの空振りでログを増やさない)
        h = logging.FileHandler(log_file, encoding="utf-8")
        h.setFormatter(fmt)
        root.addHandler(h)

    if a.snapshot:
        start_file_log()
        page = None
        try:
            ensure_chrome()
            page = find_crossmall_page()
            open_bulk_page(page)
            snapshot(page, a.snapshot.strip())
            switch_shop(page, RAKUTEN_SHOP)
        except LoginRequired:
            logging.error("ログインが切れています。自動化用Chromeでクロスモールにログインし直してください")
            return 2
        finally:
            reset_search_form(page)
            if page:
                page.detach()
        return 0

    try:
        excel = find_excel(cfg)
        rows, row_errors = read_excel(excel)
    except Exception as e:
        start_file_log()
        logging.error("Excelを読めません: %s", e)
        attention(cfg, ["Excelを読めません: %s" % e])
        return 1
    state = load_state()

    if a.list:
        for r in rows:
            s = state.get(r["key"], {})
            print("%d行目 %s  %d円  %s → %s  状態:%s  元の価格:%s" % (
                r["row"], r["code"], r["price"], fmt_dt(r["start"]), fmt_dt(r["end"]),
                s.get("status") or "未実行", s.get("original_price", "-")))
        for e in row_errors:
            print("エラー:", e)
        return 0

    # Excelの行の間違いは、1回だけ知らせる(5分ごとに同じことを書かないように)
    reported = state.setdefault("_reported_errors", [])
    new_errors = [e for e in row_errors if e not in reported]
    change, revert, upload_only, expired = plan(rows, state, now, cfg["early_minutes"])
    if not (change or revert or upload_only or expired or new_errors):
        return 0  # やることなし

    start_file_log()
    logging.info("開始 now=%s dry_run=%s 変更%d 戻し%d 出品のみ%d 期限切れ%d Excel=%s", fmt_dt(now), a.dry_run,
                 len(change), len(revert), len(upload_only), len(expired), os.path.basename(excel))
    problems = list(new_errors)
    for e in new_errors:
        logging.error(e)
    if not a.dry_run:
        reported.extend(new_errors)
        for r in expired:
            state[r["key"]] = {"code": r["code"], "row": r["row"], "status": "expired"}
            problems.append("%s (Excel %d行目): 戻す日時を過ぎていたため、価格を変えずに飛ばしました" % (r["code"], r["row"]))
        save_state(state)

    if not (change or revert or upload_only):
        attention(cfg, problems)
        return 1 if problems else 0
    if len(change) + len(revert) + len(upload_only) > cfg["max_items"]:
        msg = "対象が%d件あり、上限(%d件)を超えたため実行しませんでした" % (
            len(change) + len(revert) + len(upload_only), cfg["max_items"])
        logging.error(msg)
        attention(cfg, problems + [msg])
        return 1
    w = in_avoid(now, cfg["avoid"])
    if w:
        logging.info("%s は動かない時間帯のため、次の回に回します", w)
        attention(cfg, problems)
        return 0
    lock = acquire_lock()
    if not lock:
        logging.info("前の回がまだ動いているため、今回は何もしません")
        return 0

    page = None
    try:
        ensure_chrome()
        page = find_crossmall_page()
        open_bulk_page(page)
        do_work(page, change, revert, upload_only, state, cfg, a.dry_run, problems)
    except LoginRequired:
        msg = "クロスモールのログインが切れています。自動化用のChromeでログインし直してください"
        logging.error(msg)
        attention(cfg, problems + [msg])
        return 2
    except Exception:
        logging.error("止まりました\n%s", traceback.format_exc())
        attention(cfg, problems + ["プログラムが途中で止まりました。logs のログを確認してください"])
        return 1
    finally:
        reset_search_form(page)
        if page:
            page.detach()
        try:
            os.remove(lock)
        except OSError:
            pass
    if a.dry_run:
        for p in problems:
            logging.warning("[練習] 注意: %s", p)
        logging.info("練習モード終了(保存・出品はしていません)")
        return 0
    attention(cfg, problems)
    logging.info("終了 %s", "要確認あり" if problems else "問題なし")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
