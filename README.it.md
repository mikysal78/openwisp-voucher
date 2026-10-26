# openwisp-voucher

[English](README.md) | **Italiano**

Programma per computer (Linux e Windows) che crea **accessi Wi-Fi a tempo**
per il captive portal di [OpenWISP](https://openwisp.org) e li consegna come
**biglietti o etichette**, come negli hotel: «Mario ha accesso per 3 giorni,
poi l'utente si spegne da solo».

Usa l'API REST di OpenWISP con il token dell'utente che si collega: sul server
non si installa niente.

| Nuovo accesso | Accessi creati | Impostazioni |
|---|---|---|
| ![Nuovo accesso](docs/new.png) | ![Accessi creati](docs/history.png) | ![Impostazioni](docs/settings.png) |

| Biglietto A4 | Scontrino 58 mm |
|---|---|
| ![Biglietto A4](docs/ticket-a4.png) | ![Scontrino 58 mm](docs/ticket-58mm.png) |

## Funzioni

- **Ospite con nome**: nome utente (es. `mrossi`), email dell'ospite, nome,
  password (generata senza caratteri che si confondono, come 0/O e 1/l).
- **Serie di voucher**: `prefisso1`, `prefisso2`, … fino a 200 alla volta, con
  le password generate dal server.
- **Validità in giorni**: sul biglietto c'è l'ultimo giorno valido; OpenWISP
  disattiva l'utente alle 00:01 del giorno dopo. Si può anche **disattivare
  subito**.
- **Stampa**: foglio A4 con 10 biglietti da ritagliare, stampanti di scontrini
  da 58 o 80 mm, etichette di qualsiasi misura (Brother QL, Dymo, …) oppure
  **PDF**.
- **Biglietto personalizzabile**: logo, nome della struttura, sito web, email,
  telefono, nome della rete Wi-Fi, nota in fondo e **QR code** che collega alla
  rete Wi-Fi (o apre un indirizzo web).
- **Copia testo** per mandare le credenziali in chat o per email (il programma
  non invia niente da solo).
- **Accessi creati**: elenco con ricerca, ristampa, disattivazione, stato
  aggiornato dal server.
- **Organizzazioni**: il superuser sceglie l'organizzazione; un operatore
  lavora solo su quelle che gestisce.
- Interfaccia in italiano e in inglese.

## Scaricare

Dalle [release](https://github.com/mikysal78/openwisp-voucher/releases):

- **Windows**: `openwisp-voucher-<versione>-windows.exe`. Non è firmato:
  SmartScreen può chiedere conferma («Ulteriori informazioni» → «Esegui
  comunque»).
- **Linux** (x86_64): estrai `openwisp-voucher-<versione>-linux-x86_64.tar.gz`
  e avvia `./openwisp-voucher`. Su Debian/Ubuntu a Qt serve anche
  `sudo apt install libxcb-cursor0`.

Le impronte sono in `SHA256SUMS`; la provenienza della compilazione è attestata
da GitHub (`gh attestation verify <file> -R mikysal78/openwisp-voucher`).

Oppure, con Python 3.10+: `pipx install git+https://github.com/mikysal78/openwisp-voucher`.

## Cosa serve sul server OpenWISP

- **openwisp-radius** (1.x) con l'API dei batch (`/api/v1/radius/batch/`): gli
  accessi sono «operazioni di creazione utenti in serie», visibili nell'admin.
- Il task periodico **`deactivate_expired_users`** di openwisp-users (celery
  beat), che ogni notte disattiva gli utenti scaduti. In
  [ansible-openwisp2](https://github.com/openwisp/ansible-openwisp2) è attivo
  di serie.
- Per gli utenti con nome OpenWISP richiede un'**email**: si usa quella
  dell'ospite. Le serie di voucher non ne hanno bisogno.

### Utenti operatori

Chi sta alla reception non deve essere superuser. Nell'admin di OpenWISP:

1. crea un utente con **stato staff**;
2. rendilo **gestore** dell'organizzazione (utenti dell'organizzazione → «is admin»);
3. dagli, direttamente o con un gruppo, questi permessi:
   - `openwisp_radius | radius batch`: aggiunta, visualizzazione
   - `openwisp_radius | radius group`: visualizzazione
   - `openwisp_users | user`: visualizzazione, modifica (per disattivare gli accessi)
   - `openwisp_users | organization`: visualizzazione

In un'installazione standard il gruppo predefinito «Administrator» di OpenWISP
li comprende; se ne manca uno, il programma mostra «Permesso negato».

## Come funziona

- **Accesso**: indirizzo del server, utente e password. La password serve solo
  per ottenere il token delle API e non viene salvata; il token va nel
  portachiavi del sistema (Gestione credenziali di Windows, GNOME
  Keyring/KWallet) e, solo se non c'è un portachiavi, in un file leggibile
  soltanto dall'utente.
- **Ospite con nome**: batch CSV di una riga con la password scelta nel
  programma (`cleartext$…`), così OpenWISP non manda email. Se il nome è già
  preso OpenWISP aggiunge un numero (`mrossi1`): sul biglietto c'è il nome vero.
- **Serie**: batch con prefisso. Oltre 14 utenti OpenWISP lavora in background
  e non restituisce le password, quindi le serie più lunghe sono divise in
  batch da 14.
- **Dati sul computer**: impostazioni, logo ed elenco degli accessi creati (con
  le password, per poterli ristampare) stanno in `~/.config/openwisp-voucher`
  su Linux e in `%APPDATA%\openwisp-voucher` su Windows, leggibili solo
  dall'utente. «Togli dall'elenco» cancella solo la riga locale.

## Sviluppo

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[test,build]"
.venv/bin/python -m openwisp_voucher      # avvio
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
PATH=$PWD/.venv/bin:$PATH packaging/build.sh   # eseguibile unico in dist/
```

### Pubblicare una release

1. Aggiorna `__version__` in `openwisp_voucher/__init__.py` e aggiungi una
   sezione `## <versione>` al `CHANGELOG.md`.
2. Fai il push di un tag `v<versione>`: GitHub Actions esegue i test, compila
   gli eseguibili per Windows e Linux, calcola `SHA256SUMS`, attesta la
   provenienza e pubblica la release con le note del CHANGELOG.

## Collegati

- [openwisp-android](https://github.com/mikysal78/openwisp-android): gestire
  OpenWISP dal telefono.
- [Come è fatta l'infrastruttura NINUX Basilicata](https://mikysal78.github.io/ninux-basilicata-infra/).

Progetto indipendente, non è un prodotto ufficiale del progetto OpenWISP.

## Licenza

[GPL-3.0](LICENSE)
