#!/bin/sh
# Builds TimeTracker.app and release/vX.Y.Z/TimeTracker-X.Y.Z-mac.dmg. macOS only (Apple Silicon).
# Runs on GitHub Actions (.github/workflows/build-mac.yml); by hand on a Mac: sh build_mac.sh
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
$PY -m pip install --upgrade -r requirements.txt pyinstaller pillow
VERSION=$($PY -c "from timetracker import __version__; print(__version__)")

# Icon.png (1024x1024 with Apple-style margins) -> .icns by PyInstaller (needs pillow).
# onedir .app: a onefile .app is deprecated by PyInstaller and slow to start.
$PY -m PyInstaller --noconfirm --clean --windowed --name TimeTracker \
    --icon Icon.png --osx-bundle-identifier com.rudifreeman.timetracker \
    --add-data "timetracker/icon.png:timetracker" --add-data "timetracker/icons.ttf:timetracker" \
    --add-data "CHANGELOG.md:." \
    --exclude-module tkinter \
    --exclude-module PySide6.QtNetwork --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick \
    --exclude-module PySide6.QtPdf --exclude-module PySide6.QtOpenGL \
    main.py

APP=dist/TimeTracker.app
PLIST="$APP/Contents/Info.plist"
plutil -replace CFBundleShortVersionString -string "$VERSION" "$PLIST"
plutil -replace CFBundleVersion -string "$VERSION" "$PLIST"
plutil -replace CFBundleDisplayName -string "Time Tracker" "$PLIST"
plutil -replace NSHighResolutionCapable -bool true "$PLIST"
# The plist changed after PyInstaller signed the bundle: sign again (ad-hoc, no Apple account).
# Apple Silicon refuses to run unsigned code.
codesign --force --deep --sign - "$APP"

# DMG: the app, a link to Applications (drag to install) and the instructions.
OUT="release/v$VERSION"
DMG="$OUT/TimeTracker-$VERSION-mac.dmg"
STAGE=$(mktemp -d)
ditto "$APP" "$STAGE/TimeTracker.app"
ln -s /Applications "$STAGE/Applications"
cp release/README-mac.txt "$STAGE/README.txt"
mkdir -p "$OUT"
rm -f "$DMG"
hdiutil create -volname "Time Tracker" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
rm -rf "$STAGE"
echo "Done: $DMG"
