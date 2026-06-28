import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from datetime import datetime
from pathlib import Path

import requests
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait


BASE_DIR = Path(__file__).resolve().parent
COURSES_CSV = BASE_DIR / "courses_test.csv"
PROFILE_DIR = BASE_DIR / "chrome_profile"
PROFILE_NAME = "Profile 1"
CHROME_PATH = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
DEBUG_PORT = 9223
OUTPUT_DIR = BASE_DIR / "output"
REPORT_CSV = OUTPUT_DIR / "member_counts_test.csv"
SUMMARY_JSON = OUTPUT_DIR / "summary_test.json"
PROGRESS_JSON = OUTPUT_DIR / "progress_test.json"
DOMAIN = "nptel.iitm.ac.in"
GROUPS_HOME = "https://groups.google.com/my-groups"
LOGIN_TEST_COURSE = "noc26_cy49"
REMOVED_COURSES = {
    "noc26_ce86",
    "noc26_ce92",
    "noc26_hs123",
    "noc26_me104",
}
COUNT_RE = re.compile(r"(?<!\d)([\d,]+)\s+members?\b", re.IGNORECASE)
COURSE_RE = re.compile(r"(noc\d{2}_[a-z]+\d+)", re.IGNORECASE)
HTTP_TIMEOUT = 12
HTTP_ATTEMPTS = 1
HTTP_GLOBAL_TIMEOUT = 600


def course_id_from_url(value):
    match = COURSE_RE.search(str(value))
    if not match:
        raise ValueError(f"Could not find course ID in: {value}")
    return match.group(1).lower()


def group_name(course_id):
    return course_id.replace("_", "-") + "-announce"


def group_url(course_id):
    return f"https://groups.google.com/a/{DOMAIN}/g/{group_name(course_id)}"


def load_course_ids():
    if not COURSES_CSV.exists():
        raise FileNotFoundError(f"Missing course list: {COURSES_CSV}")
    with COURSES_CSV.open(newline="", encoding="utf-8-sig") as file:
        rows = csv.DictReader(file)
        values = [course_id_from_url(row["Course_URL"]) for row in rows]
    return list(dict.fromkeys(values))


def browser_is_ready():
    try:
        response = requests.get(
            f"http://127.0.0.1:{DEBUG_PORT}/json/version", timeout=2
        )
        return response.ok
    except requests.RequestException:
        return False


def ensure_member_browser():
    if browser_is_ready():
        return
    if not CHROME_PATH.exists():
        raise FileNotFoundError(f"Chrome was not found at {CHROME_PATH}")
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [
            str(CHROME_PATH),
            f"--remote-debugging-port={DEBUG_PORT}",
            f"--user-data-dir={PROFILE_DIR}",
            f"--profile-directory={PROFILE_NAME}",
            "--disable-notifications",
            "--disable-popup-blocking",
            "--window-size=1400,900",
            GROUPS_HOME,
        ]
    )
    for _ in range(20):
        if browser_is_ready():
            return
        time.sleep(1)
    raise RuntimeError("The dedicated member-count Chrome window did not start.")


def chrome_options():
    options = Options()
    options.debugger_address = f"127.0.0.1:{DEBUG_PORT}"
    options.page_load_strategy = "eager"
    return options


def create_driver():
    ensure_member_browser()
    driver = webdriver.Chrome(options=chrome_options())
    driver.set_page_load_timeout(12)
    return driver


def stop_loading(driver):
    try:
        driver.execute_script("window.stop();")
    except Exception:
        pass


def login():
    ensure_member_browser()
    print()
    print("A normal dedicated Chrome window is open.")
    print(f"Chrome profile folder: {PROFILE_DIR}")
    print(f"Chrome profile name: {PROFILE_NAME}")
    print("Click Sign in and use the Google account that has all NPTEL groups.")
    print(f"Then open this known group and confirm its member count is visible:")
    print(group_url(LOGIN_TEST_COURSE))
    input("When the member count is visible, return here and press Enter...")

    driver = create_driver()
    try:
        course_id, count, status, _ = fetch_browser(driver, LOGIN_TEST_COURSE)
        if count is None:
            raise RuntimeError(
                f"Login/account verification failed for {course_id}: {status}. "
                "Select the Google account that can open the NPTEL group."
            )
        print(
            "Login verified and saved in the separate member_test Chrome profile. "
            f"{course_id}: {count} members."
        )
    finally:
        driver.service.stop()


