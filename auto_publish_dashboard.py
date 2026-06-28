import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
REPO_URL = "https://github.com/01234santhoshprabhu/count.git"
LOCK_FILE = BASE_DIR / "auto_publish_dashboard.lock"
DAILY_LOG_JSON = BASE_DIR / "docs" / "daily_log.json"
LOG_FILE = Path(
    os.environ.get(
        "AUTO_PUBLISH_LOG",
        str(BASE_DIR / "auto_publish_dashboard.log"),
    )
)


def log(message):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(line, flush=True)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as file:
            file.write(line + "\n")
    except PermissionError:
        print("[log file is locked; continuing without writing this line]", flush=True)


def run(command, cwd, timeout=600):
    log(f"Running: {' '.join(command)}")
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        if exc.stdout:
            log(str(exc.stdout).strip())
        log(f"Command timed out after {timeout} seconds: {' '.join(command)}")
        return 124

    if completed.stdout.strip():
        log(completed.stdout.strip())
    return completed.returncode


def member_output_dir():
    env_dir = os.environ.get("NPTEL_MEMBER_OUTPUT_DIR")
    candidates = [
        Path(env_dir) if env_dir else None,
        Path.home() / "Documents" / "Enrollment script" / "member_test" / "output",
        Path.home() / "OneDrive" / "Documents" / "Enrollment script" / "member_test" / "output",
        BASE_DIR.parent / "Enrollment script" / "member_test" / "output",
    ]
    for path in candidates:
        if path and (path / "summary_test.json").exists():
            return path
    return candidates[1]


def acquire_lock():
    if LOCK_FILE.exists():
        try:
            age_seconds = time.time() - LOCK_FILE.stat().st_mtime
            if age_seconds < 900:
                log("Another publish cycle appears to be running; skipping this cycle.")
                return False
            log("Removing stale publish lock.")
            LOCK_FILE.unlink()
        except OSError:
            log("Publish lock is busy; skipping this cycle.")
            return False

    try:
        LOCK_FILE.write_text(str(datetime.now()), encoding="utf-8")
        return True
    except OSError as exc:
        log(f"Could not create publish lock: {exc}")
        return False


def release_lock():
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def sync_member_files():
    output_dir = member_output_dir()
    member_files = {
        "summary_test.json": "member_summary.json",
        "member_counts_test.csv": "member_counts.csv",
    }
    for source_name, target_name in member_files.items():
        source = output_dir / source_name
        target = BASE_DIR / "docs" / target_name
        if source.exists():
            target.write_bytes(source.read_bytes())
        else:
            log(f"Member test file missing, skipping: {source}")


def record_daily_log_if_due():
    now = datetime.now().astimezone()
    if now.hour < 10:
        return

    summary_path = BASE_DIR / "docs" / "summary.json"
    member_path = BASE_DIR / "docs" / "member_summary.json"
    if not summary_path.exists() or not member_path.exists():
        log("Daily log skipped because enrollment or member summary is missing.")
        return

    try:
        enrollment = json.loads(summary_path.read_text(encoding="utf-8"))
        member = json.loads(member_path.read_text(encoding="utf-8"))
        existing = json.loads(DAILY_LOG_JSON.read_text(encoding="utf-8")) if DAILY_LOG_JSON.exists() else []
    except Exception as exc:
        log(f"Daily log read failed: {exc}")
        return

    today = now.date().isoformat()
    if any(entry.get("date") == today for entry in existing):
        return

    existing.append(
        {
            "date": today,
            "captured_at": now.isoformat(),
            "target_time": "10:00",
            "enrollment": {
                "updated_at": enrollment.get("updated_at"),
                "course_count": enrollment.get("course_count"),
                "numeric_count": enrollment.get("numeric_count"),
                "error_count": enrollment.get("error_count"),
                "total_enrollment": enrollment.get("total_enrollment"),
            },
            "member": {
                "updated_at": member.get("updated_at"),
                "total_courses": member.get("total_courses"),
                "numeric_count": member.get("numeric_count"),
                "error_count": member.get("error_count"),
                "total_members": member.get("total_members"),
            },
        }
    )
    DAILY_LOG_JSON.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    log(f"Daily 10 AM log saved for {today}.")


