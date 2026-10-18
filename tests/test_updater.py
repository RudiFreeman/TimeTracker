"""Автообновление: какой файл релиза берёт Windows и какой — Mac. Без сети."""
import os

import pytest

from timetracker import updater

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WIN = {"name": "TimeTracker-2.4.0.zip", "browser_download_url": "https://github.com/x/win.zip",
       "size": 10, "digest": "sha256:" + "a" * 64}
MAC = {"name": "TimeTracker-2.4.0-mac.dmg", "browser_download_url": "https://github.com/x/mac.dmg",
       "size": 20, "digest": "sha256:" + "b" * 64}


def release_data(*assets):
    return {"tag_name": "v99.0.0", "html_url": "https://github.com/x", "body": "## Что нового\n- всё", "assets": list(assets)}


@pytest.mark.parametrize("order", [(WIN, MAC), (MAC, WIN)])
def test_pick_asset_per_system(order):
    assert updater.pick_asset(order, mac=False) is WIN
    assert updater.pick_asset(order, mac=True) is MAC


def test_old_windows_versions_still_get_the_windows_zip():
    """Версии до 2.3.2 берут ПЕРВЫЙ .zip релиза. Mac-файл поэтому .dmg: в любом порядке они получат Windows."""
    for assets in ((WIN, MAC), (MAC, WIN)):
        zips = [a for a in assets if a["name"].lower().endswith(".zip")]
        assert zips[0] is WIN


def test_mac_build_is_never_a_zip():
    with open(os.path.join(ROOT, "build_mac.sh"), encoding="utf-8") as f:
        script = f.read()
    assert '-mac.dmg"' in script and "-mac.zip" not in script


def test_release_without_file_for_this_system_is_not_offered(monkeypatch):
    monkeypatch.setattr(updater, "MAC", True)
    release = updater.Release(release_data(WIN))  # Mac-сборку ещё не выложили
    assert release.url is None and not release.is_newer()


def test_release_takes_file_for_this_system(monkeypatch):
    for mac, asset in ((False, WIN), (True, MAC)):
        monkeypatch.setattr(updater, "MAC", mac)
        release = updater.Release(release_data(WIN, MAC))
        assert release.url == asset["browser_download_url"]
        assert release.size == asset["size"]
        assert release.sha256 == asset["digest"][7:]
        assert release.is_newer()


def test_mac_paths(monkeypatch):
    monkeypatch.setattr(updater, "MAC", True)
    exe = "/Applications/TimeTracker.app/Contents/MacOS/TimeTracker"
    assert updater.bundle_path(exe) == "/Applications/TimeTracker.app"
    assert updater._paths(exe) == ("/Applications/TimeTracker.app", "/Applications/TimeTracker.new.app",
                                   "/Applications/TimeTracker.update.dmg", "/Applications/TimeTracker.old.app")


def test_windows_paths(monkeypatch):
    monkeypatch.setattr(updater, "MAC", False)
    exe = os.path.join("C:\\", "TT", "TimeTracker.exe")
    base = os.path.join("C:\\", "TT", "TimeTracker")
    assert updater._paths(exe) == (exe, base + ".new.exe", base + ".update.zip", exe + ".tmp")
