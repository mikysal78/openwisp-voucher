"""Finestra principale: nuovo accesso, accessi creati, impostazioni."""

from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import QDate, QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QPixmap
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import __version__, i18n, render, store
from .api import BATCH_SYNC_MAX, ApiError, OpenWispApi, normalize_server
from .i18n import tr
from .store import HistoryEntry, Settings
from .voucher import (
    Voucher,
    batch_name,
    days_for_expiration,
    expiration_for_days,
    generate_password,
    share_text,
    valid_prefix,
    valid_username,
)

MAX_SERIES = 200


# --- lavoro in background: la rete non deve bloccare la finestra ---


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(object)


class _Job(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.signals = _Signals()

    def run(self):
        try:
            result = self.fn()
        except Exception as error:  # mostrato all'utente
            self.signals.failed.emit(error)
        else:
            self.signals.done.emit(result)


class Background:
    def __init__(self, parent):
        self.parent = parent
        self.jobs = set()

    def run(self, fn, on_done, on_error=None):
        job = _Job(fn)
        self.jobs.add(job)

        def finish(handler, value):
            self.jobs.discard(job)
            QGuiApplication.restoreOverrideCursor()
            if handler:
                handler(value)

        job.signals.done.connect(lambda r: finish(on_done, r))
        job.signals.failed.connect(lambda e: finish(on_error or self.parent.show_error, e))
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QThreadPool.globalInstance().start(job)


def sample_voucher(settings: Settings) -> Voucher:
    return Voucher(
        settings.series_prefix + "1" if settings.series_prefix else "ospite1",
        generate_password(settings.password_length),
        expiration_for_days(max(settings.default_days, 1)),
        notes=tr("Camera 12"),
    )


class Preview(QLabel):
    """Anteprima di un biglietto con le impostazioni correnti."""

    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumWidth(320)
        self.setStyleSheet("QLabel { background: #e6e6e6; padding: 12px; }")

    def show_voucher(self, settings: Settings, voucher: Voucher):
        image = render.preview_image(settings, voucher, px_per_mm=6)
        pixmap = QPixmap.fromImage(image)
        max_w, max_h = 380, 560
        if pixmap.width() > max_w or pixmap.height() > max_h:
            pixmap = pixmap.scaled(
                max_w, max_h, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.setPixmap(pixmap)


class LoginDialog(QDialog):
    def __init__(self, parent, server: str, username: str):
        super().__init__(parent)
        self.setWindowTitle(tr("Accesso a OpenWISP"))
        form = QFormLayout(self)
        self.server = QLineEdit(server)
        self.server.setPlaceholderText("openwisp.example.org")
        self.username = QLineEdit(username)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(tr("Server"), self.server)
        form.addRow(tr("Utente"), self.username)
        form.addRow(tr("Password"), self.password)
        note = QLabel(tr("La password non viene salvata: serve solo a ottenere il token delle API."))
        note.setWordWrap(True)
        form.addRow(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        (self.password if username else self.username).setFocus()


# --- scheda "Nuovo accesso" ---


class NewTab(QWidget):
    def __init__(self, window: "MainWindow"):
        super().__init__()
        self.w = window
        self.created: list[Voucher] = []
        outer = QHBoxLayout(self)
        left = QVBoxLayout()
        outer.addLayout(left, 3)

        kind = QHBoxLayout()
        self.guest_radio = QRadioButton(tr("Ospite con nome"))
        self.series_radio = QRadioButton(tr("Serie di voucher"))
        self.guest_radio.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.guest_radio)
        group.addButton(self.series_radio)
        kind.addWidget(self.guest_radio)
        kind.addWidget(self.series_radio)
        kind.addStretch()
        left.addLayout(kind)

        self.stack = QStackedWidget()
        left.addWidget(self.stack)

        guest = QWidget()
        gf = QFormLayout(guest)
        self.username = QLineEdit()
        self.username.setPlaceholderText(tr("es. pippo"))
        self.email = QLineEdit()
        self.email.setPlaceholderText(tr("obbligatoria per OpenWISP"))
        self.first_name = QLineEdit()
        self.last_name = QLineEdit()
        pw_row = QHBoxLayout()
        self.password = QLineEdit()
        regen = QPushButton(tr("Genera"))
        regen.clicked.connect(self.new_password)
        pw_row.addWidget(self.password)
        pw_row.addWidget(regen)
        gf.addRow(tr("Nome utente"), self.username)
        gf.addRow(tr("Email dell'ospite"), self.email)
        gf.addRow(tr("Nome"), self.first_name)
        gf.addRow(tr("Cognome"), self.last_name)
        gf.addRow(tr("Password"), pw_row)
        self.stack.addWidget(guest)

        series = QWidget()
        sf = QFormLayout(series)
        self.prefix = QLineEdit()
        self.count = QSpinBox()
        self.count.setRange(1, MAX_SERIES)
        self.count.setValue(10)
        sf.addRow(tr("Prefisso"), self.prefix)
        sf.addRow(tr("Quantità"), self.count)
        hint = QLabel(tr("Nomi utente come prefisso1, prefisso2, …; le password le genera il server."))
        hint.setWordWrap(True)
        sf.addRow(hint)
        self.stack.addWidget(series)
        self.guest_radio.toggled.connect(lambda on: self.stack.setCurrentIndex(0 if on else 1))

        validity = QGroupBox(tr("Validità"))
        vf = QFormLayout(validity)
        self.days = QSpinBox()
        self.days.setRange(1, 3650)
        self.days.setSuffix(" " + tr("giorni"))
        self.until = QDateEdit()
        self.until.setCalendarPopup(True)
        self.until.setDisplayFormat("dd/MM/yyyy")
        self.until.setMinimumDate(QDate.currentDate())
        self.until_hint = QLabel()
        self.until_hint.setWordWrap(True)
        self.days.valueChanged.connect(self._days_changed)
        self.until.dateChanged.connect(self._date_changed)
        vf.addRow(tr("Durata"), self.days)
        vf.addRow(tr("Ultimo giorno valido"), self.until)
        vf.addRow(self.until_hint)
        self.notes = QLineEdit()
        self.notes.setPlaceholderText(tr("es. Camera 12 (stampata sul biglietto)"))
        vf.addRow(tr("Nota"), self.notes)
        left.addWidget(validity)

        actions = QHBoxLayout()
        self.print_now = QCheckBox(tr("Stampa subito"))
        self.print_now.setChecked(True)
        self.create_button = QPushButton(tr("Crea accesso"))
        self.create_button.setDefault(True)
        self.create_button.clicked.connect(self.create)
        actions.addWidget(self.print_now)
        actions.addStretch()
        actions.addWidget(self.create_button)
        left.addLayout(actions)

        self.result = QGroupBox(tr("Appena creati"))
        rl = QVBoxLayout(self.result)
        self.result_text = QPlainTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setMaximumHeight(140)
        rl.addWidget(self.result_text)
        rb = QHBoxLayout()
        for label, slot in (
            (tr("Stampa"), lambda: self.w.print_vouchers(self.created)),
            (tr("Salva PDF"), lambda: self.w.save_pdf(self.created)),
            (tr("Copia testo"), lambda: self.w.copy_text(self.created)),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            rb.addWidget(button)
        rl.addLayout(rb)
        self.result.setVisible(False)
        left.addWidget(self.result)
        left.addStretch()

        self.preview = Preview()
        outer.addWidget(self.preview, 2, Qt.AlignmentFlag.AlignTop)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(150)
        self._preview_timer.timeout.connect(self.refresh_preview)
        for widget in (self.username, self.password, self.prefix, self.notes):
            widget.textChanged.connect(self._preview_timer.start)
        self.until.dateChanged.connect(self._preview_timer.start)
        self.guest_radio.toggled.connect(self._preview_timer.start)
        self.reset_defaults()

    def reset_defaults(self):
        s = self.w.settings
        self.prefix.setText(s.series_prefix)
        self.days.setValue(max(s.default_days, 1))
        self._days_changed(self.days.value())
        self.new_password()

    def new_password(self):
        self.password.setText(generate_password(self.w.settings.password_length))

    def _days_changed(self, days):
        target = expiration_for_days(days)
        qd = QDate(target.year, target.month, target.day)
        if self.until.date() != qd:
            self.until.blockSignals(True)
            self.until.setDate(qd)
            self.until.blockSignals(False)
        self._update_hint()

    def _date_changed(self, qd: QDate):
        days = days_for_expiration(date(qd.year(), qd.month(), qd.day()))
        if days != self.days.value():
            self.days.blockSignals(True)
            self.days.setValue(max(days, 1))
            self.days.blockSignals(False)
        self._update_hint()

    def expiration(self) -> date:
        qd = self.until.date()
        return date(qd.year(), qd.month(), qd.day())

    def _update_hint(self):
        end = self.expiration()
        off = end.toordinal() + 1
        self.until_hint.setText(
            tr("Funziona fino alle 24:00 del {date}; OpenWISP lo disattiva alle 00:01 del {next}.").format(
                date=end.strftime("%d/%m/%Y"),
                next=date.fromordinal(off).strftime("%d/%m/%Y"),
            )
        )

    def refresh_preview(self):
        """Il biglietto come uscirà con i dati scritti finora."""
        s = self.w.settings
        if self.guest_radio.isChecked():
            username = self.username.text().strip() or tr("es. pippo").split()[-1]
            password = self.password.text().strip()
        else:
            username = (self.prefix.text().strip() or "ospite") + "1"
            password = "•" * s.password_length
        voucher = Voucher(username, password, self.expiration(), notes=self.notes.text().strip())
        self.preview.show_voucher(s, voucher)

    def create(self):
        if not self.w.ensure_ready():
            return
        s = self.w.settings
        expiration = self.expiration()
        notes = self.notes.text().strip()
        api = self.w.api
        org = s.organization_slug
        group = s.radius_group or None

        if self.guest_radio.isChecked():
            username = self.username.text().strip()
            email = self.email.text().strip()
            password = self.password.text().strip()
            if not valid_username(username):
                return self.w.show_error(tr("Nome utente non valido: solo lettere, cifre e @ . + - _"))
            if "@" not in email:
                return self.w.show_error(tr("OpenWISP richiede l'email dell'ospite"))
            if len(password) < 6:
                return self.w.show_error(tr("Password troppo corta (almeno 6 caratteri)"))
            guest = " ".join(p for p in (self.first_name.text().strip(), self.last_name.text().strip()) if p)

            def work():
                c = api.create_user(
                    org, batch_name("ospite"), username, password, email, expiration,
                    self.first_name.text().strip(), self.last_name.text().strip(), group, notes,
                )
                return [(c, guest)]
        else:
            prefix = self.prefix.text().strip()
            count = self.count.value()
            if not valid_prefix(prefix):
                return self.w.show_error(tr("Prefisso non valido: fino a 20 tra lettere, cifre e @ . + - _"))

            def work():
                out = []
                name = batch_name("serie")
                remaining, part = count, 1
                # oltre 14 utenti il server lavora in background senza restituire
                # le password: si creano più batch piccoli
                while remaining:
                    n = min(remaining, BATCH_SYNC_MAX)
                    out += [(c, "") for c in api.create_series(
                        org, f"{name}-{part}", prefix, n, expiration, group, notes)]
                    remaining -= n
                    part += 1
                return out

        def done(results):
            now = datetime.now().isoformat(timespec="seconds")
            vouchers = []
            for cred, guest in results:
                vouchers.append(Voucher(cred.username, cred.password, expiration, guest, notes))
                self.w.history.append(HistoryEntry(
                    username=cred.username, password=cred.password,
                    expiration=expiration.isoformat(), created=now,
                    organization_slug=org, user_id=cred.user_id,
                    guest=guest, notes=notes, active=True,
                ))
            store.save_history(self.w.history)
            self.w.history_tab.reload()
            self.created = vouchers
            self.result_text.setPlainText("\n\n".join(
                share_text(v, s.ssid, s.website) for v in vouchers))
            self.result.setVisible(True)
            self.w.statusBar().showMessage(tr("Creati {n} accessi").format(n=len(vouchers)), 8000)
            if self.guest_radio.isChecked():
                self.username.clear()
                self.email.clear()
                self.first_name.clear()
                self.last_name.clear()
                self.new_password()
            if self.print_now.isChecked():
                self.w.print_vouchers(vouchers)

        self.w.bg.run(work, done)


# --- scheda "Accessi creati" ---


class HistoryTab(QWidget):
    COLUMNS = ("Creato", "Utente", "Password", "Ultimo giorno", "Ospite", "Nota", "Stato")

    def __init__(self, window: "MainWindow"):
        super().__init__()
        self.w = window
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.only_valid = QCheckBox(tr("Solo quelli ancora validi"))
        self.only_valid.setChecked(True)
        self.only_valid.toggled.connect(self.reload)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Cerca utente, ospite o nota"))
        self.search.textChanged.connect(self.reload)
        top.addWidget(self.only_valid)
        top.addWidget(self.search, 1)
        layout.addLayout(top)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([tr(c) for c in self.COLUMNS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        for label, slot in (
            (tr("Ristampa"), lambda: self.w.print_vouchers(self.selected_vouchers())),
            (tr("Salva PDF"), lambda: self.w.save_pdf(self.selected_vouchers())),
            (tr("Copia testo"), lambda: self.w.copy_text(self.selected_vouchers())),
            (tr("Disattiva ora"), self.deactivate),
            (tr("Aggiorna stato"), self.refresh_state),
            (tr("Togli dall'elenco"), self.forget),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(buttons)
        note = QLabel(tr("L'elenco e le password stanno solo su questo computer, nella cartella di configurazione del programma."))
        note.setWordWrap(True)
        note.setStyleSheet("color: #666;")
        layout.addWidget(note)
        self.rows: list[HistoryEntry] = []
        self.reload()

    def reload(self):
        today = date.today().isoformat()
        text = self.search.text().strip().lower()
        org = self.w.settings.organization_slug
        rows = []
        for e in reversed(self.w.history):
            if org and e.organization_slug != org:
                continue
            if self.only_valid.isChecked() and (e.expiration < today or e.active is False):
                continue
            if text and text not in f"{e.username} {e.guest} {e.notes}".lower():
                continue
            rows.append(e)
        self.rows = rows
        self.table.setRowCount(len(rows))
        for r, e in enumerate(rows):
            if e.active is False:
                state = tr("disattivato")
            elif e.expiration < today:
                state = tr("scaduto")
            else:
                state = tr("attivo")
            values = (
                e.created.replace("T", " ")[:16],
                e.username,
                e.password,
                date.fromisoformat(e.expiration).strftime("%d/%m/%Y"),
                e.guest,
                e.notes,
                state,
            )
            for c, value in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(value))

    def selected(self) -> list[HistoryEntry]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.rows[r] for r in rows]

    def selected_vouchers(self) -> list[Voucher]:
        return [
            Voucher(e.username, e.password, date.fromisoformat(e.expiration), e.guest, e.notes)
            for e in self.selected()
        ]

    def deactivate(self):
        entries = [e for e in self.selected() if e.user_id]
        if not entries or not self.w.ensure_ready():
            return
        names = ", ".join(e.username for e in entries[:10])
        if QMessageBox.question(
            self, tr("Disattiva"),
            tr("Disattivare subito {n} accessi ({names})? L'utente non potrà più collegarsi.").format(
                n=len(entries), names=names),
        ) != QMessageBox.StandardButton.Yes:
            return
        api = self.w.api

        def work():
            for e in entries:
                api.set_active(e.user_id, False)
            return entries

        def done(changed):
            for e in changed:
                e.active = False
            store.save_history(self.w.history)
            self.reload()

        self.w.bg.run(work, done)

    def refresh_state(self):
        entries = [e for e in self.selected() or self.rows if e.user_id]
        if not entries or not self.w.ensure_ready():
            return
        api = self.w.api

        def work():
            states = {}
            for e in entries:
                try:
                    user = api.user(e.user_id)
                    states[e.user_id] = bool(user.get("is_active"))
                except ApiError as error:
                    if error.status == 404:
                        states[e.user_id] = False  # cancellato dal server
                    else:
                        raise
            return states

        def done(states):
            for e in entries:
                if e.user_id in states:
                    e.active = states[e.user_id]
            store.save_history(self.w.history)
            self.reload()

        self.w.bg.run(work, done)

    def forget(self):
        entries = self.selected()
        if not entries:
            return
        if QMessageBox.question(
            self, tr("Togli dall'elenco"),
            tr("Togliere {n} righe dall'elenco locale? Gli utenti su OpenWISP restano come sono.").format(n=len(entries)),
        ) != QMessageBox.StandardButton.Yes:
            return
        ids = {id(e) for e in entries}
        self.w.history[:] = [e for e in self.w.history if id(e) not in ids]
        store.save_history(self.w.history)
        self.reload()


# --- scheda "Impostazioni" ---


class SettingsTab(QWidget):
    FORMATS = (
        (store.FORMAT_A4, "Foglio A4 (10 biglietti da ritagliare)"),
        (store.FORMAT_58, "Scontrino 58 mm"),
        (store.FORMAT_80, "Scontrino 80 mm"),
        (store.FORMAT_LABEL, "Etichetta (misure a scelta)"),
    )
    QRS = (
        (store.QR_WIFI, "Collegamento alla rete Wi-Fi"),
        (store.QR_URL, "Indirizzo web"),
        (store.QR_NONE, "Nessun QR code"),
    )
    LANGS = (("", "Lingua del sistema"), ("it", "Italiano"), ("en", "English"))

    def __init__(self, window: "MainWindow"):
        super().__init__()
        self.w = window
        s = window.settings
        self._loading = True
        outer = QHBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        col = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll, 3)

        # server
        server = QGroupBox(tr("Server OpenWISP"))
        sf = QFormLayout(server)
        self.account = QLabel()
        self.account.setWordWrap(True)
        login_row = QHBoxLayout()
        self.login_button = QPushButton(tr("Accedi…"))
        self.login_button.clicked.connect(self.w.login)
        self.logout_button = QPushButton(tr("Esci"))
        self.logout_button.clicked.connect(self.w.logout)
        # rilegge organizzazioni e gruppi, ad esempio dopo averne creato uno nell'admin
        self.refresh_button = QPushButton(tr("Aggiorna dal server"))
        self.refresh_button.clicked.connect(self.w.load_account)
        login_row.addWidget(self.login_button)
        login_row.addWidget(self.logout_button)
        login_row.addWidget(self.refresh_button)
        login_row.addStretch()
        self.org = QComboBox()
        self.org.currentIndexChanged.connect(self._org_changed)
        self.group = QComboBox()
        self.group.currentIndexChanged.connect(self._group_changed)
        sf.addRow(tr("Collegato come"), self.account)
        sf.addRow(login_row)
        sf.addRow(tr("Organizzazione"), self.org)
        sf.addRow(tr("Gruppo RADIUS"), self.group)
        col.addWidget(server)

        # struttura
        venue = QGroupBox(tr("Struttura (stampata sul biglietto)"))
        vf = QFormLayout(venue)
        self.venue_name = QLineEdit(s.venue_name)
        logo_row = QHBoxLayout()
        self.logo_preview = QLabel()
        self.logo_preview.setFixedSize(96, 64)
        self.logo_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_preview.setStyleSheet("border: 1px solid #ccc; background: white;")
        choose = QPushButton(tr("Scegli…"))
        choose.clicked.connect(self.choose_logo)
        remove = QPushButton(tr("Rimuovi"))
        remove.clicked.connect(self.remove_logo)
        logo_row.addWidget(self.logo_preview)
        logo_row.addWidget(choose)
        logo_row.addWidget(remove)
        logo_row.addStretch()
        self.website = QLineEdit(s.website)
        self.website.setPlaceholderText("www.example.org")
        self.email = QLineEdit(s.email)
        self.phone = QLineEdit(s.phone)
        self.ssid = QLineEdit(s.ssid)
        self.wifi_password = QLineEdit(s.wifi_password)
        self.wifi_password.setPlaceholderText(tr("vuota se la rete è aperta (captive portal)"))
        self.footer_note = QLineEdit(s.footer_note)
        self.footer_note.setPlaceholderText(tr("es. Assistenza: reception, interno 9"))
        vf.addRow(tr("Nome"), self.venue_name)
        vf.addRow(tr("Logo"), logo_row)
        vf.addRow(tr("Sito web"), self.website)
        vf.addRow(tr("Email"), self.email)
        vf.addRow(tr("Telefono"), self.phone)
        vf.addRow(tr("Nome della rete Wi-Fi"), self.ssid)
        vf.addRow(tr("Password della rete"), self.wifi_password)
        vf.addRow(tr("Nota in fondo"), self.footer_note)
        col.addWidget(venue)

        # stampa
        printing = QGroupBox(tr("Stampa"))
        pf = QFormLayout(printing)
        self.format = QComboBox()
        for key, label in self.FORMATS:
            self.format.addItem(tr(label), key)
        self.format.setCurrentIndex(max(0, self.format.findData(s.print_format)))
        self.label_w = QDoubleSpinBox()
        self.label_h = QDoubleSpinBox()
        for spin, value in ((self.label_w, s.label_width_mm), (self.label_h, s.label_height_mm)):
            spin.setRange(20, 300)
            spin.setDecimals(1)
            spin.setSuffix(" mm")
            spin.setValue(value)
        size_row = QHBoxLayout()
        size_row.addWidget(self.label_w)
        size_row.addWidget(QLabel("×"))
        size_row.addWidget(self.label_h)
        size_row.addStretch()
        self.qr = QComboBox()
        for key, label in self.QRS:
            self.qr.addItem(tr(label), key)
        self.qr.setCurrentIndex(max(0, self.qr.findData(s.qr)))
        self.qr_url = QLineEdit(s.qr_url)
        self.qr_url.setPlaceholderText("https://")
        test = QPushButton(tr("Stampa di prova"))
        test.clicked.connect(lambda: self.w.print_vouchers([sample_voucher(self.w.settings)]))
        pf.addRow(tr("Formato"), self.format)
        pf.addRow(tr("Misure etichetta"), size_row)
        pf.addRow(tr("QR code"), self.qr)
        pf.addRow(tr("Indirizzo del QR"), self.qr_url)
        pf.addRow(test)
        col.addWidget(printing)

        # predefiniti
        defaults = QGroupBox(tr("Valori predefiniti"))
        df = QFormLayout(defaults)
        self.default_days = QSpinBox()
        self.default_days.setRange(1, 3650)
        self.default_days.setValue(max(s.default_days, 1))
        self.default_days.setSuffix(" " + tr("giorni"))
        self.series_prefix = QLineEdit(s.series_prefix)
        self.password_length = QSpinBox()
        self.password_length.setRange(6, 32)
        self.password_length.setValue(s.password_length)
        self.language = QComboBox()
        for key, label in self.LANGS:
            self.language.addItem(tr(label), key)
        self.language.setCurrentIndex(max(0, self.language.findData(s.language)))
        df.addRow(tr("Durata"), self.default_days)
        df.addRow(tr("Prefisso delle serie"), self.series_prefix)
        df.addRow(tr("Lunghezza password"), self.password_length)
        df.addRow(tr("Lingua"), self.language)
        col.addWidget(defaults)
        col.addStretch()

        self.preview = Preview()
        outer.addWidget(self.preview, 2, Qt.AlignmentFlag.AlignTop)

        # salvataggio automatico, raggruppato
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self.save)
        for widget in (self.venue_name, self.website, self.email, self.phone, self.ssid,
                       self.wifi_password, self.footer_note, self.qr_url, self.series_prefix):
            widget.textChanged.connect(self._changed)
        for widget in (self.format, self.qr):
            widget.currentIndexChanged.connect(self._changed)
        self.language.currentIndexChanged.connect(self._language_changed)
        for widget in (self.label_w, self.label_h, self.default_days, self.password_length):
            widget.valueChanged.connect(self._changed)
        self._update_enabled()
        self._show_logo()
        self._loading = False

    def _changed(self, *_):
        if not self._loading:
            self._update_enabled()
            self._timer.start()

    def _language_changed(self, index):
        if not self._loading:
            self.w.change_language(self.language.itemData(index))

    def _update_enabled(self):
        is_label = self.format.currentData() == store.FORMAT_LABEL
        self.label_w.setEnabled(is_label)
        self.label_h.setEnabled(is_label)
        self.qr_url.setEnabled(self.qr.currentData() == store.QR_URL)
        self.wifi_password.setEnabled(self.qr.currentData() == store.QR_WIFI)

    def save(self):
        s = self.w.settings
        s.venue_name = self.venue_name.text().strip()
        s.website = self.website.text().strip()
        s.email = self.email.text().strip()
        s.phone = self.phone.text().strip()
        s.ssid = self.ssid.text().strip()
        s.wifi_password = self.wifi_password.text()
        s.footer_note = self.footer_note.text().strip()
        s.print_format = self.format.currentData()
        s.label_width_mm = self.label_w.value()
        s.label_height_mm = self.label_h.value()
        s.qr = self.qr.currentData()
        s.qr_url = self.qr_url.text().strip()
        s.default_days = self.default_days.value()
        s.series_prefix = self.series_prefix.text().strip()
        s.password_length = self.password_length.value()
        s.language = self.language.currentData()
        store.save_settings(s)
        self.w.settings_changed()

    def refresh_preview(self):
        self.preview.show_voucher(self.w.settings, sample_voucher(self.w.settings))

    def _show_logo(self):
        path = self.w.settings.logo_path
        if path:
            pixmap = QPixmap(str(path)).scaled(
                92, 60, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.logo_preview.setPixmap(pixmap)
        else:
            self.logo_preview.setPixmap(QPixmap())
            self.logo_preview.setText(tr("nessuno"))

    def choose_logo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Scegli il logo"), "", tr("Immagini (*.png *.jpg *.jpeg *.bmp *.gif *.svg)"))
        if not path:
            return
        from PySide6.QtGui import QImage

        if QImage(path).isNull():
            return self.w.show_error(tr("Immagine non leggibile"))
        self.w.settings.logo_file = store.import_logo(path)
        self._show_logo()
        self.save()

    def remove_logo(self):
        store.remove_logo()
        self.w.settings.logo_file = ""
        self._show_logo()
        self.save()

    # -- server --

    def show_account(self, user: dict | None):
        s = self.w.settings
        if self.w.api is None:
            self.account.setText(tr("non collegato"))
        else:
            role = ""
            if user is not None:
                role = tr(" (amministratore)") if user.get("is_superuser") else tr(" (operatore)")
            self.account.setText(f"{s.username}{role} — {self.w.api.server}")
        self.logout_button.setEnabled(self.w.api is not None)
        self.refresh_button.setEnabled(self.w.api is not None)

    def set_organizations(self, orgs: list[dict], is_superuser: bool):
        """Il superuser sceglie; gli altri vedono solo le loro organizzazioni."""
        s = self.w.settings
        self.org.blockSignals(True)
        self.org.clear()
        for org in orgs:
            self.org.addItem(org.get("name") or org.get("slug"), org)
        index = next((i for i, o in enumerate(orgs) if o.get("id") == s.organization_id), 0)
        if orgs:
            self.org.setCurrentIndex(index)
        self.org.setEnabled(is_superuser or len(orgs) > 1)
        self.org.blockSignals(False)
        self._org_changed(self.org.currentIndex())

    def _org_changed(self, index):
        org = self.org.itemData(index)
        s = self.w.settings
        if not org:
            return
        changed = org.get("id") != s.organization_id
        s.organization_id = org.get("id", "")
        s.organization_slug = org.get("slug", "")
        s.organization_name = org.get("name", "")
        if changed:
            s.radius_group = ""
        store.save_settings(s)
        self.w.load_groups()
        self.w.history_tab.reload()
        self.w.update_status()

    def set_groups(self, groups: list[dict]):
        s = self.w.settings
        self.group.blockSignals(True)
        self.group.clear()
        self.group.addItem(tr("Predefinito dell'organizzazione"), "")
        for g in groups:
            self.group.addItem(g.get("name", ""), g.get("id"))
        self.group.setCurrentIndex(max(0, self.group.findData(s.radius_group)))
        self.group.blockSignals(False)

    def _group_changed(self, index):
        self.w.settings.radius_group = self.group.itemData(index) or ""
        store.save_settings(self.w.settings)


class MainWindow(QMainWindow):
    current: "MainWindow | None" = None  # tiene viva la finestra ricostruita

    def __init__(self, icon: QIcon | None = None):
        super().__init__()
        self.setWindowTitle(tr("Accessi Wi-Fi") + " — openwisp-voucher " + __version__)
        if icon:
            self.setWindowIcon(icon)
        self.settings = store.load_settings()
        self.history = store.load_history()
        self.api: OpenWispApi | None = None
        self.user: dict | None = None
        self.bg = Background(self)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.new_tab = NewTab(self)
        self.history_tab = HistoryTab(self)
        self.settings_tab = SettingsTab(self)
        self.tabs.addTab(self.new_tab, tr("Nuovo accesso"))
        self.tabs.addTab(self.history_tab, tr("Accessi creati"))
        self.tabs.addTab(self.settings_tab, tr("Impostazioni"))

        quit_action = QAction(self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        self.addAction(quit_action)

        self.resize(1100, 720)
        self.settings_changed()
        self.restore_session()

    # -- stato --

    def settings_changed(self):
        self.new_tab.refresh_preview()
        self.settings_tab.refresh_preview()

    def change_language(self, lang: str):
        """Le etichette si leggono alla creazione: si ricostruisce la finestra."""
        if self.settings_tab._timer.isActive():
            self.settings_tab._timer.stop()
            self.settings_tab.save()
        self.settings.language = lang
        store.save_settings(self.settings)
        i18n.set_language(lang)
        window = MainWindow(self.windowIcon())
        window.setGeometry(self.geometry())
        window.tabs.setCurrentIndex(self.tabs.currentIndex())
        window.show()
        MainWindow.current = window
        self.close()
        self.deleteLater()

    def update_status(self):
        s = self.settings
        if self.api is None:
            text = tr("Non collegato: vai in Impostazioni e premi «Accedi…»")
        else:
            text = tr("{user} su {server} — organizzazione: {org}").format(
                user=s.username, server=self.api.server, org=s.organization_name or "-")
        self.statusBar().showMessage(text)

    def show_error(self, error):
        QMessageBox.warning(self, tr("Errore"), str(error))

    def ensure_ready(self) -> bool:
        if self.api is None:
            self.show_error(tr("Prima collegati al server in Impostazioni"))
            self.tabs.setCurrentWidget(self.settings_tab)
            return False
        if not self.settings.organization_slug:
            self.show_error(tr("Scegli un'organizzazione in Impostazioni"))
            self.tabs.setCurrentWidget(self.settings_tab)
            return False
        return True

    # -- accesso --

    def restore_session(self):
        s = self.settings
        token = store.load_token(s.server, s.username) if s.server and s.username else None
        if token:
            self.api = OpenWispApi(s.server, token)
            self.load_account()
        self.settings_tab.show_account(None)
        self.update_status()

    def login(self):
        s = self.settings
        dialog = LoginDialog(self, s.server, s.username)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            server = normalize_server(dialog.server.text())
        except ApiError as error:
            return self.show_error(error)
        username = dialog.username.text().strip()
        password = dialog.password.text()
        api = OpenWispApi(server)

        def work():
            return api.obtain_token(username, password)

        def done(token):
            if s.server and s.username and (s.server, s.username) != (server, username):
                store.delete_token(s.server, s.username)
            s.server, s.username = server, username
            store.save_settings(s)
            if not store.save_token(server, username, token):
                self.statusBar().showMessage(
                    tr("Portachiavi non disponibile: token salvato in un file privato"), 8000)
            self.api = api
            self.load_account()

        self.bg.run(work, done)

    def logout(self):
        s = self.settings
        store.delete_token(s.server, s.username)
        self.api = None
        self.user = None
        self.settings_tab.set_organizations([], False)
        self.settings_tab.set_groups([])
        self.settings_tab.show_account(None)
        self.update_status()

    def load_account(self):
        api = self.api
        username = self.settings.username

        def work():
            user = api.current_user(username)
            orgs = api.organizations()
            return user, orgs

        def done(result):
            user, orgs = result
            self.user = user
            is_superuser = bool(user and user.get("is_superuser"))
            if not orgs:
                self.show_error(tr("Questo utente non gestisce nessuna organizzazione"))
            self.settings_tab.set_organizations(orgs, is_superuser)
            self.settings_tab.show_account(user)
            self.update_status()

        def failed(error):
            if isinstance(error, ApiError) and error.status == 401:
                self.logout()
            self.show_error(error)

        self.bg.run(work, done, failed)

    def load_groups(self):
        if self.api is None or not self.settings.organization_id:
            return
        api, org = self.api, self.settings.organization_id
        self.bg.run(lambda: api.radius_groups(org), self.settings_tab.set_groups,
                    lambda e: self.settings_tab.set_groups([]))

    # -- uscita delle credenziali --

    def print_vouchers(self, vouchers: list[Voucher]):
        if not vouchers:
            return self.show_error(tr("Nessun accesso selezionato"))
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        if self.settings.printer_name:
            printer.setPrinterName(self.settings.printer_name)
        dialog = QPrintDialog(printer, self)
        dialog.setWindowTitle(tr("Stampa {n} biglietti").format(n=len(vouchers)))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            render.print_vouchers(printer, self.settings, vouchers)
        except Exception as error:
            return self.show_error(error)
        if printer.outputFormat() == QPrinter.OutputFormat.NativeFormat:
            self.settings.printer_name = printer.printerName()
            store.save_settings(self.settings)

    def save_pdf(self, vouchers: list[Voucher]):
        if not vouchers:
            return self.show_error(tr("Nessun accesso selezionato"))
        name = f"accessi-wifi-{datetime.now():%Y%m%d-%H%M}.pdf"
        path, _ = QFileDialog.getSaveFileName(self, tr("Salva PDF"), name, "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            render.export_pdf(path, self.settings, vouchers)
        except Exception as error:
            return self.show_error(error)
        self.statusBar().showMessage(tr("Salvato {path}").format(path=path), 8000)

    def copy_text(self, vouchers: list[Voucher]):
        if not vouchers:
            return self.show_error(tr("Nessun accesso selezionato"))
        s = self.settings
        QGuiApplication.clipboard().setText(
            "\n\n".join(share_text(v, s.ssid, s.website) for v in vouchers))
        self.statusBar().showMessage(tr("Testo copiato: incollalo dove vuoi"), 6000)