def session_from_driver(driver):
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": driver.execute_script("return navigator.userAgent"),
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    for cookie in driver.get_cookies():
        session.cookies.set(
            cookie["name"],
            cookie["value"],
            domain=cookie.get("domain"),
            path=cookie.get("path", "/"),
        )
    return session


def parse_member_count(text):
    match = COUNT_RE.search(text or "")
    return int(match.group(1).replace(",", "")) if match else None


def fetch_http(headers, cookies, course_id):
    url = group_url(course_id)
    last_error = None
    for attempt in range(HTTP_ATTEMPTS):
        try:
            session = requests.Session()
            session.headers.update(headers)
            session.cookies.update(cookies)
            response = session.get(url, timeout=HTTP_TIMEOUT, allow_redirects=True)
            if "accounts.google.com" in response.url:
                return course_id, None, "Login required", "http"
            count = parse_member_count(response.text)
            if count is not None:
                return course_id, count, "OK", "http"
            if response.status_code == 404:
                return course_id, None, "Group not found", "http"
            return course_id, None, "Needs browser check", "http"
        except Exception as exc:
            last_error = exc
            if attempt < HTTP_ATTEMPTS - 1:
                time.sleep(1)
    return course_id, None, f"HTTP error: {last_error}", "http"


def load_previous_counts():
    if not REPORT_CSV.exists():
        return {}
    try:
        with REPORT_CSV.open(newline="", encoding="utf-8-sig") as file:
            return {
                row["course_id"]: int(row["member_count"])
                for row in csv.DictReader(file)
                if row["member_count"].strip().isdigit()
            }
    except Exception:
        return {}


def fetch_browser(driver, course_id):
    url = group_url(course_id)
    try:
        driver.get(url)
    except TimeoutException:
        stop_loading(driver)

    if "accounts.google.com" in driver.current_url:
        return course_id, None, "Login required", "browser"
    if "groups.google.com/access-error" in driver.current_url:
        return course_id, None, "Wrong Google account or no group access", "browser"

    try:
        WebDriverWait(driver, 12).until(
            lambda current: parse_member_count(current.find_element(By.TAG_NAME, "body").text)
            is not None
            or "doesn't exist" in current.find_element(By.TAG_NAME, "body").text.lower()
            or "not found" in current.find_element(By.TAG_NAME, "body").text.lower()
        )
    except TimeoutException:
        pass

    body = driver.find_element(By.TAG_NAME, "body").text
    count = parse_member_count(body)
    if count is not None:
        return course_id, count, "OK", "browser"
    if "doesn't exist" in body.lower() or "not found" in body.lower():
        return course_id, None, "Group not found", "browser"
    return course_id, None, "Count not visible", "browser"


