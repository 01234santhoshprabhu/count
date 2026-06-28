@echo off
title NPTEL Member Test Automatic Updater
cd /d "%~dp0"
set PYTHONHOME=
set PYTHONPATH=

powershell -NoProfile -Command "$profile = '%~dp0chrome_profile'; if (-not (Test-NetConnection 127.0.0.1 -Port 9223 -InformationLevel Quiet)) { Start-Process -FilePath 'C:\Program Files\Google\Chrome\Application\chrome.exe' -ArgumentList @('--remote-debugging-port=9223', ('--user-data-dir=' + '\"' + $profile + '\"'), '--profile-directory=Profile 1', '--disable-notifications', '--disable-popup-blocking', '--window-size=1400,900', 'https://groups.google.com/my-groups') }"

powershell -NoProfile -Command "if (-not (Get-NetTCPConnection -LocalPort 8786 -State Listen -ErrorAction SilentlyContinue)) { Start-Process -FilePath 'C:\Python314\python.exe' -ArgumentList 'test_server.py' -WorkingDirectory '%~dp0' -WindowStyle Hidden }"
start "" "http://127.0.0.1:8786/"

echo Starting member-count test updater...
echo The test data regenerates every 5 minutes.
echo Keep this window open. Closing it stops automatic regeneration.
echo.

:loop
"C:\Python314\python.exe" auto_update_member_test.py 300
echo.
echo Member updater stopped or crashed. Restarting in 60 seconds...
timeout /t 60 /nobreak
goto loop
