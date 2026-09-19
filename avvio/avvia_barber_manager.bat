@echo off
setlocal

cd /d "%~dp0"

echo Avvio Barber Manager...

start "" pythonw.exe "%~dp0app.py"

timeout /t 2 /nobreak >nul

start "" "http://127.0.0.1:5000"

exit