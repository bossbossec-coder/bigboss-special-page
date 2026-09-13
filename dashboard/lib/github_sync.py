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
