@echo off
rem Builds a single portable dist\TimeTracker.exe
cd /d "%~dp0"
python -m pip install --upgrade -r requirements.txt || exit /b 1
python -m PyInstaller --noconfirm --clean --onefile --windowed --name TimeTracker ^
    --icon timetracker\icon.ico --add-data "timetracker\icon.png;timetracker" --add-data "CHANGELOG.md;." ^
    --exclude-module tkinter ^
    --exclude-module PySide6.QtNetwork --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick ^
    --exclude-module PySide6.QtPdf --exclude-module PySide6.QtOpenGL ^
    main.py || exit /b 1
rem Separate icon file for the desktop shortcut (Windows caches the exe's icon)
copy /y timetracker\icon.ico dist\TimeTracker.ico >nul
echo.
echo Done: %~dp0dist\TimeTracker.exe
rem Lay out release/vX.Y.Z (TimeTracker folder + zips), see release.py
python -X utf8 release.py || exit /b 1
