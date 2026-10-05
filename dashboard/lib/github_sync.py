"""アップロードしたExcelファイルをGitHubリポジトリにも保存するための補助モジュール。

クラウド（Streamlit Community Cloudなど）にデプロイした場合、アプリのファイルは
再起動のたびに消えてしまうことがある。そこでアップロードされたファイルを
GitHub側にも保存しておき、次回の起動時にも同じファイルが読み込まれるようにする。
"""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import requests

API_ROOT = "https://api.github.com"
FILE_DOWNLOAD_TIMEOUT = 8  # 秒。1ファイルずつ直列に待つと遅い時に何分も止まって
# しまうため、ファイル取得は並列化した上でこの秒数で見切りをつける。


@dataclass
class GitHubSyncResult:
    ok: bool
    message: str


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def upload_file_to_github(
    *,
    repo: str,
    branch: str,
    token: str,
    path_in_repo: str,
    content_bytes: bytes,
    commit_message: str,
) -> GitHubSyncResult:
    """指定したファイルをGitHubリポジトリに作成・上書きする。

    repo: "owner/repo" 形式
    path_in_repo: リポジトリ内のパス（例: "dashboard/data/incoming/渋谷店_売上.xlsx"）
    """
    url = f"{API_ROOT}/repos/{repo}/contents/{path_in_repo}"

    try:
        existing = requests.get(url, headers=_headers(token), params={"ref": branch}, timeout=20)
    except requests.RequestException as exc:
        return GitHubSyncResult(False, f"GitHubへの接続に失敗しました: {exc}")

    sha = None
    if existing.status_code == 200:
        sha = existing.json().get("sha")
    elif existing.status_code not in (404,):
        return GitHubSyncResult(
            False, f"GitHubの確認でエラーが発生しました（status={existing.status_code}）: {existing.text[:200]}"
        )

    payload = {
        "message": commit_message,
        "content": base64.b64encode(content_bytes).decode("ascii"),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    try:
        resp = requests.put(url, headers=_headers(token), json=payload, timeout=20)
    except requests.RequestException as exc:
        return GitHubSyncResult(False, f"GitHubへの保存に失敗しました: {exc}")

    if resp.status_code not in (200, 201):
        return GitHubSyncResult(
            False, f"GitHubへの保存でエラーが発生しました（status={resp.status_code}）: {resp.text[:200]}"
        )

    return GitHubSyncResult(True, "GitHubに保存しました。")


def _download_one(name: str, download_url: str) -> tuple[str, bytes] | None:
    try:
        file_resp = requests.get(download_url, timeout=FILE_DOWNLOAD_TIMEOUT)
    except requests.RequestException:
        return None
    if file_resp.status_code != 200:
        return None
    return name, file_resp.content


def download_folder_files(
    *,
    repo: str,
    branch: str,
    token: str,
    path_in_repo: str,
    suffix: str = ".xlsx",
) -> list[tuple[str, bytes]] | None:
    """GitHubリポジトリの指定フォルダにある、拡張子が一致するファイルを
    全件ダウンロードする。取得に失敗した場合はNoneを返す（呼び出し側では、
    既にローカルにある内容をそのまま使い続けるフォールバックとして扱う）。

    Streamlit Cloud側の「GitHubの変更を検知して自動デプロイする」機能の
    タイミングに依存すると、コンテナ側の反映が遅れたり行われなかったりして
    「自動アップロードは成功しているのに画面には反映されない」状態が
    起こり得るため、アプリ自身が定期的にGitHubから直接最新のファイルを
    取得できるようにするための関数。

    ファイルは1つずつ順番にではなく並列で取得する。直列に取得していた頃は、
    GitHub側がたまたま遅い瞬間に当たると「1ファイルあたり最大20秒 × 店舗数」
    待たされてしまい、スマホで何分もぐるぐる回ったまま開かなくなる不具合が
    あったため。
    """
    url = f"{API_ROOT}/repos/{repo}/contents/{path_in_repo}"
    try:
        resp = requests.get(url, headers=_headers(token), params={"ref": branch}, timeout=FILE_DOWNLOAD_TIMEOUT)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None

    entries = resp.json()
    if not isinstance(entries, list):
        return None

    targets = [
        (entry.get("name", ""), entry.get("download_url"))
        for entry in entries
        if entry.get("type") == "file"
        and entry.get("name", "").endswith(suffix)
        and entry.get("download_url")
    ]

    files: list[tuple[str, bytes]] = []
    if not targets:
        return files
    with ThreadPoolExecutor(max_workers=min(8, len(targets))) as executor:
        futures = [executor.submit(_download_one, name, download_url) for name, download_url in targets]
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                files.append(result)

    return files
