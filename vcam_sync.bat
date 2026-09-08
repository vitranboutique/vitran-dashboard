@echo off
rem Tu dong quet kho video VCAM tren o may shop roi day len kho Gist cua app.
rem Chay dinh ky bang Task Scheduler (task: VITRAN - Dong bo video VCAM).
cd /d "%~dp0"
"C:\Users\ADMIN\AppData\Local\Programs\Python\Python310\python.exe" vcam_scan.py --push >> vcam_sync.log 2>&1
