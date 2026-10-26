from datetime import date, timedelta

from openwisp_voucher import store

ORGS = [
    {"id": "a", "slug": "hotel-a", "name": "Hotel A"},
    {"id": "b", "slug": "hotel-b", "name": "Hotel B"},
]


def window(qapp):
    from openwisp_voucher.ui import MainWindow

    return MainWindow()


def test_superuser_chooses_organization(qapp, monkeypatch):
    w = window(qapp)
    monkeypatch.setattr(w, "load_groups", lambda: None)
    w.settings_tab.set_organizations(ORGS, is_superuser=True)
    assert w.settings_tab.org.isEnabled()
    w.settings_tab.org.setCurrentIndex(1)
    assert w.settings.organization_slug == "hotel-b"
    assert store.load_settings().organization_slug == "hotel-b"


def test_operator_sees_only_own_organization(qapp, monkeypatch):
    w = window(qapp)
    monkeypatch.setattr(w, "load_groups", lambda: None)
    # l'API restituisce a un operatore solo le organizzazioni che gestisce
    w.settings_tab.set_organizations(ORGS[:1], is_superuser=False)
    assert not w.settings_tab.org.isEnabled()
    assert w.settings_tab.org.count() == 1
    assert w.settings.organization_slug == "hotel-a"


def test_days_and_date_stay_in_sync(qapp):
    w = window(qapp)
    tab = w.new_tab
    tab.days.setValue(3)
    assert tab.expiration() == date.today() + timedelta(days=2)
    target = date.today() + timedelta(days=9)
    from PySide6.QtCore import QDate

    tab.until.setDate(QDate(target.year, target.month, target.day))
    assert tab.days.value() == 10


def test_create_requires_login(qapp, monkeypatch):
    w = window(qapp)
    errors = []
    monkeypatch.setattr(w, "show_error", errors.append)
    w.new_tab.create()
    assert errors and w.tabs.currentWidget() is w.settings_tab


def test_history_filters(qapp):
    today = date.today()
    store.save_history([
        store.HistoryEntry("valido", "p", (today + timedelta(days=1)).isoformat(), "2026-10-26T10:00:00", "o"),
        store.HistoryEntry("scaduto", "p", (today - timedelta(days=1)).isoformat(), "2026-10-20T10:00:00", "o"),
        store.HistoryEntry("spento", "p", today.isoformat(), "2026-10-26T10:00:00", "o", active=False),
    ])
    w = window(qapp)
    tab = w.history_tab
    assert [e.username for e in tab.rows] == ["valido"]
    tab.only_valid.setChecked(False)
    assert len(tab.rows) == 3
    tab.search.setText("scad")
    assert [e.username for e in tab.rows] == ["scaduto"]
