@echo off
setlocal
cd /d "%~dp0.."
start "VITRAN Shopee Launcher" /min python tools\shopee_chrome_launcher.py
endlocal
