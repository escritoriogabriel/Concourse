#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
PYTHON="${PYTHON:-python3}"
"$PYTHON" -m pip install -r requirements.txt
printf '\nAcesse http://127.0.0.1:8000 no seu navegador. Para encerrar, CTRL+C.\n'
"$PYTHON" app.py
