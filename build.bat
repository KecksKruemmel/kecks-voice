@echo off
REM Baut dist\KecksVoice.exe (eine einzelne Datei, kein Python nötig).
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller || goto :fail
python make_icon.py || goto :fail
python -m PyInstaller --noconfirm --onefile --noconsole --name KecksVoice --icon kecksvoice.ico ^
  --collect-all faster_whisper --collect-all ctranslate2 --collect-all av ^
  --hidden-import pystray._win32 kecksvoice.py || goto :fail
echo.
echo Fertig: dist\KecksVoice.exe
pause
exit /b 0

:fail
echo.
echo Build fehlgeschlagen.
pause
exit /b 1
