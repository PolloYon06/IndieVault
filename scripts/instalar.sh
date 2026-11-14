#!/usr/bin/env bash
# Instalador de IndieVault para macOS y Linux.
# Crea el entorno virtual, instala las dependencias y configura el .env.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "============================================================"
echo "  IndieVault - instalacion"
echo "============================================================"
echo

if [ ! -f manage.py ]; then
  echo "[ERROR] No encuentro manage.py."
  echo "Ejecuta este archivo desde la carpeta del repositorio IndieVault."
  exit 1
fi

PYTHON=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
    PYTHON="$candidate"
    break
  fi
done

if [ -z "$PYTHON" ]; then
  echo "[ERROR] Necesitas Python 3.12 o superior."
  echo "En macOS:  brew install python"
  echo "En Ubuntu: sudo apt install python3 python3-venv"
  exit 1
fi

if [ ! -d indieEnv ]; then
  echo "[1/3] Creando el entorno virtual..."
  "$PYTHON" -m venv indieEnv
else
  echo "[1/3] El entorno virtual ya existe, se reutiliza."
fi

echo "[2/3] Instalando las dependencias..."
./indieEnv/bin/python -m pip install --upgrade pip --quiet
./indieEnv/bin/python -m pip install -r requirements.txt

echo "[3/3] Configurando el archivo .env..."
./indieEnv/bin/python scripts/setup_env.py

echo
echo "============================================================"
echo "  Listo. Para arrancar la app:"
echo
echo "    source indieEnv/bin/activate"
echo "    python manage.py runserver"
echo
echo "  Y abre http://127.0.0.1:8000/ en el navegador."
echo "============================================================"
