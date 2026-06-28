@echo off
cd /d "%~dp0"
py member_count_test.py --limit 10 --show-browser
pause

