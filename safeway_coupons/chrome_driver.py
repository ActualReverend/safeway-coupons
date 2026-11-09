import contextlib
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Optional
from collections.abc import Iterator

import undetected_chromedriver as uc  # type: ignore

CHROMEDRIVER_PATH = (
    Path.home()
    / ".local"
    / "share"
    / "undetected_chromedriver"
    / "undetected_chromedriver"
)

CHROME_BINARY_NAMES = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "chrome",
)


class ChromeDriverDoesNotExist(Exception):
    pass


class ChromeProfileError(Exception):
    pass


def chrome_binary() -> str:
    """Return the path to the Chrome binary or raise a clear error."""
    configured = os.environ.get("CHROME_BINARY")
    if configured:
        if Path(configured).is_file():
            return configured
        raise ChromeDriverDoesNotExist(
            f"Error: CHROME_BINARY={configured} does not exist"
        )
    for name in CHROME_BINARY_NAMES:
        path = shutil.which(name)
        if path:
            return path
    raise ChromeDriverDoesNotExist(
        "Error: no Google Chrome/Chromium binary found. Install Chrome or "
        "set CHROME_BINARY to its path."
    )


def chrome_headless(headless: bool = True) -> bool:
    """Return whether Chrome should run headless.

    SWY_CHROME_HEADLESS overrides the default. Running with a visible window
    is useful for completing Safeway's one-time new-device verification.
    """
    configured = os.environ.get("SWY_CHROME_HEADLESS")
    if configured is None:
        return headless
    return configured.strip().lower() not in ("0", "false", "no", "off")


def chrome_profile_dir() -> Optional[Path]:
    """Return the persistent Chrome profile directory, creating it if needed.

    A persistent profile keeps Safeway's device-trust cookies between runs,
    so a new device verification is only required once.
    """
    configured = os.environ.get("SWY_CHROME_PROFILE")
    if not configured:
        return None
    path = Path(configured).expanduser()
    try:
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o700)
    except OSError as e:
        raise ChromeProfileError(
            f"Error: cannot use SWY_CHROME_PROFILE={path}: {e}"
        ) from e
    return path


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def clear_stale_profile_locks(profile: Path) -> bool:
    """Remove Chrome singleton locks left behind by a previous container.

    Chrome records a hostname and PID in ``SingletonLock``. A recreated
    container has a different hostname, so Chrome would otherwise refuse to
    reuse the persisted profile.
    """
    lock = profile / "SingletonLock"
    if lock.is_symlink():
        host, _, pid_text = os.readlink(lock).rpartition("-")
        if (
            host == socket.gethostname()
            and pid_text.isdigit()
            and _pid_is_running(int(pid_text))
        ):
            return False
    removed = False
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        with contextlib.suppress(FileNotFoundError):
            (profile / name).unlink()
            removed = True
    return removed


@contextlib.contextmanager
def chrome_driver(headless: bool = True) -> Iterator[uc.Chrome]:
    profile = chrome_profile_dir()
    headless = chrome_headless(headless)
    options = uc.ChromeOptions()
    options.binary_location = chrome_binary()
    options.headless = headless
    for option in [
        "--no-sandbox",
        "--disable-extensions",
        "--disable-application-cache",
        "--disable-gpu",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
    ]:
        options.add_argument(option)
    if profile is None:
        options.add_argument("--incognito")
    else:
        print(f"Using persistent Chrome profile at {profile}")
        if clear_stale_profile_locks(profile):
            print(f"Removed stale Chrome profile locks from {profile}")
        options.add_argument(f"--user-data-dir={profile}")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
    if headless:
        options.add_argument("--headless=new")
    else:
        print("Running Chrome with a visible window")
    driver = uc.Chrome(options=options)
    try:
        yield driver
    finally:
        # Always quit so Chrome releases the persistent profile and flushes
        # its cookies, even when authentication fails.
        driver.quit()


def chrome_driver_version() -> str:
    if not CHROMEDRIVER_PATH.is_file():
        raise ChromeDriverDoesNotExist(
            f"Error: {CHROMEDRIVER_PATH} does not exist"
        )
    cmd = [str(CHROMEDRIVER_PATH), "--version"]
    print(f"+ {' '.join(cmd)}", file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True)
    return result.stdout.decode()


def init() -> None:
    with contextlib.suppress(ChromeDriverDoesNotExist):
        print(chrome_driver_version())
        return
    print("Initializing Chrome Driver")
    with chrome_driver() as driver:
        print("Connect to example.com")
        driver.get("https://example.com")
    print(chrome_driver_version())
