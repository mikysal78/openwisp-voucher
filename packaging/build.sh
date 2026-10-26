#!/bin/sh
# Eseguibile unico per il sistema su cui gira (Linux o, da Git Bash, Windows).
set -eu
cd "$(dirname "$0")/.."
sep=":"
version_args=""
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    sep=";"
    # nome del prodotto e versione nelle proprietà del .exe
    mkdir -p build
    python packaging/version_info.py build/version_info.txt
    version_args="--version-file build/version_info.txt"
    ;;
esac
# shellcheck disable=SC2086
python -m PyInstaller --noconfirm --clean --onefile --windowed $version_args \
  --name openwisp-voucher \
  --icon openwisp_voucher/icon.png \
  --add-data "openwisp_voucher/icon.png${sep}openwisp_voucher" \
  --exclude-module tkinter \
  packaging/launch.py
