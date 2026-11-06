@echo off
REM Rakuten night price (Task Scheduler: every 5 minutes)
cd /d "%~dp0"
python yoru_price.py
exit /b %ERRORLEVEL%
