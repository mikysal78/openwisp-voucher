"""Disegno dei biglietti con QPainter: anteprima, stampa e PDF usano lo stesso codice.

Le misure sono in millimetri e diventano pixel con k = punti per millimetro del
dispositivo; i caratteri sono in punti tipografici, che Qt converte con i DPI
del dispositivo. Per questo le anteprime sono QImage con i DPI impostati.
"""

from __future__ import annotations

from dataclasses import dataclass

import segno
from PySide6.QtCore import QMarginsF, QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QPen,
)

from .i18n import tr
from .store import (
    FORMAT_58,
    FORMAT_80,
    FORMAT_A4,
    FORMAT_LABEL,
    QR_NONE,
    QR_URL,
    QR_WIFI,
    Settings,
)
from .voucher import Voucher, wifi_qr_payload

MONO = "DejaVu Sans Mono, Consolas, Courier New, monospace"

# A4: 2 colonne x 5 righe di biglietti da ritagliare
A4_MARGIN = 10.0
A4_COLS = 2
A4_ROWS = 5
THERMAL_SIDE = 4.0  # margine laterale degli scontrini (zona non stampabile)
LABEL_MARGIN = 2.0


@dataclass
class Page:
    width_mm: float
    height_mm: float
    per_page: int


def qr_payload(settings: Settings) -> str | None:
    if settings.qr == QR_WIFI and settings.ssid:
        return wifi_qr_payload(settings.ssid, settings.wifi_password)
    if settings.qr == QR_URL and settings.qr_url:
        return settings.qr_url
    return None


def _font(size_pt: float, bold=False, mono=False) -> QFont:
    font = QFont()
    if mono:
        font.setFamilies([f.strip() for f in MONO.split(",")])
        font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSizeF(max(size_pt, 3.0))
    font.setBold(bold)
    return font


