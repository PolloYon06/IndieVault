#!/usr/bin/env python3
"""Genera el archivo .env del equipo y comprueba la conexion con Amazon RDS.

Uso:
    python scripts/setup_env.py

Solo usa la biblioteca estandar, asi que funciona antes de instalar las
dependencias. Si el entorno virtual ya tiene Django y mysqlclient, ademas
prueba la conexion real con la base y explica en castellano que falla.
"""
from __future__ import annotations

import getpass
import os
import secrets
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
CA_REL = "certs/global-bundle.pem"
DB_HOST = "database-1.cvv8xc2ptzxa.us-east-1.rds.amazonaws.com"
DB_PORT = "3306"
DB_NAME = "indievault"
DB_USER = "indievault_app"

CHECK_CODE = r"""
import os, sys
os.chdir(r"{root}")
sys.path.insert(0, r"{root}")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ProyectoIndieVault.settings")
try:
    import django
    django.setup()
    from django.db import connection
    connection.ensure_connection()
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM IndieVault_game")
        print("RESULT_OK", cursor.fetchone()[0])
except ModuleNotFoundError as exc:
    print("RESULT_NODEP", exc.name)
except Exception as exc:
    print("RESULT_FAIL", type(exc).__name__, str(exc).replace("\n", " ")[:400])
"""


def say(message: str = "") -> None:
    print(message)


def fail(message: str) -> None:
    say(f"\n  ERROR: {message}")
    sys.exit(1)


def ask_password() -> str:
    env_password = os.environ.get("INDEVAULT_DB_PASSWORD")
    if env_password:
        return env_password.strip()

    say("Pega la contrasena de la base de datos (no se muestra al escribir).")
    say("Te la tiene que dar el administrador del proyecto.")
    while True:
        first = getpass.getpass("  Contrasena: ").strip()
        if not first:
            say("  La contrasena no puede estar vacia. Intenta otra vez.")
            continue
        second = getpass.getpass("  Repitela:   ").strip()
        if first != second:
            say("  No coinciden. Intenta otra vez.")
            continue
        return first


def env_value(value: str) -> str:
    """Entrecomilla el valor si python-dotenv lo necesitara."""
    if any(ch in value for ch in ' #"\''):
        return '"' + value.replace('"', '\\"') + '"'
    return value


def read_existing_password() -> str | None:
    if not ENV_FILE.exists():
        return None
    for line in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line.startswith("DJANGO_DB_PASSWORD="):
            value = line.split("=", 1)[1].strip()
            if value:
                return value
    return None


def confirm_overwrite() -> bool:
    say(f"Ya existe {ENV_FILE.name} en esta carpeta.")
    answer = input("  Sobrescribirlo? [s/N]: ").strip().lower()
    return answer in {"s", "si", "sí", "y", "yes"}


def write_env(password: str) -> None:
    content = f"""# Archivo de configuracion local. NO se sube al repositorio.
# Generado por scripts/setup_env.py

DJANGO_SECRET_KEY={secrets.token_urlsafe(50)}
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,[::1]

# Base de datos del equipo en Amazon RDS.
DJANGO_DB_ENGINE=mysql
DJANGO_DB_NAME={DB_NAME}
DJANGO_DB_HOST={DB_HOST}
DJANGO_DB_PORT={DB_PORT}
DJANGO_DB_USER={DB_USER}
DJANGO_DB_PASSWORD={env_value(password)}
DJANGO_DB_SSL_CA={CA_REL}
"""
    with open(ENV_FILE, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass
    say(f"  Creado {ENV_FILE}")


def public_ip() -> str | None:
    try:
        with urllib.request.urlopen("https://checkip.amazonaws.com", timeout=6) as response:
            value = response.read().decode("ascii", "ignore").strip()
            return value or None
    except Exception:
        return None


def check_connection() -> None:
    say("\nComprobando la conexion con la base de datos...")

    if not (ROOT / CA_REL).exists():
        say(f"  Aviso: falta {CA_REL}. La conexion TLS no podra verificarse.")

    code = CHECK_CODE.format(root=str(ROOT))
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=35,
        )
    except subprocess.TimeoutExpired:
        explain_timeout()
        return

    output = (result.stdout or "") + (result.stderr or "")

    if "RESULT_OK" in output:
        count = output.split("RESULT_OK", 1)[1].split()[0]
        say("  Conexion correcta.")
        say(f"  La base responde y tiene {count} juegos cargados.")
        say("\nYa puedes arrancar la app:  python manage.py runserver")
        return

    if "RESULT_NODEP" in output:
        missing = output.split("RESULT_NODEP", 1)[1].strip().splitlines()[0]
        say(f"  Todavia no estan instaladas las dependencias (falta '{missing}').")
        say("  Instalalas y este script volvera a probar:")
        say("    python -m pip install -r requirements.txt")
        return

    detail = output.split("RESULT_FAIL", 1)[1].strip() if "RESULT_FAIL" in output else output

    if "1045" in detail or "Access denied" in detail:
        say("  La base rechaza la contrasena (error 1045).")
        say("  Vuelve a ejecutar este script y pega la contrasena exacta,")
        say("  sin espacios ni comillas.")
        return

    if "1049" in detail or "Unknown database" in detail:
        say("  La base de datos 'indievault' no existe en el servidor.")
        say("  Avisa al administrador del proyecto.")
        return

    if any(token in detail for token in ("2003", "2002", "timed out", "timeout", "10060")):
        explain_timeout()
        return

    if "certificate" in detail.lower() or "ssl" in detail.lower():
        say("  El certificado TLS no valida. Comprueba que existe")
        say(f"  {CA_REL} y que el .env apunta a el.")
        say(f"  Detalle: {detail}")
        return

    say("  No pude conectar con la base.")
    say(f"  Detalle: {detail}")


def explain_timeout() -> None:
    say("  No hay respuesta del servidor de base de datos.")
    say("  Las causas habituales, por orden:")
    say("    1. El administrador tiene AWS apagado o RDS arrancando (5-10 min).")
    say("    2. Tu IP publica no esta autorizada en el security group.")
    ip = public_ip()
    if ip:
        say(f"\n  Tu IP publica ahora es: {ip}")
        say("  Enviasela al administrador para que la autorice.")
    say("\n  Cuando la autorice, vuelve a probar con:")
    say("    python manage.py runserver")


def main() -> None:
    say("=" * 62)
    say("  IndieVault - configuracion de la base de datos del equipo")
    say("=" * 62)

    if not (ROOT / "manage.py").exists():
        fail("no encuentro manage.py. Ejecuta el script desde el repositorio.")

    if ENV_FILE.exists():
        if confirm_overwrite():
            write_env(ask_password())
        else:
            say("  Se mantiene el .env actual.")
    else:
        write_env(ask_password())

    check_connection()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        say("\nCancelado.")
        sys.exit(1)
