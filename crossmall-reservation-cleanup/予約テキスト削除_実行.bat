@echo off
REM 予約商品名の予約テキスト削除(毎朝6:15 タスクスケジューラから実行)
REM 事前に 自動化用Chrome起動.bat でChromeを起動・ログインしておくこと
cd /d "%~dp0"
python reservation_cleanup.py --days 1
exit /b %ERRORLEVEL%
