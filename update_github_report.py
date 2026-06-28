import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests


BASE_DIR = Path(__file__).resolve().parent
COURSES_CSV = BASE_DIR / "courses.csv"
DOCS_DIR = BASE_DIR / "docs"
REPORT_CSV = DOCS_DIR / "enrollment_report.csv"
SUMMARY_JSON = DOCS_DIR / "summary.json"
MAX_WORKERS = 24
REQUEST_TIMEOUT = 5
RETRY_ATTEMPTS = 1
GLOBAL_TIMEOUT_SECONDS = 180
SECOND_PASS_DELAY_SECONDS = 1


def extract_course_id(url):
    match = re.search(r"(noc\d{2}_[a-z]+\d+)", str(url), re.IGNORECASE)
    if match:
        return match.group(1)
    return str(url).rstrip("/").split("/")[-1]


def fetch_count(course_id):
    api_url = (
        "https://onlinecourses.nptel.ac.in/e-learning/api/coursepreview"
        f"?course_id={course_id}"
    )
    last_error = None
    for _ in range(RETRY_ATTEMPTS):
        try:
            response = requests.get(
                api_url,
                timeout=REQUEST_TIMEOUT,
                verify=False,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            data = response.json()
            if response.status_code == 404 or data.get("status") == 404:
                return course_id, "Removed / Unavailable"
            payload = data.get("payload", {})
            if isinstance(payload, str):
                payload = json.loads(payload)
            student_count = payload.get("student_count")
            if student_count is None:
                last_error = "student_count missing"
                time.sleep(SECOND_PASS_DELAY_SECONDS)
                continue
            return course_id, int(student_count)
        except Exception as exc:
            last_error = exc
            time.sleep(SECOND_PASS_DELAY_SECONDS)
    return course_id, f"Temporary Error: {last_error}"


def load_previous_counts():
    if not REPORT_CSV.exists():
        return {}
    try:
        old_df = pd.read_csv(REPORT_CSV)
        old_df = old_df[old_df["Course_ID"].astype(str).ne("TOTAL")]
        old_values = pd.to_numeric(old_df["Learners_Enrolled"], errors="coerce")
        return {
            str(row["Course_ID"]): int(old_values.loc[index])
            for index, row in old_df.iterrows()
            if pd.notna(old_values.loc[index])
        }
    except Exception:
        return {}


def main():
    DOCS_DIR.mkdir(exist_ok=True)
    df = pd.read_csv(COURSES_CSV)
    df["Course_ID"] = df["Course_URL"].apply(extract_course_id)
    previous_counts = load_previous_counts()

    results = {}
    executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    try:
        futures = {
            executor.submit(fetch_count, cid): cid for cid in df["Course_ID"]
        }
        try:
            for future in as_completed(futures, timeout=GLOBAL_TIMEOUT_SECONDS):
                course_id, count = future.result()
                results[course_id] = count
        except TimeoutError:
            print(
                f"Enrollment HTTP phase exceeded {GLOBAL_TIMEOUT_SECONDS} seconds; "
                "using previous counts for unfinished courses."
            )
        for future, course_id in futures.items():
            if course_id not in results:
                previous = previous_counts.get(course_id)
                results[course_id] = (
                    previous
                    if previous is not None
                    else "Temporary Error: request timed out"
                )
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    df["Learners_Enrolled"] = df["Course_ID"].map(results)

    temporary_error_mask = df["Learners_Enrolled"].astype(str).str.startswith("Temporary Error:")
    df.loc[temporary_error_mask, "Learners_Enrolled"] = df.loc[
        temporary_error_mask, "Course_ID"
    ].map(previous_counts)
    df["Learners_Enrolled"] = df["Learners_Enrolled"].fillna("Temporary Error / No Previous Count")
    report_df = df[["Course_ID", "Learners_Enrolled"]].copy()
    numeric = pd.to_numeric(report_df["Learners_Enrolled"], errors="coerce")
    total = int(numeric.fillna(0).sum())
    total_row = pd.DataFrame([["TOTAL", total]], columns=["Course_ID", "Learners_Enrolled"])
    report_df = pd.concat([report_df, total_row], ignore_index=True)
    report_df.to_csv(REPORT_CSV, index=False)

    summary = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "course_count": int(len(df)),
        "numeric_count": int(numeric.notna().sum()),
        "error_count": int(numeric.isna().sum()),
        "total_enrollment": total,
        "top_courses": [
            {"course_id": str(row["Course_ID"]), "count": int(row["_count"])}
            for _, row in (
                df.assign(_count=numeric)
                .dropna(subset=["_count"])
                .sort_values("_count", ascending=False)
                .head(10)
                .iterrows()
            )
        ],
        "errors": [
            {
                "course_id": str(row["Course_ID"]),
                "course_url": str(row["Course_URL"]),
                "status": str(row["Learners_Enrolled"]),
            }
            for _, row in df[numeric.isna()].iterrows()
        ],
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Updated {REPORT_CSV}")
    print(f"Total enrollment: {total}")


if __name__ == "__main__":
    requests.packages.urllib3.disable_warnings()
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
