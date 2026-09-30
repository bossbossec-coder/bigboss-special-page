"""ギフト売上CSV 自動ダウンロードツール(クロスモール「商品注文分析」)

使い方:
  run_gift_csv.bat              メニューから選ぶ(手動で実行するとき)
  run_gift_csv.bat --yesterday  前日分を1日だけダウンロード(毎日の自動実行用)
"""
import os
import sys
import traceback
from datetime import date, datetime, timedelta
from getpass import getpass

from config import ROOT, load_config
from crossmall import CrossMallError, CrossMallSession

KEYRING_SERVICE = "crossmall-gift-report"


def safe_getpass(prompt):
    """getpassが使えない環境でも異常終了しないようにするフォールバック付き入力。"""
    try:
        return getpass(prompt)
    except Exception:
        print("(この環境では入力内容を隠せないため、そのまま画面に表示されます)")
        return input(prompt)


def get_password(login_id, interactive):
    """パスワードを取得する。

    毎日の自動実行では画面入力ができないため、Windowsの「資格情報マネージャー」に
    保存したものを使う(ファイルやプログラム内には保存しない)。
    """
    try:
        import keyring

        saved = keyring.get_password(KEYRING_SERVICE, login_id)
    except Exception:
        keyring = None
        saved = None
    if saved:
        return saved
    if not interactive:
        raise CrossMallError(
            "パスワードが保存されていません。一度 run_gift_csv.bat をダブルクリックして"
            "手動で実行し、パスワードを保存してください。"
        )

    print("\nクロスモールのログインパスワードを入力してください。")
    print("(入力した文字は画面に表示されませんが、そのまま入力してEnterを押してください)")
    password = safe_getpass("パスワード: ")
    if keyring is not None:
        answer = input(
            "\nこのパスワードをパソコンに保存しますか?\n"
            "(Windowsの資格情報マネージャーに保存され、毎日の自動実行で使われます) [y/n]: "
        )
        if answer.strip().lower() == "y":
            keyring.set_password(KEYRING_SERVICE, login_id, password)
            print("保存しました。")
    return password


def csv_path_for(download_dir, day):
    return os.path.join(download_dir, f"ギフト_{day.isoformat()}.csv")


def date_range(start, end):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def parse_date(text):
    return datetime.strptime(text.strip().replace("-", "/"), "%Y/%m/%d").date()


def log(message):
    """画面とログファイルの両方に記録する(自動実行時は画面が見られないため)。"""
    print(message)
    try:
        with open(os.path.join(ROOT, "gift_csv_log.txt"), "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}\n")
    except OSError:
        pass


def download_days(config, password, days, overwrite, interactive):
    download_dir = config["browser"]["download_dir"]
    targets = [d for d in days if overwrite or not os.path.exists(csv_path_for(download_dir, d))]
    skipped = len(days) - len(targets)
    if skipped:
        log(f"ダウンロード済みの{skipped}日分は飛ばします。")
    if not targets:
        log("ダウンロードが必要な日はありませんでした。")
        return

    log(f"クロスモールにログインし、{len(targets)}日分をダウンロードします...")
    session = CrossMallSession(config, password)
    try:
        session.login()
        session.open_order_analysis()
        for i, day in enumerate(targets, start=1):
            downloaded = session.download_day(day)
            final_path = csv_path_for(download_dir, day)
            if os.path.exists(final_path):
                os.remove(final_path)
            os.rename(downloaded, final_path)
            log(f"  ({i}/{len(targets)}) {day:%Y/%m/%d} → {os.path.basename(final_path)}")
    except Exception:
        if interactive:
            print("\n[エラーが発生しました。開いているブラウザの画面を確認してください]")
            input("確認が終わったら、Enterキーを押すとブラウザが閉じます...")
        raise
    finally:
        session.close()
    log(f"完了しました。保存先: {download_dir}")


def run_interactive(config):
    backfill = config["backfill"]
    print("=" * 50)
    print(" ギフト売上CSV 自動ダウンロードツール")
    print("=" * 50)
    print(f"\n1: 昨年分をまとめてダウンロード({backfill['date_from']}〜{backfill['date_to']})")
    print("2: 前日分をダウンロード")
    print("3: 日付を指定してダウンロード")
    choice = input("\n番号を入力してEnterを押してください: ").strip()

    if choice == "1":
        days = list(date_range(parse_date(backfill["date_from"]), parse_date(backfill["date_to"])))
        overwrite = False
    elif choice == "2":
        days = [date.today() - timedelta(days=1)]
        overwrite = True
    elif choice == "3":
        start = parse_date(input("開始日 (例 2025/10/15): "))
        end = parse_date(input("終了日 (例 2025/10/20): "))
        days = list(date_range(start, end))
        overwrite = input("ダウンロード済みの日も取り直しますか? [y/n]: ").strip().lower() == "y"
    else:
        print("1〜3の番号を入力してください。")
        return

    password = get_password(config["site"]["login_id"], interactive=True)
    download_days(config, password, days, overwrite, interactive=True)


def main():
    config = load_config()
    if "--yesterday" in sys.argv:
        # タスクスケジューラからの自動実行。画面入力は一切行わない。
        password = get_password(config["site"]["login_id"], interactive=False)
        download_days(
            config, password, [date.today() - timedelta(days=1)], overwrite=True, interactive=False
        )
        return
    run_interactive(config)
    input("\nEnterキーで終了...")


if __name__ == "__main__":
    interactive = "--yesterday" not in sys.argv
    try:
        main()
    except CrossMallError as e:
        log(f"[エラー] {e}")
        if interactive:
            print("\n処理を中断しました。ダウンロード済みの日は保存されています。")
            print("もう一度実行すると、続きの日からダウンロードします。")
            input("\nEnterキーで終了...")
        sys.exit(1)
    except Exception:
        log("[予期しないエラーが発生しました]\n" + traceback.format_exc())
        if interactive:
            input("\nEnterキーで終了...")
        sys.exit(1)
