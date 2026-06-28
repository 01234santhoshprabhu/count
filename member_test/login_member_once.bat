@echo off
title NPTEL Member Login Setup
cd /d "%~dp0"
set PYTHONHOME=
set PYTHONPATH=

echo Opening the exact Chrome profile used by member automation...
echo Login here once with member2026@nptel.iitm.ac.in.
echo Do not use normal Chrome for this login.
echo.

C:\Python314\python.exe member_count_test.py --login

echo.
echo If it says login verified, now run start_automatic_test.bat.
pause
