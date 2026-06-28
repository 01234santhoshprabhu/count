# Google Groups Member Count Test

This folder is fully separate from the live enrollment dashboard.

1. Install packages:
   `py -m pip install -r requirements.txt`
2. Run `login_google_groups.bat` once and sign in manually in the normal
   dedicated Chrome window.
3. Run `run_sample_10.bat`.
4. Run `start_test_dashboard.bat`.
5. After confirming the sample, run `run_all_test.bat`.

For automatic regeneration every five minutes, run:
`start_automatic_test.bat`

Test dashboard: http://127.0.0.1:8786/

Credentials are not stored in the Python script. Normal Chrome keeps the login
session inside `member_test/chrome_profile`. Keep the dedicated Chrome window
open while collecting counts.
