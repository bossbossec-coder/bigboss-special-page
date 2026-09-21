"""アップロードしたExcelファイルをGitHubリポジトリにも保存するための補助モジュール。

クラウド（Streamlit Community Cloudなど）にデプロイした場合、アプリのファイルは
再起動のたびに消えてしまうことがある。そこでアップロードされたファイルを
GitHub側にも保存しておき、次回の起動時にも同じファイルが読み込まれるようにする。
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

import requests

API_ROOT = "https://api.github.com"


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
    """
    url = f"{API_ROOT}/repos/{repo}/contents/{path_in_repo}"
    try:
        resp = requests.get(url, headers=_headers(token), params={"ref": branch}, timeout=20)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None

    entries = resp.json()
    if not isinstance(entries, list):
        return None

    files: list[tuple[str, bytes]] = []
    for entry in entries:
        name = entry.get("name", "")
        download_url = entry.get("download_url")
        if entry.get("type") != "file" or not name.endswith(suffix) or not download_url:
            continue
        try:
            file_resp = requests.get(download_url, timeout=20)
        except requests.RequestException:
            continue
        if file_resp.status_code != 200:
            continue
        files.append((name, file_resp.content))

    return files
