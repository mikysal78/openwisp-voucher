import sys
from datetime import date

from openwisp_voucher import render, store
from openwisp_voucher.voucher import Voucher


def test_settings_roundtrip_and_unknown_keys(config_home):
    s = store.Settings(venue_name="Hotel", ssid="WIFI", print_format=store.FORMAT_80)
    store.save_settings(s)
    path = config_home / "openwisp-voucher" / "settings.json"
    path.write_text(path.read_text().replace('"ssid"', '"vecchia_chiave": 1, "ssid"'))
    loaded = store.load_settings()
    assert loaded.venue_name == "Hotel" and loaded.print_format == store.FORMAT_80


def test_files_are_private(config_home):
    store.save_history([store.HistoryEntry("u", "p", "2026-10-28", "2026-10-26T10:00:00", "o")])
    path = config_home / "openwisp-voucher" / "accessi.json"
    if sys.platform != "win32":  # su Windows vale l'ACL della cartella utente
        assert path.stat().st_mode & 0o077 == 0
    assert store.load_history()[0].username == "u"


def test_logo_import(tmp_path, qapp):
    from PySide6.QtGui import QColor, QImage

    image = QImage(40, 20, QImage.Format.Format_RGB32)
    image.fill(QColor("red"))
    source = tmp_path / "Logo.PNG"
    image.save(str(source))
    s = store.Settings(logo_file=store.import_logo(source))
    assert s.logo_path is not None and s.logo_path.name == "logo.png"
    store.remove_logo()
    assert s.logo_path is None


def _settings(fmt):
    return store.Settings(venue_name="Hotel Belvedere", ssid="NINUX", website="www.example.org",
                          email="info@example.org", phone="+39 0835 000000", print_format=fmt)


def test_previews_for_every_format(qapp):
    v = Voucher("ospite12", "k7m2pq9x", date(2026, 10, 28), notes="Camera 12")
    for fmt in store.FORMATS:
        image = render.preview_image(_settings(fmt), v, px_per_mm=4)
        assert not image.isNull() and image.width() > 100


def test_pdf_pages(tmp_path, qapp):
    v = Voucher("ospite12", "k7m2pq9x", date(2026, 10, 28))
    a4 = tmp_path / "a4.pdf"
    render.export_pdf(str(a4), _settings(store.FORMAT_A4), [v] * 11)
    assert a4.read_bytes().count(b"/Type /Page\n") + a4.read_bytes().count(b"/Type /Page ") >= 1
    assert a4.stat().st_size > 1000
    thermal = tmp_path / "t.pdf"
    render.export_pdf(str(thermal), _settings(store.FORMAT_58), [v, v])
    assert thermal.stat().st_size > 1000
    width, height = render.page_size_mm(_settings(store.FORMAT_58), [v])
    assert width == 58 and 60 < height < 200


def test_long_label_content_is_shrunk(qapp):
    s = _settings(store.FORMAT_LABEL)
    s.label_width_mm, s.label_height_mm = 62, 29
    s.footer_note = "Una nota molto lunga " * 5
    image = render.preview_image(s, Voucher("ospite12", "k7m2pq9x", date(2026, 10, 28)), 4)
    assert image.height() == round(29 * 4)
