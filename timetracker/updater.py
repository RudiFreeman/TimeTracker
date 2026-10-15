"""Self-update from GitHub Releases. Without UI except the Qt signals of `Updater`.

Check: GET releases/latest → tag vX.Y.Z newer than __version__ → asset TimeTracker-X.Y.Z.zip.
Install, three processes, none of them touches its own running file:
  1. The old app: `prepare` downloads the zip next to the exe, verifies size + sha256 (GitHub
     `digest`) and extracts TimeTracker.new.exe. The app then quits the normal way and main.py
     calls `launch_replacer`: start `TimeTracker.new.exe --replace <path to TimeTracker.exe>`.
  2. The replacer (main.py → `replace`, before any UI): waits for the single-instance mutex (= the
     old app has exited), copies itself over TimeTracker.exe (via .tmp + os.replace, with retries —
     antivirus holds fresh exe files) and starts `TimeTracker.exe --updated`, or on failure the
     old exe with `--update-failed` so the user is told.
  3. The new app: waits for the mutex too, `cleanup` removes .new.exe / .tmp / .update.zip.
Why: a onefile exe reads its own Python modules from sys.executable while running, so renaming
or replacing the file under a running app breaks later imports (seen in tests 15.10.2026).
The database next to the exe is never touched.
Works only for the frozen exe; from source the check works, «Обновить» opens the release page.
"""
import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from PySide6.QtCore import QObject, Signal

from . import __version__
from .db import app_dir

REPO = "RudiFreeman/TimeTracker"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
TIMEOUT = 15
CHUNK = 256 * 1024
# Downloads only over https from GitHub (the asset URL redirects to its file storage).
TRUSTED_HOSTS = ("github.com", "githubusercontent.com")
UPDATED_FLAG = "--updated"        # the new app after a successful update
FAILED_FLAG = "--update-failed"   # the old app started again: tell the user
REPLACE_FLAG = "--replace"        # TimeTracker.new.exe --replace <target exe>

_can_install = None


def parse_version(text):
    """'v2.1.10' → (2, 1, 10); None if the tag is not a version."""
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", (text or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def can_install():
    """Self-install needs the built exe in a folder we may write to (not Program Files).
    os.access lies about folders on Windows, so try to create a file. Computed once."""
    global _can_install
    if _can_install is None:
        _can_install = False
        if getattr(sys, "frozen", False):
            probe = os.path.join(app_dir(), ".update-probe")
            try:
                with open(probe, "w"):
                    pass
                os.remove(probe)
                _can_install = True
            except OSError:
                pass
    return _can_install


def _trusted(url):
    parts = urllib.parse.urlsplit(url or "")
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(host == h or host.endswith("." + h) for h in TRUSTED_HOSTS)


def _open(url):
    request = urllib.request.Request(url, headers={
        "User-Agent": f"TimeTracker/{__version__}", "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(request, timeout=TIMEOUT, context=ssl.create_default_context())


def describe_error(exc):
    """Short Russian reason for the UI."""
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in (403, 429):
            return "GitHub временно ограничил проверки, попробуйте позже"
        if exc.code == 404:
            return "на GitHub пока нет опубликованной версии"
        return f"GitHub ответил ошибкой {exc.code}"
    if isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError)):
        return "нет связи с GitHub"
    if isinstance(exc, ValueError):  # bad JSON
        return "GitHub прислал непонятный ответ"
    return str(exc) or exc.__class__.__name__


def release_notes(body):
    """«Что нового» from the release description (it also has download/install sections)."""
    body = (body or "").replace("\r\n", "\n")
    m = re.search(r"^#+\s*Что нового\s*$", body, re.M)
    return (body[m.end():] if m else body).strip()


class Release:
    def __init__(self, data):
        self.version = parse_version(data.get("tag_name"))
        self.tag = data.get("tag_name", "")
        self.page = data.get("html_url") or RELEASES_PAGE
        self.notes = release_notes(data.get("body"))
        zips = [a for a in data.get("assets", []) if a.get("name", "").lower().endswith(".zip")]
        asset = zips[0] if zips else {}
        self.url = asset.get("browser_download_url")
        self.size = asset.get("size")
        digest = asset.get("digest") or ""
        self.sha256 = digest[7:].lower() if digest.startswith("sha256:") else None

    @property
    def label(self):
        return ".".join(map(str, self.version)) if self.version else self.tag

    def is_newer(self):
        return bool(self.version and self.url) and self.version > parse_version(__version__)


def fetch_latest():
    with _open(API_LATEST) as response:
        return Release(json.load(response))


