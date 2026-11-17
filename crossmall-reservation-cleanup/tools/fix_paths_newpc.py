# -*- coding: utf-8 -*-
"""新しいPCに移した au-excel-work の .py / .bat に残っている、古いPCの場所を書き換える。

使い方(このファイルを au-excel-work フォルダに置いて実行):
  python fix_paths_newpc.py           … 書き換える箇所を表示するだけ(何も変えない)
  python fix_paths_newpc.py --apply   … 実際に書き換える(元のファイルは backup フォルダに保存)

書き換える内容:
  1. C:\\Users\\user\\au-excel-work  →  このフォルダの場所(例 C:\\Users\\harag\\au-excel-work)
  2. Chrome / Thunderbird の場所の "(x86)" → 新しいPCに実際にある場所(ある場合だけ)
ファイルは文字のバイト列のまま置き換えるので、.py(UTF-8) も .bat(ANSI/Shift-JIS) も文字コードは変わらない。
ファイル名に「旧」が入っているもの(使っていない古い版)は触らない。
"""
import datetime
import glob
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OLD_DIR = r"C:\Users\user\au-excel-work"

PAIRS = [(OLD_DIR, HERE)]
for x86, new in [
    (r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
     r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    (r"C:\Program Files (x86)\Mozilla Thunderbird\thunderbird.exe",
     r"C:\Program Files\Mozilla Thunderbird\thunderbird.exe"),
]:
    if os.path.exists(new) and not os.path.exists(x86):
        PAIRS.append((x86, new))
    elif not os.path.exists(new) and not os.path.exists(x86):
        print("注意: 見つかりません(インストールされていない可能性): %s" % os.path.basename(new))


def variants(old, new):
    """大文字小文字の違い(c:\\users\\user など)にも対応する"""
    yield old.encode("ascii"), new
    yield old.lower().encode("ascii"), new


def main():
    apply = "--apply" in sys.argv
    if os.path.normcase(HERE) == os.path.normcase(OLD_DIR):
        print("このフォルダは古いPCと同じ場所です。書き換えは不要です。")
        return 0
    files = [f for f in glob.glob(os.path.join(HERE, "*.py")) + glob.glob(os.path.join(HERE, "*.bat"))
             if "旧" not in os.path.basename(f) and os.path.basename(f) != os.path.basename(__file__)]
    backup = os.path.join(HERE, "backup", "pathfix_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    changed = 0
    for f in sorted(files):
        raw = open(f, "rb").read()
        new_raw = raw
        notes = []
        for old, new in PAIRS:
            for old_b, new_s in variants(old, new):
                n = new_raw.count(old_b)
                if n:
                    enc = "utf-8" if f.lower().endswith(".py") else "cp932"
                    new_raw = new_raw.replace(old_b, new_s.encode(enc))
                    notes.append("  %d か所: %s  →  %s" % (n, old_b.decode("ascii"), new_s))
        if new_raw != raw:
            changed += 1
            print(os.path.basename(f))
            print("\n".join(notes))
            if apply:
                os.makedirs(backup, exist_ok=True)
                shutil.copy2(f, os.path.join(backup, os.path.basename(f)))
                open(f, "wb").write(new_raw)
    if not changed:
        print("書き換える箇所はありませんでした。")
    elif apply:
        print("\n%d 個のファイルを書き換えました。元のファイル: %s" % (changed, backup))
    else:
        print("\n(まだ何も変えていません。書き換えるときは: python fix_paths_newpc.py --apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
