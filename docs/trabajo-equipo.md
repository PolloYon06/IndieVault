# Trabajo en equipo con la base de datos en AWS

La base de datos vive en **Amazon RDS (MySQL 8.4)** y es compartida por todo el
equipo. Cada integrante ejecuta Django en su PC y se conecta a RDS por Internet
con TLS. No hace falta instalar MariaDB ni MySQL local.

El administrador del proyecto habilita en AWS el acceso público de RDS y
autoriza la IP de cada integrante en el security group. Si tu IP no está
autorizada, la conexión dará timeout aunque el `.env` sea correcto.

## Requisitos

- Python 3.12 o superior.
- Git.
- La contraseña de la base de datos, que te da el administrador del proyecto.
- No hace falta instalar MySQL ni MariaDB.

## Puesta en marcha

```bash
git clone https://github.com/PolloYon06/IndieVault.git
cd IndieVault
```

Después ejecuta el instalador:

- **Windows:** doble clic en `scripts\instalar.bat`
- **macOS / Linux:** `./scripts/instalar.sh`

El instalador crea el entorno virtual `indieEnv`, instala las dependencias y
genera el `.env` con el endpoint de RDS, el usuario `indievault_app` y el
certificado TLS. Solo te pide la contraseña de la base.

Al terminar, arranca la app:

```bash
# Windows
indieEnv\Scripts\activate
# macOS / Linux
source indieEnv/bin/activate

python manage.py runserver
```

La app queda en `http://127.0.0.1:8000/`. No hay que crear ni editar el `.env`
a mano: eso es lo que provoca el error `(2002, "Can't connect to server on
'127.0.0.1' (10061)")`.

Si más adelante cambia alguna dependencia:

```bash
pip install -r requirements.txt
```

## Base de datos

El `.env` del equipo apunta a:

```text
Host: database-1.cvv8xc2ptzxa.us-east-1.rds.amazonaws.com
Puerto: 3306
Base: indievault
Usuario: indievault_app
TLS: certificado en certs/global-bundle.pem
```

La conexión usa el certificado CA incluido en `certs/global-bundle.pem`. No
desactives la verificación TLS.

Si al probar la conexión el endpoint resuelve a una IP `172.31...` o da
timeout, el acceso público de RDS todavía no está activo o falta tu IP en el
security group. Pídele al administrador que lo habilite.

### Migraciones

La base ya está migrada. Cuando alguien cambie modelos:

```bash
python manage.py makemigrations
python manage.py migrate
git add IndieVault/migrations/
git commit -m "Agrega migración de ..."
git push
```

Avisa al equipo antes de aplicar migraciones para evitar que dos personas
generen migraciones incompatibles al mismo tiempo.

### Qué no hacer

- No ejecutes `flush`, `drop`, `reset` ni borres tablas: la base es compartida.
- No subas `.env` a Git.
- No cambies `DJANGO_DB_HOST` al endpoint privado de RDS: usa el endpoint
  público que viene en el `.env`.
- No uses el usuario `admin` de RDS para la app.

## Problemas de conexión

Primero identifica el mensaje exacto:

| Mensaje | Causa | Solución |
|---|---|---|
| `Can't connect to server on '127.0.0.1' (10061)` | No hay `.env`, o está mal nombrado (`\.env.txt`) | Ejecuta otra vez el instalador |
| `Can't connect ... (10060)` o timeout con el endpoint de RDS | Tu IP no está autorizada, o RDS está apagado | Envía tu IP al administrador |
| `Access denied for user` (1045) | Contraseña incorrecta | Ejecuta el instalador y pega la contraseña exacta |
| `Unknown database` (1049) | Falta la base | Avisa al administrador |

Si aparece `Can't connect to MySQL server` o un timeout:

1. Comprueba tu IP pública:

   ```bash
   curl -s https://checkip.amazonaws.com
   ```

2. Envíale esa IP al administrador. El security group de RDS solo permite las
   IPs del equipo; si cambiaste de red, hay que agregar la nueva.
3. Verifica que el `.env` tenga el host público, el puerto `3306` y el usuario
   `indievault_app`.

Si aparece `Access denied`, revisa que copiaste la contraseña completa del
`.env` compartido, sin espacios ni comillas adicionales.

## Flujo de Git

```bash
git pull --rebase
git checkout -b mi-cambio
# trabajar
git add ...
git commit -m "Describe el cambio"
git push -u origin mi-cambio
```

Luego se abre un Pull Request en GitHub. No se hace `push` directo a `main`
si hay cambios grandes o migraciones.

## App publicada

Para probar sin instalar nada:

```text
http://184.193.197.193/
```

La app de la nube usa la misma base RDS.