def copy_dashboard_files(target_dir):
    for filename in [
        "index.html",
        "test.html",
        "summary.json",
        "enrollment_report.csv",
        "member_summary.json",
        "member_counts.csv",
        "daily_log.json",
    ]:
        source = BASE_DIR / "docs" / filename
        target = target_dir / filename
        if source.exists():
            target.write_bytes(source.read_bytes())


def remove_publish_dir(path):
    shutil.rmtree(path, ignore_errors=True)


def cleanup_old_publish_dirs(current_dir=None):
    for path in BASE_DIR.glob(".publish-gh-pages-*"):
        if current_dir is not None and path == current_dir:
            continue
        remove_publish_dir(path)


def make_publish_dir():
    return Path(
        tempfile.mkdtemp(
            prefix=f"nptel-gh-pages-{datetime.now().strftime('%Y%m%d%H%M%S')}-{os.getpid()}-"
        )
    )


def publish_live_branch():
    publish_dir = make_publish_dir()

    try:
        clone_code = 1
        for attempt in range(1, 4):
            clone_code = run(
                ["git", "clone", "--depth", "1", "--branch", "gh-pages", REPO_URL, str(publish_dir)],
                BASE_DIR,
                timeout=240,
            )
            if clone_code == 0:
                break
            log(f"Could not clone gh-pages branch on attempt {attempt}; retrying after network delay.")
            remove_publish_dir(publish_dir)
            publish_dir = make_publish_dir()
            time.sleep(20 * attempt)

        if clone_code != 0:
            log("Could not clone gh-pages branch after retries; skipping publish.")
            return False

        copy_dashboard_files(publish_dir)
        run(["git", "config", "user.name", "NPTEL Automation"], publish_dir)
        run(["git", "config", "user.email", "nptel@example.com"], publish_dir)
        run(
            [
                "git",
                "add",
                "index.html",
                "test.html",
                "summary.json",
                "enrollment_report.csv",
                "member_summary.json",
                "member_counts.csv",
                "daily_log.json",
            ],
            publish_dir,
        )
        commit_code = run(["git", "commit", "-m", "Auto refresh live dashboard data"], publish_dir)
        if commit_code != 0:
            log("No live data change to commit.")
            return True

        push_code = 1
        for attempt in range(1, 4):
            push_code = run(["git", "push", "origin", "gh-pages"], publish_dir, timeout=240)
            if push_code == 0:
                return True
            log(f"Push rejected or network failed; pulling latest gh-pages and retrying attempt {attempt}.")
            run(["git", "pull", "--rebase", "origin", "gh-pages"], publish_dir, timeout=240)
            time.sleep(10 * attempt)

        log("Live publish push failed after retries.")
        return False
    finally:
        remove_publish_dir(publish_dir)
        cleanup_old_publish_dirs()


def publish_member_update():
    if not acquire_lock():
        return False
    try:
        sync_member_files()
        record_daily_log_if_due()
        return publish_live_branch()
    finally:
        release_lock()


def publish_once():
    if not acquire_lock():
        return False

    try:
        return publish_once_locked()
    finally:
        release_lock()


def publish_once_locked():
    code = run([sys.executable, "update_github_report.py"], BASE_DIR)
    if code != 0:
        log("Report update failed; skipping publish.")
        return False

    sync_member_files()
    record_daily_log_if_due()
    return publish_live_branch()


def main():
    interval_seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    log(f"Auto publisher started. Interval: {interval_seconds} seconds.")
    while True:
        started = time.time()
        try:
            publish_once()
        except Exception as exc:
            log(f"Auto publish error: {exc}")
        elapsed = time.time() - started
        sleep_for = interval_seconds
        log(f"Sleeping for {int(sleep_for)} seconds.")
        time.sleep(sleep_for)


if __name__ == "__main__":
    main()