class _Card:
    """Disposizione di un biglietto dentro un rettangolo (pixel del dispositivo).

    draw() con painter=None misura soltanto e restituisce l'altezza usata.
    """

    def __init__(self, settings: Settings, voucher: Voucher, k: float, logo: QImage | None):
        self.s = settings
        self.v = voucher
        self.k = k
        self.logo = logo
        self.qr = None
        payload = qr_payload(settings)
        if payload:
            self.qr = segno.make(payload, error="m", micro=False)

    def mm(self, value: float) -> float:
        return value * self.k

    # -- primitive: con painter None calcolano solo l'ingombro --

    def _text(self, p, x, y, w, text, font, align=Qt.AlignmentFlag.AlignHCenter, color=None):
        if not text:
            return 0.0
        flags = int(align) | int(Qt.TextFlag.TextWordWrap)
        if p is None:
            # QFontMetricsF senza dispositivo userebbe i DPI dello schermo
            return self._measure(text, font, w, flags)
        p.setFont(font)
        p.setPen(color or QColor("#111111"))
        rect = p.boundingRect(QRectF(x, y, w, 10_000), flags, text)
        p.drawText(QRectF(x, y, w, rect.height()), flags, text)
        return rect.height()

    def _measure(self, text, font, w, flags):
        image = QImage(1, 1, QImage.Format.Format_ARGB32)
        dpm = round(self.k * 1000)
        image.setDotsPerMeterX(dpm)
        image.setDotsPerMeterY(dpm)
        painter = QPainter(image)
        painter.setFont(font)
        rect = painter.boundingRect(QRectF(0, 0, w, 10_000), flags, text)
        painter.end()
        return rect.height()

    def _logo(self, p, x, y, w, max_h):
        if self.logo is None or self.logo.isNull():
            return 0.0
        ratio = self.logo.width() / self.logo.height()
        h = min(max_h, w / ratio)
        lw = h * ratio
        if p is not None:
            target = QRectF(x + (w - lw) / 2, y, lw, h)
            p.drawImage(target, self.logo)
        return h

    def _qr(self, p, x, y, size):
        if self.qr is None:
            return 0.0
        matrix = list(self.qr.matrix)
        border = 2
        n = len(matrix) + 2 * border
        cell = size / n
        if p is not None:
            p.save()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("white"))
            p.drawRect(QRectF(x, y, size, size))
            p.setBrush(QColor("black"))
            for r, row in enumerate(matrix):
                for c, dark in enumerate(row):
                    if dark:
                        # celle appena più grandi: niente righe bianche fra le celle
                        p.drawRect(
                            QRectF(
                                x + (c + border) * cell,
                                y + (r + border) * cell,
                                cell + 0.5,
                                cell + 0.5,
                            )
                        )
            p.restore()
        return size

    def _line(self, p, x, y, w):
        if p is not None:
            pen = QPen(QColor("#999999"))
            pen.setWidthF(max(1.0, self.mm(0.2)))
            p.setPen(pen)
            p.drawLine(QPointF(x, y), QPointF(x + w, y))

    def _contacts(self):
        items = [self.s.website, self.s.email, self.s.phone]
        # spazi non divisibili: un numero di telefono non va a capo a metà
        return [i.strip().replace(" ", "\u00a0") for i in items if i and i.strip()]

    def _expiry_text(self):
        return tr("Valido fino al {date} compreso").format(
            date=self.v.expiration.strftime("%d/%m/%Y")
        )

    # -- disposizioni --

    def vertical(self, p, x, y, w, scale=1.0):
        """Scontrini ed etichette alte: tutto in colonna."""
        z = scale
        top = y
        gap = self.mm(1.6 * z)
        y += self._logo(p, x, y, w, self.mm(20 * z))
        if self.logo is not None:
            y += gap
        y += self._text(p, x, y, w, self.s.venue_name, _font(11 * z, bold=True))
        if self.s.ssid:
            y += self._text(p, x, y, w, tr("Rete Wi-Fi: {ssid}").format(ssid=self.s.ssid), _font(8.5 * z))
        y += gap
        self._line(p, x, y, w)
        y += gap
        y += self._text(p, x, y, w, tr("Utente"), _font(7 * z), color=QColor("#555555"))
        y += self._text(p, x, y, w, self.v.username, _font(13 * z, bold=True, mono=True))
        y += gap / 2
        y += self._text(p, x, y, w, tr("Password"), _font(7 * z), color=QColor("#555555"))
        y += self._text(p, x, y, w, self.v.password, _font(13 * z, bold=True, mono=True))
        y += gap
        y += self._text(p, x, y, w, self._expiry_text(), _font(8.5 * z, bold=True))
        if self.v.notes:
            y += self._text(p, x, y, w, self.v.notes, _font(7.5 * z))
        if self.qr is not None:
            y += gap
            size = min(w * 0.6, self.mm(32 * z))
            y += self._qr(p, x + (w - size) / 2, y, size)
            caption = tr("Inquadra per collegarti") if self.s.qr == QR_WIFI else ""
            y += self._text(p, x, y, w, caption, _font(6.5 * z), color=QColor("#555555"))
        contacts = self._contacts()
        if contacts or self.s.footer_note:
            y += gap
            self._line(p, x, y, w)
            y += gap
            y += self._text(p, x, y, w, "\n".join(contacts), _font(7.5 * z))
            y += self._text(p, x, y, w, self.s.footer_note, _font(7 * z), color=QColor("#555555"))
        return y - top

    def horizontal(self, p, x, y, w, h, scale=1.0):
        """Biglietti larghi (A4, etichette orizzontali): QR a destra."""
        z = scale
        top = y
        gap = self.mm(1.2 * z)
        left = Qt.AlignmentFlag.AlignLeft
        qr_size = 0.0
        if self.qr is not None:
            qr_size = min(h * 0.62, w * 0.36, self.mm(30 * z))
        col_w = w - (qr_size + self.mm(3) if qr_size else 0)
        logo_h = self._logo_left(p, x, y, col_w, self.mm(12 * z))
        if logo_h:
            y += logo_h + gap
        y += self._text(p, x, y, col_w, self.s.venue_name, _font(10 * z, bold=True), left)
        if self.s.ssid:
            y += self._text(p, x, y, col_w, tr("Rete Wi-Fi: {ssid}").format(ssid=self.s.ssid), _font(8 * z), left)
        y += gap
        label_w = self.mm(17 * z)
        for label, value in ((tr("Utente"), self.v.username), (tr("Password"), self.v.password)):
            self._text(p, x, y + self.mm(0.8 * z), label_w, label, _font(7 * z), left, QColor("#555555"))
            y += self._text(p, x + label_w, y, col_w - label_w, value, _font(12 * z, bold=True, mono=True), left)
        y += gap / 2
        y += self._text(p, x, y, col_w, self._expiry_text(), _font(8 * z, bold=True), left)
        if self.v.notes:
            y += self._text(p, x, y, col_w, self.v.notes, _font(7 * z), left)
        if qr_size:
            qy = top
            self._qr(p, x + w - qr_size, qy, qr_size)
            if self.s.qr == QR_WIFI:
                self._text(p, x + w - qr_size - self.mm(2), qy + qr_size, qr_size + self.mm(4),
                           tr("Inquadra per collegarti"), _font(6 * z), color=QColor("#555555"))
            y = max(y, qy + qr_size + self.mm(3 * z))
        contacts = "  ·  ".join(self._contacts())
        if contacts or self.s.footer_note:
            y += gap
            self._line(p, x, y, w)
            y += gap
            y += self._text(p, x, y, w, contacts, _font(7 * z))
            y += self._text(p, x, y, w, self.s.footer_note, _font(6.5 * z), color=QColor("#555555"))
        return y - top

    def _logo_left(self, p, x, y, w, max_h):
        if self.logo is None or self.logo.isNull():
            return 0.0
        ratio = self.logo.width() / self.logo.height()
        h = min(max_h, w / ratio)
        if p is not None:
            p.drawImage(QRectF(x, y, h * ratio, h), self.logo)
        return h

    def fit(self, p, rect: QRectF, horizontal: bool):
        """Disegna nel rettangolo riducendo tutto se il contenuto non ci sta."""

        def layout(painter, scale):
            if horizontal:
                return self.horizontal(painter, rect.x(), rect.y(), rect.width(), rect.height(), scale)
            return self.vertical(painter, rect.x(), rect.y(), rect.width(), scale)

        scale = 1.0
        for _ in range(6):
            needed = layout(None, scale)
            if needed <= rect.height():
                break
            scale *= max(0.5, rect.height() / needed) * 0.98
        layout(p, scale)


