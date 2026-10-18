"""Снимки всех окон программы на тестовых данных: python -X utf8 tests/screenshots.py <папка>.

Не тест pytest (имя без test_): запускается вручную или в сборке для Mac на GitHub, чтобы посмотреть,
как программа выглядит на системе, которой нет под рукой. Рабочая база не трогается — данные во
временной папке. Окна показываются по-настоящему (не offscreen), иначе шрифты системы не те.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

from timetracker import theme, updater  # noqa: E402
from timetracker.db import Database  # noqa: E402
from timetracker.main_window import MainWindow  # noqa: E402
from timetracker.timer_window import Hub, TimerWindow  # noqa: E402


def sample(db):
    """Две задачи за сегодня и вчера, одна идёт сейчас; токены."""
    now = datetime.now().replace(microsecond=0)
    today = now.replace(hour=9, minute=0, second=0)
    if now - today < timedelta(hours=3):  # рано утром — данные «вчера и позавчера»
        today -= timedelta(days=1)
    dac = db.get_or_create_product("DAC 520SV")
    titan = db.get_or_create_product("TitanFlex")
    shoot, edit = db.create_subtask("Съёмка"), db.create_subtask("Монтаж")
    for days in (1, 0):
        day = today - timedelta(days=days)
        db.add_manual(dac, shoot, day, day + timedelta(hours=1, minutes=20))
        db.add_manual(titan, edit, day + timedelta(hours=1, minutes=30), day + timedelta(hours=2, minutes=45))
    db.add_tokens(titan, "ElevenLabs", 12500)
    return dac, edit


def grab(widget, folder, name):
    widget.show()
    widget.raise_()
    for _ in range(20):
        QApplication.processEvents()
    widget.grab().save(os.path.join(folder, f"{name}.png"))
    print("saved", name)


def main():
    folder = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "screenshots")
    os.makedirs(folder, exist_ok=True)
    app = QApplication(sys.argv)
    theme.load_fonts()
    app.setStyle("Fusion")
    app.setPalette(theme.palette())
    app.setStyleSheet(theme.stylesheet())
    db = Database(os.path.join(tempfile.mkdtemp(), "screens.db"))
    running = sample(db)
    hub = Hub()
    timer = TimerWindow(db, hub)
    db.start(*running)  # after the window: its start-up recovery would pause it
    timer.updater = updater.Updater()
    timer.main_window = MainWindow(db, hub, timer)
    hub.changed.emit()
    grab(timer, folder, "1-timer")
    timer.mini.show_mini()  # as on minimizing the timer window
    grab(timer.mini, folder, "2-mini")
    timer.mini.hide()
    for index, name in enumerate(("journal", "summary", "settings", "about")):
        timer.main_window.show_page(index)
        grab(timer.main_window, folder, f"{index + 3}-{name}")
    timer._ticker.stop()
    db.close()


if __name__ == "__main__":
    main()
