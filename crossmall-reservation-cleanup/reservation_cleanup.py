# -*- coding: utf-8 -*-
"""CrossMall: 発売日を過ぎた予約商品の商品名から予約テキストを削除し、各モールへ出品処理する。

毎朝(タスクスケジューラ)実行。Chromeは --remote-debugging-port=9222 で起動済み・クロスモールにログイン済みが前提。
使い方:  python reservation_cleanup.py [--days N] [--date YYYY-MM-DD] [--dry-run]
  既定は「昨日が発売日」の商品。--days 3 なら昨日〜3日前が発売日の商品(取りこぼし救済)。
  --dry-run は商品名の変更内容をログに出すだけで、更新も出品処理もしない。
"""
import argparse
import datetime
import json
import logging
import os
import re
import sys
import time
import traceback
import urllib.request

import websocket

PORT = 9222
BASE = "http://127.0.0.1:%d" % PORT

SHOPS = [  # (shop_id, 名前, 種別)  この順に処理する
    ("5255", "ビッグボス楽天", "rakuten"),
    ("5256", "ドリームクラフト", "rakuten"),
    ("5257", "Yahoo", "yahoo"),
    ("8581", "wine.com", "yahoo"),
    ("8014", "Wowma", "wowma"),
    ("9365", "Wowma2店舗目", "wowma"),
]
MARK_ID = "1100"  # 予約Claude


class LoginRequired(Exception):
    pass