def load_logo(settings: Settings) -> QImage | None:
    path = settings.logo_path
    if path is None:
        return None
    image = QImage(str(path))
    return None if image.isNull() else image


def page_for(settings: Settings) -> Page:
    if settings.print_format == FORMAT_A4:
        return Page(210.0, 297.0, A4_COLS * A4_ROWS)
    if settings.print_format in (FORMAT_58, FORMAT_80):
        width = 58.0 if settings.print_format == FORMAT_58 else 80.0
        return Page(width, 0.0, 1)  # altezza calcolata dal contenuto
    return Page(settings.label_width_mm, settings.label_height_mm, 1)


def thermal_height_mm(settings: Settings, vouchers: list[Voucher], dpi: float = 300) -> float:
    k = dpi / 25.4
    width = page_for(settings).width_mm - 2 * THERMAL_SIDE
    logo = load_logo(settings)
    tallest = max(_Card(settings, v, k, logo).vertical(None, 0, 0, width * k) for v in vouchers)
    return tallest / k + 2 * THERMAL_SIDE + 6  # un po' di carta prima del taglio


def card_rects(settings: Settings, page_w_mm: float, page_h_mm: float, k: float):
    """Rettangoli (pixel) dei biglietti di una pagina, con orientamento."""
    fmt = settings.print_format
    if fmt == FORMAT_A4:
        cw = (page_w_mm - 2 * A4_MARGIN) / A4_COLS
        ch = (page_h_mm - 2 * A4_MARGIN) / A4_ROWS
        pad = 4.0
        rects = []
        for row in range(A4_ROWS):
            for col in range(A4_COLS):
                outer = QRectF(
                    (A4_MARGIN + col * cw) * k, (A4_MARGIN + row * ch) * k, cw * k, ch * k
                )
                rects.append((outer, outer.adjusted(pad * k, pad * k, -pad * k, -pad * k), True))
        return rects
    if fmt in (FORMAT_58, FORMAT_80):
        m = THERMAL_SIDE * k
        outer = QRectF(0, 0, page_w_mm * k, page_h_mm * k)
        return [(outer, outer.adjusted(m, m, -m, -m), False)]
    m = LABEL_MARGIN * k
    outer = QRectF(0, 0, page_w_mm * k, page_h_mm * k)
    return [(outer, outer.adjusted(m, m, -m, -m), page_w_mm >= page_h_mm * 1.3)]


