import os
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import undetected_chromedriver as uc  # type: ignore

from safeway_coupons.chrome_driver import chrome_driver


@pytest.fixture(autouse=True)
def clear_chrome_env(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    for name in ("SWY_CHROME_PROFILE", "SWY_CHROME_HEADLESS"):
        monkeypatch.delenv(name, raising=False)
    yield


def chrome_options() -> Any:
    call = uc.Chrome.call_args
    assert call is not None
    return call.kwargs["options"]


def test_profile_persists_chrome_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = tmp_path / "chrome-profile"
    monkeypatch.setenv("SWY_CHROME_PROFILE", str(profile))

    with chrome_driver():
        pass

    options = chrome_options()
    assert f"--user-data-dir={profile}" in options.arguments
    assert "--incognito" not in options.arguments
    assert profile.is_dir()
    assert profile.stat().st_mode & 0o777 == 0o700


def test_stale_profile_locks_are_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = tmp_path / "chrome-profile"
    profile.mkdir()
    lock = profile / "SingletonLock"
    lock.symlink_to("previous-container-12345")
    monkeypatch.setenv("SWY_CHROME_PROFILE", str(profile))

    with chrome_driver():
        pass

    assert not lock.is_symlink()


def test_active_profile_locks_are_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = tmp_path / "chrome-profile"
    profile.mkdir()
    lock = profile / "SingletonLock"
    lock.symlink_to(f"{socket.gethostname()}-{os.getpid()}")
    monkeypatch.setenv("SWY_CHROME_PROFILE", str(profile))

    with chrome_driver():
        pass

    assert lock.is_symlink()


def test_driver_quits_when_authentication_fails() -> None:
    with pytest.raises(RuntimeError), chrome_driver():
        raise RuntimeError("authentication failed")

    assert uc.Chrome.return_value.quit.called


def test_default_uses_incognito() -> None:
    with chrome_driver():
        pass

    options = chrome_options()
    assert "--incognito" in options.arguments
    assert not any(
        argument.startswith("--user-data-dir=")
        for argument in options.arguments
    )


def test_headless_by_default() -> None:
    with chrome_driver():
        pass

    options = chrome_options()
    assert options.headless is True
    assert "--headless=new" in options.arguments


@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
def test_headless_can_be_disabled(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SWY_CHROME_HEADLESS", value)

    with chrome_driver():
        pass

    options = chrome_options()
    assert options.headless is False
    assert "--headless=new" not in options.arguments