def write_outputs(rows, total_courses, started_at, running):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda row: row["course_id"])
    with REPORT_CSV.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["course_id", "group_name", "member_count", "status", "method"],
        )
        writer.writeheader()
        writer.writerows(ordered)

    numeric = [row for row in ordered if isinstance(row["member_count"], int)]
    summary = {
        "updated_at": datetime.now().astimezone().isoformat(),
        "started_at": started_at,
        "running": running,
        "total_courses": total_courses,
        "completed": len(ordered),
        "numeric_count": len(numeric),
        "error_count": len(ordered) - len(numeric),
        "total_members": sum(row["member_count"] for row in numeric),
        "rows": ordered,
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    PROGRESS_JSON.write_text(
        json.dumps(
            {
                "updated_at": summary["updated_at"],
                "running": running,
                "completed": len(ordered),
                "total_courses": total_courses,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def write_progress(completed, total_courses, running, message):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PROGRESS_JSON.write_text(
        json.dumps(
            {
                "updated_at": datetime.now().astimezone().isoformat(),
                "running": running,
                "completed": completed,
                "total_courses": total_courses,
                "message": message,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def collect(limit=None, workers=12, show_browser=False, timeout_policy="previous"):
    course_ids = load_course_ids()
    if limit:
        course_ids = course_ids[:limit]
    started_at = datetime.now().astimezone().isoformat()
    previous_counts = load_previous_counts()
    rows = [
        {
            "course_id": course_id,
            "group_name": group_name(course_id),
            "member_count": "",
            "status": "Removed / Unavailable",
            "method": "enrollment status",
        }
        for course_id in course_ids
        if course_id in REMOVED_COURSES
    ]
    active_course_ids = [
        course_id for course_id in course_ids if course_id not in REMOVED_COURSES
    ]
    write_progress(
        len(rows),
        len(course_ids),
        True,
        "Starting Google Groups member refresh",
    )

    driver = create_driver()
    try:
        try:
            driver.get(group_url(LOGIN_TEST_COURSE))
        except TimeoutException:
            stop_loading(driver)
        if "accounts.google.com" in driver.current_url:
            raise RuntimeError(
                "Google login is required. Run: py member_count_test.py --login"
            )
        if "groups.google.com/access-error" in driver.current_url:
            raise RuntimeError(
                "Wrong Google account or no group access. Open login_member_once.bat "
                "and choose member2026@nptel.iitm.ac.in."
            )

        session = session_from_driver(driver)
        headers = dict(session.headers)
        cookies = session.cookies.copy()
        http_results = {}
        executor = ThreadPoolExecutor(max_workers=max(1, workers))
        try:
            futures = {
                executor.submit(fetch_http, headers, cookies, course_id): course_id
                for course_id in active_course_ids
            }
            try:
                for future in as_completed(futures, timeout=HTTP_GLOBAL_TIMEOUT):
                    course_id, count, status, method = future.result()
                    http_results[course_id] = (count, status, method)
            except TimeoutError:
                print(
                    f"HTTP phase exceeded {HTTP_GLOBAL_TIMEOUT} seconds; "
                    "using previous counts for unfinished courses."
                )
            for future, course_id in futures.items():
                if course_id not in http_results:
                    http_results[course_id] = (
                        None,
                        "HTTP timeout",
                        "http",
                    )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        for index, course_id in enumerate(active_course_ids, start=1):
            count, status, method = http_results[course_id]
            should_browser_check = (
                count is None
                and (
                    status == "Needs browser check"
                    or (status.startswith("HTTP") and timeout_policy == "browser")
                )
            )
            if should_browser_check:
                course_id, count, status, method = fetch_browser(driver, course_id)
            if count is None and course_id in previous_counts:
                count = previous_counts[course_id]
                if status.startswith("HTTP"):
                    status = "Previous count (HTTP timeout)"
                else:
                    status = "Previous count (temporary error)"
                method = "previous"

            rows.append(
                {
                    "course_id": course_id,
                    "group_name": group_name(course_id),
                    "member_count": count if count is not None else "",
                    "status": status,
                    "method": method,
                }
            )
            completed = len(rows)
            if index % 5 == 0 or index == len(active_course_ids):
                write_progress(
                    completed,
                    len(course_ids),
                    True,
                    f"Checking member counts: {completed}/{len(course_ids)}",
                )
                print(f"Completed {completed}/{len(course_ids)}")
    finally:
        driver.service.stop()

    write_outputs(rows, len(course_ids), started_at, False)
    write_progress(
        len(rows),
        len(course_ids),
        False,
        "Latest member refresh completed",
    )
    print(f"Test report: {REPORT_CSV}")
    print(f"Test dashboard data: {SUMMARY_JSON}")


def main():
    parser = argparse.ArgumentParser(
        description="Isolated Google Groups member-count test collector."
    )
    parser.add_argument("--login", action="store_true", help="Save Google login session.")
    parser.add_argument("--limit", type=int, help="Test only the first N courses.")
    parser.add_argument("--all", action="store_true", help="Collect every test course.")
    parser.add_argument("--workers", type=int, default=12, help="Fast HTTP worker count.")
    parser.add_argument(
        "--timeout-policy",
        choices=["previous", "browser"],
        default="previous",
        help=(
            "Use previous count for HTTP timeouts in fast mode, or verify every "
            "timeout through Chrome in accurate mode."
        ),
    )
    parser.add_argument(
        "--show-browser", action="store_true", help="Keep collection browser visible."
    )
    args = parser.parse_args()

    if args.login:
        login()
        return
    if not args.all and not args.limit:
        parser.error("Choose --limit N for testing or --all for every course.")
    collect(
        limit=args.limit,
        workers=args.workers,
        show_browser=args.show_browser,
        timeout_policy=args.timeout_policy,
    )


if __name__ == "__main__":
    try:
        main()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)
    except KeyboardInterrupt:
        print("Stopped.")
        sys.exit(130)
    except Exception as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

