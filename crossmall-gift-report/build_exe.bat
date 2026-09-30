@echo off
cd /d %~dp0

echo Installing required libraries...
pip install -r requirements.txt
pip install pyinstaller

echo.
echo Building exe file...
pyinstaller --onefile --console --name GiftCsvTool --distpath dist --workpath build --specpath build --collect-submodules selenium --collect-submodules keyring src\main.py

echo.
echo Build complete: dist\GiftCsvTool.exe
echo Copy this exe together with run_gift_csv.bat, config.json,
echo and msedgedriver.exe into one folder.
pause
