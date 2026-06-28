@echo off
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9223 --user-data-dir="%~dp0chrome_profile" --profile-directory=Default --window-size=1400,900 "https://groups.google.com/my-groups"
