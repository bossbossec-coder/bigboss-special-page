@echo off
REM CrossMall reservation text cleanup (run daily 6:15 from Task Scheduler)
REM --days 2 : today + yesterday (catches anything missed the day before)
REM --reserve-offset 0 : release date = today
cd /d "%~dp0"
python reservation_cleanup.py --days 2 --reserve-offset 0
exit /b %ERRORLEVEL%
