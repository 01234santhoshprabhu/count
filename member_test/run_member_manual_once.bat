@echo off
title NPTEL Member Manual Refresh
cd /d "%~dp0"
set PYTHONHOME=
set PYTHONPATH=

echo Running one member-count refresh only.
echo This does not start the automatic loop.
echo.

C:\Python314\python.exe member_count_test.py --all --workers 24 --timeout-policy previous

echo.
echo Manual member refresh finished.
pause
