"""Custom painting for compact rows: day headers with a timeline strip, and task entries."""
from datetime import datetime, time as dtime

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from . import theme
from .db import fmt_duration

DATA = Qt.UserRole
DAY_HEIGHT = 46     # includes the gap above the card
ENTRY_HEIGHT = 30
DAY_GAP = 6


class Box:
    """Holds a Python payload in item data untouched (Qt would convert dicts/dates)."""
    __slots__ = ("v",)

    def __init__(self, value):
        self.v = value


def payload(index):
    box = index.data(DATA)
    return box.v if isinstance(box, Box) else None


def _font(base, bold=False, size=None, family=None):
    font = QFont(base)
    if family:
        font.setFamily(family)
    if size:
        font.setPointSizeF(size)
    font.setBold(bold)
    return font


def paint_entry(p, rect, base_font, color, title, subtitle, right_text, hover=False, active=False, selected=False,
                tokens_text=None, muted=False):
    """One task row: color bar, "Product • subtask", [tokens], time on the right."""
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#363636" if selected else theme.ROW_HOVER if hover else theme.ROW))
    p.drawRoundedRect(QRectF(rect), 4, 4)
    p.setBrush(QColor(color))
    p.drawRoundedRect(QRectF(rect.left(), rect.top() + 4, 3, rect.height() - 8), 1.5, 1.5)

    right_font = _font(base_font, bold=active)
    right_w = QFontMetrics(right_font).horizontalAdvance(right_text) + 12
    p.setFont(right_font)
    p.setPen(QColor(theme.ACTIVE if active else theme.TEXT_3 if muted else theme.TEXT_2))
    p.drawText(rect.adjusted(0, 0, -12, 0), Qt.AlignVCenter | Qt.AlignRight, right_text)
    if tokens_text:
        tok_font = _font(base_font, size=9)
        tok_w = QFontMetrics(tok_font).horizontalAdvance(tokens_text)
        tok_right = rect.right() - right_w - 10
        p.setFont(tok_font)
        p.setPen(QColor(theme.TEXT_3))
        p.drawText(QRect(tok_right - tok_w, rect.top(), tok_w, rect.height()), Qt.AlignVCenter | Qt.AlignRight,
                   tokens_text)
        p.setFont(_font(base_font, size=8, family=theme.ICON_FONT))
        p.drawText(QRect(tok_right - tok_w - 16, rect.top(), 14, rect.height()), Qt.AlignCenter, theme.G_TOKENS)
        right_w += tok_w + 26

    x = rect.left() + 14
    avail = rect.right() - right_w - x - 8
    if active:
        p.setFont(_font(base_font, size=8, family=theme.ICON_FONT))
        p.setPen(QColor(theme.ACTIVE))
        p.drawText(QRect(x, rect.top(), 14, rect.height()), Qt.AlignVCenter | Qt.AlignLeft, theme.G_PLAY)
        x += 16
        avail -= 16
    title_font = _font(base_font, bold=True)
    fm = QFontMetrics(title_font)
    title_text = fm.elidedText(title, Qt.ElideRight, max(0, avail))
    p.setFont(title_font)
    p.setPen(QColor(theme.TEXT_2 if muted else theme.TEXT))
    p.drawText(QRect(x, rect.top(), avail, rect.height()), Qt.AlignVCenter | Qt.AlignLeft, title_text)
    x += fm.horizontalAdvance(title_text)
    avail -= fm.horizontalAdvance(title_text)
    if subtitle and avail > 30:
        sub_font = _font(base_font)
        sub = QFontMetrics(sub_font).elidedText(f"  •  {subtitle}", Qt.ElideRight, avail)
        p.setFont(sub_font)
        p.setPen(QColor(theme.TEXT_3 if muted else theme.TEXT_2))
        p.drawText(QRect(x, rect.top(), avail, rect.height()), Qt.AlignVCenter | Qt.AlignLeft, sub)


