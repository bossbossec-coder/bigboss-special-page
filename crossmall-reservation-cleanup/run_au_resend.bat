@echo off
REM CrossMall: resend reservation-cleaned items to au (Wowma) only. Run daily 0:30 from Task Scheduler.
cd /d "%~dp0"
python reservation_cleanup.py --au-resend
exit /b %ERRORLEVEL%
