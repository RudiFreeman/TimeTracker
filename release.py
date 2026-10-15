"""Раскладывает собранный dist/TimeTracker.exe по версии: release/vX.Y.Z/.

Внутри: папка TimeTracker (exe + README.txt + UPDATE.txt) и архив
TimeTracker-X.Y.Z.zip с тем же содержимым — один на новую установку и на обновление.
Инструкции берутся из шаблонов release/README.txt и release/UPDATE.txt. Базу не кладём.
Запускается из build.bat после сборки.
"""
import os
import shutil
import sys
import zipfile

from timetracker import __version__

ROOT = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(ROOT, "dist", "TimeTracker.exe")
RELEASE = os.path.join(ROOT, "release")
DOCS = ("README.txt", "UPDATE.txt")  # шаблоны из release/, копируются под теми же именами


def write_zip(path, files):
    """files: [(путь на диске, имя внутри архива)]."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for src, name in files:
            z.write(src, name)


def main():
    if not os.path.exists(EXE):
        sys.exit(f"Нет {EXE} — сначала сборка.")
    out = os.path.join(RELEASE, f"v{__version__}")
    if os.path.exists(out):
        print(f"Внимание: {out} уже есть — перезаписываю. Если эта версия уже ушла коллегам, "
              f"поднимите __version__ в timetracker/__init__.py.")
        shutil.rmtree(out)
    app = os.path.join(out, "TimeTracker")
    os.makedirs(app)
    shutil.copy2(EXE, app)
    for name in DOCS:
        shutil.copy2(os.path.join(RELEASE, name), app)

    write_zip(os.path.join(out, f"TimeTracker-{__version__}.zip"),
              [(os.path.join(app, f), f"TimeTracker/{f}") for f in os.listdir(app)])
    print(f"Готово: {out}")


if __name__ == "__main__":
    main()