class JournalDelegate(QStyledItemDelegate):
    """Paints the journal tree: top-level items are days, children are entries."""

    def __init__(self, tree):
        super().__init__(tree)
        self.tree = tree
        self.workday = (dtime(9, 0), dtime(18, 0))  # set by the journal page from settings

    def sizeHint(self, option, index):
        data = payload(index) or {}
        return QSize(100, DAY_HEIGHT if data.get("kind") == "day" else ENTRY_HEIGHT)

    def paint(self, p, option, index):
        data = payload(index)
        if not data:
            return
        p.save()
        p.setRenderHint(p.RenderHint.Antialiasing)
        hover = bool(option.state & QStyle.State_MouseOver)
        if data["kind"] == "day":
            self._paint_day(p, option.rect, option.font, data, hover, self.tree.isExpanded(index))
        else:
            entry = data["entry"]
            right = theme.fmt_human(entry["seconds"])
            paint_entry(p, option.rect.adjusted(0, 1, 0, -1), option.font, theme.product_color(entry["product_id"]),
                        entry["product"], entry["subtask"], right, hover, entry["status"] == "active")
        p.restore()

    def _paint_day(self, p, rect, base_font, data, hover, expanded):
        day = data["day"]
        card = rect.adjusted(0, DAY_GAP, 0, -1)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.CARD_HOVER if hover else theme.CARD))
        p.drawRoundedRect(QRectF(card), 5, 5)

        text_rect = card.adjusted(0, 0, 0, -3)
        p.setFont(_font(base_font, size=9, family=theme.ICON_FONT))
        p.setPen(QColor(theme.TEXT_2))
        p.drawText(QRect(card.left() + 12, text_rect.top(), 16, text_rect.height()), Qt.AlignCenter,
                   theme.G_DOWN if expanded else theme.G_RIGHT)
        p.setFont(_font(base_font, bold=True, size=10.5))
        p.setPen(QColor(theme.TEXT))
        p.drawText(text_rect.adjusted(40, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, theme.fmt_day(day["date"]))
        p.drawText(text_rect.adjusted(0, 0, -12, 0), Qt.AlignVCenter | Qt.AlignRight, theme.fmt_human(day["total"]))

        # Timeline strip: where in the 24 h day the work happened, colored by product.
        strip = QRectF(card.left() + 2, card.bottom() - 2, card.width() - 4, 3)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.TRACK))
        p.drawRect(strip)
        midnight = datetime.combine(day["date"], dtime())

        def x_at(moment):
            return strip.left() + strip.width() * (moment - midnight).total_seconds() / 86400

        # Working hours: lighter band on the track + small ticks at its start and end.
        start, end = (x_at(datetime.combine(day["date"], t)) for t in self.workday)
        if end > start:
            p.setBrush(QColor(theme.TRACK_WORK))
            p.drawRect(QRectF(start, strip.top(), end - start, strip.height()))
        p.setBrush(QColor(theme.TEXT_2))
        for x in (start, end):
            p.drawRect(QRectF(x - 0.75, strip.top() - 8, 1.5, strip.height() + 8))
        for entry in day["entries"]:
            p.setBrush(QColor(theme.product_color(entry["product_id"])))
            for s, e in entry["intervals"]:
                x1, x2 = x_at(s), x_at(e)
                p.drawRect(QRectF(x1, strip.top(), max(2.0, x2 - x1), strip.height()))


class EntryDelegate(QStyledItemDelegate):
    """Rows of the timer window's open-session list."""

    def sizeHint(self, option, index):
        return QSize(100, ENTRY_HEIGHT)

    def paint(self, p, option, index):
        s = payload(index)
        if not s:
            return
        p.save()
        p.setRenderHint(p.RenderHint.Antialiasing)
        finished = s["status"] == "stopped"
        paint_entry(p, option.rect.adjusted(0, 1, 0, -1), option.font, theme.product_color(s["product_id"]),
                    s["product"], s["subtask"], "✓ завершено" if finished else fmt_duration(s["total"]),
                    hover=bool(option.state & QStyle.State_MouseOver), active=s["status"] == "active",
                    selected=bool(option.state & QStyle.State_Selected),
                    tokens_text=theme.fmt_tokens(s["tokens"]) if s.get("tokens") else None, muted=finished)
        p.restore()
