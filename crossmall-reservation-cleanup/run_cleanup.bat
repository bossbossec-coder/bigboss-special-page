@echo off
REM CrossMall reservation text cleanup (run daily 6:15 from Task Scheduler)
REM Same-day release items: --reserve-offset 0
cd /d "%~dp0"
python reservation_cleanup.py --days 1 --reserve-offset 0
exit /b %ERRORLEVEL%