def paint_pages(painter: QPainter, new_page, settings: Settings, vouchers: list[Voucher],
                page_w_mm: float, page_h_mm: float, k: float) -> None:
    """Disegna tutti i biglietti; new_page() passa alla pagina successiva."""
    logo = load_logo(settings)
    rects = card_rects(settings, page_w_mm, page_h_mm, k)
    per_page = len(rects)
    for i, voucher in enumerate(vouchers):
        slot = i % per_page
        if i and slot == 0:
            new_page()
        outer, inner, horizontal = rects[slot]
        if settings.print_format == FORMAT_A4:
            # bordo tratteggiato per ritagliare
            pen = QPen(QColor("#bbbbbb"))
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setWidthF(max(1.0, 0.2 * k))
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(outer)
        _Card(settings, voucher, k, logo).fit(painter, inner, horizontal)


def page_size_mm(settings: Settings, vouchers: list[Voucher]) -> tuple[float, float]:
    page = page_for(settings)
    height = page.height_mm or thermal_height_mm(settings, vouchers)
    return page.width_mm, height


def apply_page(device, width_mm: float, height_mm: float) -> None:
    """Pagina su misura senza margini (QPrinter o QPdfWriter)."""
    size = QPageSize(QSizeF(width_mm, height_mm), QPageSize.Unit.Millimeter, "voucher")
    orientation = QPageLayout.Orientation.Portrait
    layout = QPageLayout(size, orientation, QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)
    layout.setMode(QPageLayout.Mode.FullPageMode)
    device.setPageLayout(layout)


def export_pdf(path: str, settings: Settings, vouchers: list[Voucher], dpi: int = 300) -> None:
    width, height = page_size_mm(settings, vouchers)
    writer = QPdfWriter(path)
    writer.setResolution(dpi)
    writer.setTitle(tr("Accessi Wi-Fi"))
    writer.setCreator("openwisp-voucher")
    apply_page(writer, width, height)
    painter = QPainter(writer)
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform | QPainter.RenderHint.TextAntialiasing)
    try:
        paint_pages(painter, writer.newPage, settings, vouchers, width, height, dpi / 25.4)
    finally:
        painter.end()


def print_vouchers(printer, settings: Settings, vouchers: list[Voucher]) -> None:
    width, height = page_size_mm(settings, vouchers)
    apply_page(printer, width, height)
    painter = QPainter()
    if not painter.begin(printer):
        raise RuntimeError(tr("Impossibile avviare la stampa"))
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform | QPainter.RenderHint.TextAntialiasing)
    try:
        k = printer.resolution() / 25.4
        paint_pages(painter, printer.newPage, settings, vouchers, width, height, k)
    finally:
        painter.end()


def preview_image(settings: Settings, voucher: Voucher, px_per_mm: float = 6.0) -> QImage:
    """Un solo biglietto, come verrà stampato (per l'anteprima)."""
    page = page_for(settings)
    if settings.print_format == FORMAT_A4:
        w_mm = (page.width_mm - 2 * A4_MARGIN) / A4_COLS
        h_mm = (page.height_mm - 2 * A4_MARGIN) / A4_ROWS
    elif settings.print_format in (FORMAT_58, FORMAT_80):
        w_mm = page.width_mm
        h_mm = thermal_height_mm(settings, [voucher], dpi=px_per_mm * 25.4)
    else:
        w_mm, h_mm = page.width_mm, page.height_mm
    image = QImage(round(w_mm * px_per_mm), round(h_mm * px_per_mm), QImage.Format.Format_ARGB32)
    dpm = round(px_per_mm * 1000)
    image.setDotsPerMeterX(dpm)
    image.setDotsPerMeterY(dpm)
    image.fill(QColor("white"))
    painter = QPainter(image)
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform | QPainter.RenderHint.TextAntialiasing)
    k = px_per_mm
    if settings.print_format == FORMAT_A4:
        pad = 4.0 * k
        rect = QRectF(0, 0, image.width(), image.height())
        pen = QPen(QColor("#bbbbbb"))
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawRect(rect.adjusted(0, 0, -1, -1))
        _Card(settings, voucher, k, load_logo(settings)).fit(painter, rect.adjusted(pad, pad, -pad, -pad), True)
    else:
        _, inner, horizontal = card_rects(settings, w_mm, h_mm, k)[0]
        _Card(settings, voucher, k, load_logo(settings)).fit(painter, inner, horizontal)
    painter.end()
    return image
