import json
import os
import sys


def _get_root():
    # exe化(PyInstaller --onefile)した場合、__file__はWindowsの一時フォルダを
    # 指してしまうため、実行中のexe自体がある場所を基準にする必要がある。
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


ROOT = _get_root()
_CONFIG_PATH = os.path.join(ROOT, "config.json")
_EXAMPLE_PATH = os.path.join(ROOT, "config.example.json")


def load_config():
    if not os.path.exists(_CONFIG_PATH):
        print(
            "[エラー] config.json が見つかりません。\n"
            f"{_EXAMPLE_PATH} をコピーして config.json という名前で保存し、\n"
            "クロスモールのログイン画面のURLとログインIDを入力してください。"
        )
        input("\nEnterキーで終了...")
        sys.exit(1)
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        config = json.load(f)

    # 相対パスはexe(またはリポジトリ)のフォルダ基準にそろえる。
    # タスクスケジューラから起動すると作業フォルダが変わることがあるため。
    browser = config["browser"]
    for key in ("edge_driver_path", "download_dir"):
        if browser.get(key) and not os.path.isabs(browser[key]):
            browser[key] = os.path.join(ROOT, browser[key])
    return config