# ---------------------------------------------------------------- CDP
def http_json(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def list_pages():
    return [t for t in http_json("/json/list") if t.get("type") == "page"]


class Page:
    def __init__(self, target):
        self.id = target["id"]
        self.ws = websocket.create_connection(
            target["webSocketDebuggerUrl"], timeout=90, suppress_origin=True)
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
                pass  # ページ遷移中
            time.sleep(interval)
        return False

    def close(self):
        try:
            self.ws.close()
        finally:
            try:
                urllib.request.urlopen(BASE + "/json/close/" + self.id, timeout=10).read()
            except Exception:
                pass


def wait_for_popup(before_ids, timeout=15):
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


# ---------------------------------------------------------------- 商品名の加工(純粋関数)
def jp_date(d):
    return "%d年%d月%d日" % (d.year, d.month, d.day)


def clean_name(name, dates):
    """【予約】と【<日付>限定発売/新発売】を消す(楽天・ドリクラ・Wowma用)。他の文字は触らない。"""
    new = name
    for ds in map(jp_date, dates):
        new = re.sub(r"【" + re.escape(ds) + r"[^】]*】", "", new, count=1)
    new = new.replace("【予約】", "", 1)
    return new


def clean_name_yahoo(name, dates):
    """Yahoo/wine.com: '<日付>限定発売' と直後の半角スペース1つだけ消す。他のスペースは絶対に触らない。"""
    new = name
    for ds in map(jp_date, dates):
        new = re.sub(re.escape(ds) + r"(?:限定発売|新発売) ?", "", new, count=1)
    return new


def ship_text(d):
    """商品名の先頭にある出荷日表記。例: 10月25日出荷 (月・日はゼロ埋めしない)"""
    return "%d月%d日出荷" % (d.month, d.day)


def clean_name_ship(name, dates):
    """先頭の '<M月D日>出荷' と、その直後に続く半角スペースを消す(消した結果、名前がスペースで始まらないように)。
    商品名の途中のスペースは触らない。"""
    new = name
    for d in dates:
        new = re.sub(r"^" + re.escape(ship_text(d)) + r" *", "", new, count=1)
    return new


SAIKYO = "【最強配送】"


def add_saikyo(name):
    """【本州のみ 送料無料】または【送料無料】の直前に【最強配送】を足す。戻り値 (新しい名前, スキップ理由)。
    すでに【最強配送】がある・どちらの文字もない場合は (None, 理由)。"""
    if SAIKYO in name:
        return None, "すでに【最強配送】あり"
    m = re.search(r"【(?:本州のみ )?送料無料】", name)
    if not m:
        return None, "【本州のみ 送料無料】/【送料無料】がない"
    return name[:m.start()] + SAIKYO + name[m.start():], ""


SHIP_SHOPS = [("5257", "Yahoo"), ("8581", "wine.com")]  # 出荷日表記の削除は、この2店舗だけ


# ---------------------------------------------------------------- 画面操作
def find_crossmall_page():
    for t in list_pages():
        if "crossmall.jp" in t.get("url", ""):
            return Page(t)
    raise RuntimeError("クロスモールのタブが見つかりません(自動化用Chromeを起動・ログインしてください)")


def open_bulk_page(page):
    url = page.ev("location.href")
    if "login" in url.lower():
        raise LoginRequired(url)
    if page.ev("!!document.getElementById('shop_id')"):
        return
    page.ev("(()=>{const h=document.getElementById('menu2_header_hd'); if(h) h.click();})()")
    time.sleep(1)
    page.ev("""(()=>{const e=[...document.querySelectorAll('.menu_sub')]
        .find(x=>x.textContent.trim()==='商品一括処理'); if(!e) throw new Error('商品一括処理メニューなし'); e.click();})()""")
    if not page.wait_for("!!document.getElementById('shop_id')", 60):
        if "login" in page.ev("location.href").lower():
            raise LoginRequired()
        raise RuntimeError("商品一括処理画面が開きません")


def switch_shop(page, shop_id):
    page.ev("window.__cm_mark=1")
    page.ev("(()=>{const s=document.getElementById('shop_id'); s.value='%s'; chngShop();})()" % shop_id)
    time.sleep(1)
    page.wait_for("!window.__cm_mark", 10)  # 再読込されたら消える。されなくても進む
    if not page.wait_for("document.readyState==='complete' && !!document.getElementById('shop_id') "
                         "&& document.getElementById('shop_id').value==='%s'" % shop_id, 60):
        raise RuntimeError("店舗切替失敗 %s" % shop_id)


def set_conditions(page, item_name, use_mark):
    page.ev("""(()=>{
      const set=(id,v)=>{const e=document.getElementById(id); if(e){e.value=v;
        e.dispatchEvent(new Event('change',{bubbles:true}));}};
      ['item_cd1','item_cd2','item_cd_plural'].forEach(i=>set(i,''));  // 前回の商品コード条件を消す
      set('item_name', %s);
      set('stc_flag','2');
      set('mark_set%s', %s ? '1' : '');  // 前回のMark条件が残らないよう、使わないときは空にする
    })()""" % (json.dumps(item_name), MARK_ID, "true" if use_mark else "false"))


def clear_dates(page):
    page.ev("(()=>{const a=[...document.querySelectorAll('a')].find(x=>x.textContent.trim()==='クリア'"
            " && (x.getAttribute('onclick')||'').includes('clearDate')); if(a) a.click();})()")


LINKS = "document.querySelectorAll('a[href*=\"doEditShopItem\"]')"

ROW_CODE_JS = r"""(()=>{const a=%s[%d]; if(!a) return null; const tr=a.closest('tr'); if(!tr) return null;
  const m=(tr.innerText||'').match(/\d{13}[-\w]*/); return m?m[0]:null;})()"""


def row_code(page, idx):
    """検索結果のidx番目の行の商品コード(標準)。例 4901004006684-sbl-1"""
    return page.ev(ROW_CODE_JS % (LINKS, idx))


LOADING_JS = """(()=>{
  let loading=false;
  try{ if(window.Ext && Ext.StoreManager) Ext.StoreManager.each(s=>{
        if(s.isLoading && s.isLoading()) loading=true;}); }catch(e){}
  const vis=e=>e.offsetParent!==null && getComputedStyle(e).visibility!=='hidden';
  const mask=[...document.querySelectorAll('.x-mask,.x-mask-msg')].some(vis);
  return loading||mask;
})()"""


def search(page, zero_wait=40):
    """検索して件数を返す。表示まで数十秒かかるため、読み込み中表示が終わるまで待つ。
    読み込み中表示が一度も確認できなかった場合は、0件を確定する前に zero_wait 秒まで待つ。"""
    page.ev("window.__cm_mark=1")
    page.ev("onSrch()")
    start, seen_loading, last, same = time.time(), False, -1, 0
    while time.time() - start < 180:
        time.sleep(1.5)
        try:
            loading = bool(page.ev(LOADING_JS))
            n = page.ev("(document.readyState==='complete') ? %s.length : -1" % LINKS)
        except Exception:
            continue  # ページ遷移中
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


def tick_marks_and_update(page, only=None):
    """検索結果の各行の Mark(予約Claude) を1件ずつ直接クリックでチェック→更新。
    only(商品コードの集合)を渡すと、その商品の行だけチェックする。"""
    if only is None:
        n = page.ev("""(()=>{let c=0; document.querySelectorAll('input.chk_mark[id^="chk%s_"]').forEach(e=>{
            if(!e.checked){e.click(); c++;}}); return c;})()""" % MARK_ID)
    else:
        n = 0
        for i in range(page.ev("%s.length" % LINKS)):
            if row_code(page, i) in only:
                n += page.ev("""(()=>{const a=%s[%d]; const e=a.closest('tr').querySelector('input.chk_mark[id^="chk%s_"]');
                  if(e && !e.checked){e.click(); return 1;} return 0;})()""" % (LINKS, i, MARK_ID))
    # すでにチェック済みの商品(他店舗の処理で付いたMark)も有効。更新後にチェック済みの数を返す
    total = page.ev("""document.querySelectorAll('input.chk_mark[id^="chk%s_"]:checked').length""" % MARK_ID)
    if only is not None and total == 0:
        n = 0
    logging.info("Markチェック 新規%s件 / チェック済み計%s件", n, total)
    page.ev("window.__cm_mark=1")
    page.ev("onSubmit()")
    page.wait_for("!window.__cm_mark", 15)
    page.wait_for("document.readyState==='complete'", 60)
    return total


def untick_marks_and_update(page):
    """検索結果のうちチェック済みの Mark(予約Claude) を1件ずつ直接クリックで外す→更新。"""
    n = page.ev("""(()=>{let c=0; document.querySelectorAll('input.chk_mark[id^="chk%s_"]').forEach(e=>{
        if(e.checked){e.click(); c++;}}); return c;})()""" % MARK_ID)
    logging.info("Mark解除 %s件", n)
    page.ev("window.__cm_mark=1")
    page.ev("onSubmit()")
    page.wait_for("!window.__cm_mark", 60)
    page.wait_for("document.readyState==='complete'", 60)


def clear_marks(page):
    """出品処理後にMarkを外す。Mark有が0件になるまで、店舗を切り替えながら確認する。"""
    logging.info("=== Mark解除 ===")
    for sid, name, _ in reversed(SHOPS):
        switch_shop(page, sid)
        set_conditions(page, "", True)
        n = search(page)
        logging.info("%s Mark有: %d件", name, n)
        if n == 0:
            return
        untick_marks_and_update(page)
    logging.warning("全店舗確認してもMark有が残っている可能性があります")


def fill(pop, selector, value):
    pop.ev("""(()=>{const e=document.querySelector(%s); if(!e) throw new Error('要素なし '+%s);
      e.value=%s; e.dispatchEvent(new Event('input',{bubbles:true}));
      e.dispatchEvent(new Event('change',{bubbles:true}));})()"""
           % (json.dumps(selector), json.dumps(selector), json.dumps(value)))


def edit_one(page, idx, kind, dates, dry_run):
    """idx番目の商品の店舗別詳細編集を開き、変更して更新。戻り値: 'updated'/'skipped'"""
    before = {t["id"] for t in list_pages()}
    page.ev("%s[%d].click()" % (LINKS, idx))
    pop = wait_for_popup(before, 20)
    if pop is None:
        raise RuntimeError("編集ポップアップが開きません(idx=%d)" % idx)
    try:
        sel = 'textarea[name$="[item_name]"]'
        if not pop.wait_for("!!document.querySelector('%s')" % sel, 30):
            raise RuntimeError("商品名欄が見つかりません")
        old = pop.ev("document.querySelector('%s').value" % sel)
        if kind == "saikyo":
            new, why = add_saikyo(old)
            if new is None:
                logging.info("  [%d] スキップ(%s): %s", idx, why, old)
                return "skipped"
        elif kind == "yahoo":
            new = clean_name_yahoo(old, dates)
        elif kind == "ship":
            new = clean_name_ship(old, dates)
        else:
            new = clean_name(old, dates)
        if new == old:
            logging.info("  [%d] 変更なし(スキップ): %s", idx, old)
            return "skipped"
        logging.info("  [%d] %s\n      -> %s", idx, old, new)
        if dry_run:
            return "skipped"
        fill(pop, sel, new)
        code = "IAS" if "IAS" in new else None
        if kind == "rakuten":
            fill(pop, 'input[name$="[stock_shipping_lead_time_label]"]', code or "BSH")
            fill(pop, 'input[name$="[stock_delivery_date_no]"]', "3")
        elif kind == "saikyo":
            fill(pop, 'input[name$="[stock_shipping_lead_time_label]"]', "SAIKYO")
            fill(pop, 'input[name$="[stock_delivery_date_no]"]', "1")
        elif kind == "wowma":
            pop.ev("document.getElementById('kbn_09_1').click()")
            fill(pop, "#char_13", "2")
            fill(pop, "#char_12", code or "2")
        pop.ev("document.getElementById('update').click()")
        if not popup_gone(pop.id, 30):
            raise RuntimeError("更新後もポップアップが閉じません(文字数オーバー等の入力エラーの可能性) 画面のメッセージ: %s"
                               % (pop.dialogs[-1] if pop.dialogs else "なし"))
        return "updated"
    finally:
        try:
            pop.close()
        except Exception:
            pass


def process_shop(page, shop, dates, dry_run, errors):
    sid, name, kind = shop
    logging.info("=== %s (%s) ===", name, sid)
    switch_shop(page, sid)
    updated = 0
    if sid == "5255":  # 楽天: 商品名の日付テキストで検索 → Mark付与
        for d in dates:
            clear_dates(page)
            set_conditions(page, "【予約】【" + jp_date(d), False)
            n = search(page)
            logging.info("%s 検索(%s): %d件", name, jp_date(d), n)
            if n == 0:
                continue
            if not dry_run:
                if tick_marks_and_update(page) == 0:
                    errors.append("%s: Markのチェックが0件(Mark欄の要素が違う可能性)" % name)
                    logging.error("Markのチェックが0件でした")
                set_conditions(page, "【予約】【" + jp_date(d), False)
                n = search(page)
            updated += run_items(page, n, kind, dates, dry_run, errors, name)
    else:  # 他店舗: Mark(予約Claude)=有 で検索
        set_conditions(page, "", True)
        n = search(page)
        logging.info("%s 検索(Mark有): %d件", name, n)
        updated += run_items(page, n, kind, dates, dry_run, errors, name)
    return updated


def run_items(page, n, kind, dates, dry_run, errors, shop_name, codes=None, only=None):
    """codes: 更新できた商品の商品コードを集める集合 / only: この商品コードの行だけ処理する集合"""
    updated = 0
    for i in range(n):
        code = row_code(page, i) if (codes is not None or only is not None) else None
        if only is not None and code not in only:
            logging.info("  [%d] 対象外のためスキップ: %s", i, code)
            continue
        for attempt in (1, 2):  # 他の作業と画面が被った等の一時的な失敗は、1回だけやり直す
            try:
                if edit_one(page, i, kind, dates, dry_run) == "updated":
                    updated += 1
                    if codes is not None and code:
                        codes.add(code)
                break
            except LoginRequired:
                raise
            except Exception as e:  # 1商品の失敗で残りを止めない
                if attempt == 1:
                    logging.warning("  失敗(やり直します) %s idx=%d: %s", shop_name, i, e)
                    time.sleep(5)
                    continue
                logging.error("  失敗 %s idx=%d: %s", shop_name, i, e)
                errors.append("%s idx=%d: %s" % (shop_name, i, e))
    return updated


def select_rows(page, only_codes=None):
    """検索結果の行チェックを1つずつ直接クリック。only_codes(商品コードの集合)があれば、その行だけ。戻り値は選んだ行数。"""
    if only_codes is None:
        return page.ev("""(()=>{const l=[...document.querySelectorAll('.x-grid-row-checker')]; l.forEach(e=>e.click()); return l.length;})()""")
    n = 0
    for i in range(page.ev("%s.length" % LINKS)):
        if row_code(page, i) in only_codes:
            n += page.ev("""(()=>{const e=[...document.querySelectorAll('.x-grid-row-checker')][%d]; if(e){e.click(); return 1;} return 0;})()""" % i)
    return n


def bulk_upload(page, only_shops=None, only_codes=None):
    """表示商品を一括出品処理。only_shops(店舗IDのリスト)を渡すと、その店舗だけチェックして出品する。
    only_codes(商品コードの集合)を渡すと、その商品の行だけ選んで出品する。"""
    logging.info("=== 一括出品処理 %s ===", only_shops or "(全店舗)")
    if select_rows(page, only_codes) == 0:
        logging.warning("出品する行が選べませんでした。出品処理をスキップします")
        return
    time.sleep(1)
    before = {t["id"] for t in list_pages()}
    page.ev("onMultiMallUpload()")
    pop = wait_for_popup(before, 15)
    target = pop or page  # ポップアップでもインラインでも両対応
    try:
        if not target.wait_for("!!document.querySelector('input[value=\"全選択\"]')", 30):
            raise RuntimeError("一括出品処理の確認画面が出ません")
        if only_shops is None:
            target.ev("document.querySelector('input[value=\"全選択\"]').click()")
        else:
            checked = target.ev("""(()=>{const ids=%s;
              const all=[...document.querySelectorAll('input[type=checkbox]')]
                .filter(e=>/^select_shop_id_/.test(e.id||e.name||''));
              all.forEach(e=>{const want=ids.some(i=>(e.id||e.name)==='select_shop_id_'+i);
                if(e.checked!==want) e.click();});
              return all.filter(e=>e.checked).map(e=>e.id||e.name).sort();})()""" % json.dumps(only_shops))
            want = sorted("select_shop_id_" + i for i in only_shops)
            if checked != want:  # 想定外の店舗に出品しないよう、合わなければ中止
                raise RuntimeError("出品先店舗のチェックが想定と違います: %s (想定 %s)" % (checked, want))
        time.sleep(1)
        target.ev("document.querySelector('input[value=\"処理開始\"]').click()")
        time.sleep(3)
        # 「横軸/縦軸を逆にして出品しますが…」のような確認が出たら「はい」
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
            time.sleep(10)
            pop.close()


def shipping_job(page, dates, dry_run, errors, only=None):
    """Yahoo/wine.com の商品名先頭の『○月○日出荷 』を消す → 楽天に【最強配送】等を足す → 3店舗に出品 → Mark解除。
    only: 商品コードの集合を渡すと、その商品だけ処理する(テスト用)。"""
    logging.info("########## 出荷日表記の削除 (Yahoo / wine.com) ##########")
    open_bulk_page(page)
    total = 0
    ship_codes = set()  # Yahooで今回更新できた商品の商品コード(楽天の対象はこれだけ)
    for sid, name in SHIP_SHOPS:
        logging.info("=== %s (%s) 出荷日表記 ===", name, sid)
        try:
            switch_shop(page, sid)
            for d in dates:
                clear_dates(page)
                key = ship_text(d)
                set_conditions(page, key, False)
                n = search(page)
                logging.info("%s 検索(%s): %d件", name, key, n)
                if n == 0:
                    continue
                if not dry_run:
                    if tick_marks_and_update(page, only) == 0:
                        errors.append("%s: Markのチェックが0件(出荷日表記)" % name)
                        logging.error("Markのチェックが0件でした")
                    set_conditions(page, key, False)
                    n = search(page)
                total += run_items(page, n, "ship", dates, dry_run, errors, name,
                                   codes=ship_codes if sid == "5257" else None, only=only)
        except LoginRequired:
            raise
        except Exception as e:
            logging.error("出荷日表記 店舗処理失敗 %s: %s", name, e)
            errors.append("%s(出荷日表記): %s" % (name, e))
    if dry_run:
        logging.info("dry-run: 楽天の【最強配送】追加と出品処理は省略(Markが付かないため)")
        return total
    if not total:
        logging.info("出荷日表記: 更新0件のため楽天の追加・出品処理はスキップ")
        return total

    saikyo_done = set()  # 楽天で【最強配送】を足せた商品コード
    try:
        logging.info("########## 最強配送の追加 (ビッグボス楽天) ##########")
        switch_shop(page, "5255")
        set_conditions(page, "", True)
        n = search(page)
        logging.info("ビッグボス楽天 Mark有: %d件 (対象はYahoo更新分 %d件)", n, len(ship_codes))
        run_items(page, n, "saikyo", dates, dry_run, errors, "ビッグボス楽天(最強配送)",
                  codes=saikyo_done, only=ship_codes)
    except LoginRequired:
        raise
    except Exception as e:
        logging.error("最強配送の追加 失敗: %s", e)
        errors.append("ビッグボス楽天(最強配送): %s" % e)

    # 名前を消すと検索に出なくなるため、Mark有で表示して店舗ごとに出品(Yahoo/wine.com/楽天)
    for sid, name in SHIP_SHOPS + [("5255", "ビッグボス楽天")]:
        try:
            if sid == "5255" and not saikyo_done:
                continue
            switch_shop(page, sid)
            set_conditions(page, "", True)
            n = search(page)
            logging.info("%s Mark有: %d件", name, n)
            if n:
                bulk_upload(page, only_shops=[sid],
                            only_codes=saikyo_done if sid == "5255" else only)
        except LoginRequired:
            raise
        except Exception as e:
            logging.error("出荷日表記 出品失敗 %s: %s", name, e)
            errors.append("%s(出品): %s" % (name, e))
    if not errors:
        clear_marks(page)
    else:
        logging.warning("失敗があるためMarkは外しません")
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--date", help="基準日(YYYY-MM-DD)。省略時は今日")
    ap.add_argument("--ship-offset", type=int, default=0,
                    help="出荷日表記(○月○日出荷)の対象日。0=当日(既定)、1=前日")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--ship-only", action="store_true",
                    help="予約テキストの処理を飛ばし、出荷日表記(+楽天の最強配送)の処理だけ行う")
    ap.add_argument("--only-codes", help="この商品コードだけ処理する(カンマ区切り。テスト用)")
    ap.add_argument("--clear-marks-only", action="store_true",
                    help="商品名の処理はせず、残っているMark(予約Claude)を外すだけ")
    a = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(os.path.join(here, "logs"), exist_ok=True)
    today = datetime.date.fromisoformat(a.date) if a.date else datetime.date.today()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(os.path.join(here, "logs", today.strftime("%Y%m%d") + ".log"),
                                      encoding="utf-8"), logging.StreamHandler()])
    dates = [today - datetime.timedelta(days=i) for i in range(1, a.days + 1)]
    ship_dates = [today - datetime.timedelta(days=a.ship_offset + i) for i in range(a.days)]
    logging.info("開始 対象発売日: %s 出荷日表記: %s dry_run=%s", [jp_date(d) for d in dates],
                 [ship_text(d) for d in ship_dates], a.dry_run)

    if a.clear_marks_only:
        try:
            page = find_crossmall_page()
            open_bulk_page(page)
            clear_marks(page)
        except LoginRequired:
            logging.error("ログインが切れています。自動化用Chromeでログインし直してください")
            return 2
        except Exception:
            logging.error("致命的エラー\n%s", traceback.format_exc())
            return 1
        logging.info("Mark解除のみ完了")
        return 0

    only = {c.strip() for c in a.only_codes.split(",") if c.strip()} if a.only_codes else None
    errors, total = [], 0
    try:
        page = find_crossmall_page()
        open_bulk_page(page)
        if not a.ship_only:
            for shop in SHOPS:
                try:
                    total += process_shop(page, shop, dates, a.dry_run, errors)
                except LoginRequired:
                    raise
                except Exception as e:
                    logging.error("店舗処理失敗 %s: %s", shop[1], e)
                    errors.append("%s: %s" % (shop[1], e))
            if total and not a.dry_run:
                bulk_upload(page)
                if not errors:  # 失敗があった日はMarkを残し、翌日以降に再実行できるようにする
                    clear_marks(page)
                else:
                    logging.warning("失敗があるためMarkは外しません")
            else:
                logging.info("更新0件のため一括出品処理はスキップ")
        total += shipping_job(page, ship_dates, a.dry_run, errors, only)
    except LoginRequired:
        logging.error("ログインが切れています。自動化用Chromeでログインし直してください")
        return 2
    except Exception:
        logging.error("致命的エラー\n%s", traceback.format_exc())
        return 1
    if errors:
        logging.error("失敗 %d件:\n%s", len(errors), "\n".join(errors))
        return 1
    logging.info("完了 更新%d件", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
