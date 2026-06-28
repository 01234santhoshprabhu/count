import json
import msvcrt
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
LOCK_FILE = BASE_DIR / "auto_member_test.lock"
LOG_FILE = BASE_DIR / "auto_member_test.log"
PROGRESS_JSON = BASE_DIR / "output" / "progress_test.json"
MAX_RUN_SECONDS = 1800
MEMBER_PROFILE_MARKER = str(BASE_DIR / "chrome_profile")
PUBLISH_RETRY_ATTEMPTS = 30
PUBLISH_RETRY_SECONDS = 30


def log(message):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as file:
        file.write(line + "\n")


def find_enroll_dir():
    candidates = [
        Path.home() / "Desktop" / "ENROLL",
        Path.home() / "OneDrive" / "Desktop" / "ENROLL",
        BASE_DIR.parents[1] / "ENROLL" if len(BASE_DIR.parents) > 1 else None,
    ]
    for path in candidates:
        if path and (path / "auto_publish_dashboard.py").exists():
            return path
    return candidates[0]


def acquire_process_lock():
    lock_handle = LOCK_FILE.open("a+")
    lock_handle.seek(0)
    if lock_handle.tell() == 0:
        lock_handle.write("0")
        lock_handle.flush()
    lock_handle.seek(0)
    try:
        msvcrt.locking(lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        lock_handle.close()
        return None
    return lock_handle


def write_timeout_progress():
    PROGRESS_JSON.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_JSON.write_text(
        json.dumps(
            {
                "updated_at": datetime.now().astimezone().isoformat(),
                "running": False,
                "completed": 0,
                "total_courses": 1058,
                "message": "Refresh timed out; automatic updater will retry.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def reset_member_browser():
    command = (
        "$marker = '"
        + MEMBER_PROFILE_MARKER.replace("'", "''")
        + "'; "
        + "Get-CimInstance Win32_Process | "
        + "Where-Object { $_.CommandLine -like '*chromedriver*' -or $_.CommandLine -like \"*$marker*\" } | "
        + "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
    )


def run_member_collector():
    lines = queue.Queue()

    def reader(pipe):
        try:
            for item in pipe:
                lines.put(item)
        finally:
            pipe.close()

    process = subprocess.Popen(
        [
            sys.executable,
            "member_count_test.py",
            "--all",
            "--workers",
            "24",
            "--timeout-policy",
            "previous",
        ],
        cwd=BASE_DIR,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    if process.stdout is not None:
        threading.Thread(target=reader, args=(process.stdout,), daemon=True).start()

    output_lines = []
    started = time.time()
    try:
        while True:
            while True:
                try:
                    line = lines.get_nowait()
                except queue.Empty:
                    break
                if line:
                    output_lines.append(line)
                    print(line, end="", flush=True)
                    with LOG_FILE.open("a", encoding="utf-8") as file:
                        file.write(line)

            if process.poll() is not None:
                while True:
                    try:
                        line = lines.get_nowait()
                    except queue.Empty:
                        break
                    output_lines.append(line)
                    print(line, end="", flush=True)
                    with LOG_FILE.open("a", encoding="utf-8") as file:
                        file.write(line)
                return process.returncode, "".join(output_lines)

            if time.time() - started > MAX_RUN_SECONDS:
                process.kill()
                return 124, "".join(output_lines)

            time.sleep(0.2)
    finally:
        if process.poll() is None:
            process.kill()


def run_cycle():
    log("Starting full 1,058-course member refresh.")
    returncode, output = run_member_collector()
    if returncode == 124:
        log(f"Member refresh exceeded {MAX_RUN_SECONDS} seconds and was stopped.")
        write_timeout_progress()
        reset_member_browser()
        return

    if returncode == 0:
        log("Member refresh completed successfully.")
        if publish_member_data_with_retries():
            log("Published member refresh to online dashboard.")
        else:
            log("Member refresh completed, but online publish will retry next cycle.")
    else:
        if output.strip():
            log(output.strip())
        log(f"Member refresh failed with code {returncode}.")
        lower_output = output.lower()
        recoverable_browser_error = any(
            marker in lower_output
            for marker in (
                "chrome window did not start",
                "invalid session id",
                "not connected to devtools",
                "chrome not reachable",
                "disconnected",
            )
        )
        if recoverable_browser_error:
            log("Resetting member Chrome after browser startup/session failure.")
            reset_member_browser()


def publish_member_data():
    enroll_dir = find_enroll_dir()
    if not enroll_dir.exists():
        log(f"Enrollment dashboard folder missing, cannot publish members: {enroll_dir}")
        return False

    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "import auto_publish_dashboard as a; raise SystemExit(0 if a.publish_member_update() else 1)",
            ],
            cwd=enroll_dir,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=420,
        )
    except subprocess.TimeoutExpired as exc:
        if exc.stdout:
            log(str(exc.stdout).strip())
        log("Member publish timed out; will retry next cycle.")
        return False

    if completed.stdout.strip():
        log(completed.stdout.strip())

    if completed.returncode == 0:
        return True

    log(f"Member publish failed with code {completed.returncode}.")
    return False


def publish_member_data_with_retries():
    for attempt in range(1, PUBLISH_RETRY_ATTEMPTS + 1):
        if publish_member_data():
            return True
        if attempt < PUBLISH_RETRY_ATTEMPTS:
            log(
                "Member publish is waiting for enrollment publisher lock; "
                f"retry {attempt + 1}/{PUBLISH_RETRY_ATTEMPTS} in {PUBLISH_RETRY_SECONDS} seconds."
            )
            time.sleep(PUBLISH_RETRY_SECONDS)
    return False


def main():
    interval_seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    lock_handle = acquire_process_lock()
    if lock_handle is None:
        print("The automatic member updater is already running.")
        return

    log(f"Automatic member updater started. Interval: {interval_seconds} seconds.")
    try:
        while True:
            started = time.time()
            try:
                run_cycle()
            except Exception as exc:
                log(f"Automatic refresh error: {exc}")
            elapsed = time.time() - started
            sleep_for = max(10, interval_seconds - elapsed)
            log(f"Next refresh starts in {int(sleep_for)} seconds.")
            time.sleep(sleep_for)
    finally:
        lock_handle.close()


if __name__ == "__main__":
    main()
