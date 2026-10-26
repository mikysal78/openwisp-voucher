#!/bin/sh
# Eseguibile unico per il sistema su cui gira (Linux o, da Git Bash, Windows).
set -eu
cd "$(dirname "$0")/.."
sep=":"
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) sep=";" ;; esac
python -m PyInstaller --noconfirm --clean --onefile --windowed \
  --name openwisp-voucher \
  --icon openwisp_voucher/icon.png \
  --add-data "openwisp_voucher/icon.png${sep}openwisp_voucher" \
  --exclude-module tkinter \
  packaging/launch.py
