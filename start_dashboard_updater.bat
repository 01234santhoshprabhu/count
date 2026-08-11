@echo off
title NPTEL Dashboard Auto Updater
cd /d "%~dp0"
set PYTHONHOME=
set PYTHONPATH=
set AUTO_PUBLISH_LOG=%~dp0auto_publish_dashboard_%DATE:~-4%%DATE:~3,2%%DATE:~0,2%_%TIME:~0,2%%TIME:~3,2%%TIME:~6,2%.log
set AUTO_PUBLISH_LOG=%AUTO_PUBLISH_LOG: =0%
echo Starting NPTEL dashboard auto updater...
echo.
echo Keep this window open. If this window is closed, live updates will stop.
echo.
"C:\Python314\python.exe" auto_publish_dashboard.py 300
echo.
echo Updater stopped. Check the dated auto_publish_dashboard log file for details.
pause
