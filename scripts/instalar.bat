@echo off
rem Instalador de IndieVault para Windows.
rem Crea el entorno virtual, instala las dependencias y configura el .env.
setlocal
cd /d "%~dp0.."

echo ============================================================
echo   IndieVault - instalacion
echo ============================================================
echo.

if not exist manage.py (
    echo [ERROR] No encuentro manage.py.
    echo Ejecuta este archivo desde la carpeta del repositorio IndieVault.
    echo.
    pause
    exit /b 1
)

set "PY=python"
%PY% --version >nul 2>nul
if errorlevel 1 (
    py -3 --version >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] No encuentro Python.
        echo Descargalo de https://www.python.org/downloads/ e instala la version 3.12 o superior.
        echo Importante: marca la casilla "Add python.exe to PATH" durante la instalacion.
        echo.
        pause
        exit /b 1
    )
    set "PY=py -3"
)

if not exist indieEnv (
    echo [1/3] Creando el entorno virtual...
    %PY% -m venv indieEnv
    if errorlevel 1 goto error
) else (
    echo [1/3] El entorno virtual ya existe, se reutiliza.
)

echo [2/3] Instalando las dependencias...
"indieEnv\Scripts\python.exe" -m pip install --upgrade pip --quiet
"indieEnv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto error

echo [3/3] Configurando el archivo .env...
"indieEnv\Scripts\python.exe" scripts\setup_env.py
if errorlevel 1 goto error

echo.
echo ============================================================
echo   Listo. Para arrancar la app:
echo.
echo     indieEnv\Scripts\activate
echo     python manage.py runserver
echo.
echo   Y abre http://127.0.0.1:8000/ en el navegador.
echo ============================================================
echo.
pause
exit /b 0

:error
echo.
echo ============================================================
echo   Algo fallo. Copia todo este texto y mandaselo a tu companero.
echo ============================================================
echo.
pause
exit /b 1