def _paths(exe=None):
    """exe, its .new.exe, the downloaded zip, the temp copy used by the replacer."""
    exe = exe or sys.executable
    base = os.path.splitext(exe)[0]
    return exe, base + ".new.exe", base + ".update.zip", exe + ".tmp"


def cleanup(downloads=True):
    """Remove leftovers of an update. The replacer may still be closing — then the later retry.
    downloads=False: the app is running, .new.exe / .update.zip may be a download in progress."""
    if not getattr(sys, "frozen", False):
        return
    exe, new, archive, tmp = _paths()
    paths = [tmp]
    if downloads:
        paths += [new, archive]
    for path in paths:
        try:
            os.remove(path)
        except OSError:
            pass


def prepare(release, progress=None):
    """Download and unpack the new exe next to the current one. progress(done, total).
    Returns the .new.exe path for `launch_replacer`. Raises on failure; the program is unchanged."""
    _exe, new, archive, _tmp = _paths()
    try:
        digest = hashlib.sha256()
        done = 0
        if not _trusted(release.url):
            raise OSError("ссылка на архив ведёт не на GitHub")
        if not release.sha256:
            raise OSError("GitHub не сообщил контрольную сумму архива")
        with _open(release.url) as response, open(archive, "wb") as out:
            if not _trusted(response.geturl()):  # after redirects
                raise OSError("архив отдаётся не с GitHub")
            total = release.size or int(response.headers.get("Content-Length") or 0)
            while chunk := response.read(CHUNK):
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        if release.size and done != release.size:
            raise OSError("архив скачался не полностью")
        if digest.hexdigest() != release.sha256:
            raise OSError("архив повреждён (не совпала контрольная сумма)")
        with zipfile.ZipFile(archive) as z:
            names = [n for n in z.namelist() if n.lower().rsplit("/", 1)[-1] == "timetracker.exe"]
            if not names:
                raise OSError("в архиве нет TimeTracker.exe")
            with z.open(names[0]) as src, open(new, "wb") as dst:
                shutil.copyfileobj(src, dst)
    finally:
        try:
            os.remove(archive)
        except OSError:
            pass
    return new


def start(exe, *args):
    """Start exe as a separate, fully independent process."""
    env = dict(os.environ)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"  # don't reuse our onefile temp folder
    for key in [k for k in env if k.startswith("_PYI") or k.startswith("_MEI")]:
        del env[key]
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    subprocess.Popen([exe, *args], cwd=os.path.dirname(exe), env=env, close_fds=True, creationflags=flags)


def launch_replacer(new):
    """Step 1 → 2: called by main.py after the app has quit and the database is closed."""
    start(new, REPLACE_FLAG, sys.executable)


def replace(target, seconds=20):
    """Step 2, in the replacer process (the mutex is already ours): copy this exe over `target`.
    Returns True on success. Retries — the old exe may still be closing or scanned by antivirus."""
    tmp = target + ".tmp"
    deadline = time.monotonic() + seconds
    while True:
        try:
            shutil.copyfile(sys.executable, tmp)
            os.replace(tmp, target)
            return True
        except OSError:
            if time.monotonic() > deadline:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                return False
            time.sleep(0.5)


class Updater(QObject):
    """Background check/download; signals arrive in the GUI thread (queued across threads)."""
    checked = Signal(object, str)    # Release or None, error text ('' if fine)
    progress = Signal(int, int)      # bytes done, total
    prepared = Signal(str, str)      # new exe path ('' on failure), error text

    def __init__(self):
        super().__init__()
        self.latest = None        # Release from the last successful check
        self.checking = False
        self.downloading = False
        self.backed_up = False    # one forced database copy per run is enough

    @property
    def busy(self):
        return self.checking or self.downloading

    def check(self):
        if self.busy:
            return
        self.checking = True
        threading.Thread(target=self._check, daemon=True).start()

    def _check(self):
        try:
            release, error = fetch_latest(), ""
        except Exception as exc:  # no network, GitHub down, bad JSON — never fatal
            release, error = None, describe_error(exc)
        self.checking = False
        if release:
            self.latest = release
        self.checked.emit(release, error)

    def update_available(self):
        return self.latest if self.latest and self.latest.is_newer() else None

    def install(self, release):
        """Download in the background; a check running at the same time doesn't block it."""
        if self.downloading:
            return
        self.downloading = True
        threading.Thread(target=self._prepare, args=(release,), daemon=True).start()

    def _prepare(self, release):
        try:
            new, error = prepare(release, self.progress.emit), ""
        except Exception as exc:
            new, error = "", describe_error(exc)
        self.downloading = False
        self.prepared.emit(new, error)
