@echo off
cd /d "%~dp0"
py member_count_test.py --all --workers 12
pause

