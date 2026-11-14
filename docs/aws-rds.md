# IndieVault en AWS: base de datos RDS + app en EC2

Documento de constancia técnica del traslado de la base de datos a AWS y del
despliegue de la aplicación. Actualizado el **14 de noviembre de 2026**.

> Este archivo no contiene contraseñas ni claves. Solo indica dónde están
> guardadas y con qué permisos.

---

## 1. Resumen

| Elemento | Estado |
|---|---|
| Base de datos en AWS (RDS MySQL) | Migrada y verificada |
| Datos (juegos, usuarios, biblioteca) | Idénticos a la base local original |
| App desplegada en la EC2 | Gunicorn + Nginx, accesible por HTTP |
| Acceso de los PCs del equipo a RDS | Directo por Internet, con TLS y allowlist de IPs |
| Repositorio GitHub | `main` |

La base de datos vive en RDS. La EC2 la usa por la red privada de la VPC y cada
integrante del equipo se conecta por Internet desde su PC, con TLS y con su IP
pública autorizada en el security group de RDS.

---

## 2. Arquitectura actual

```
        PC de cada integrante del equipo
          Django :8000  ──────────────┐
                                      │  MySQL :3306 + TLS (VERIFY_IDENTITY)
                                      │  security group: IP /32 por persona
                                      v
        +--------------------------------------------+
        |  RDS MySQL 8.4.11   database-1             |
        |  database-1.cvv8xc2ptzxa.us-east-1...      |
        |  Base: indievault                          |
        |  Acceso público: sí                        |
        |  sg-indievault-rds-sg (allowlist)          |
        +----------------------▲---------------------+
                               │ MySQL :3306 + TLS
                               │ red privada de la VPC
                               │ rds-ec2-1 (EC2 security group)
                               │
        Internet               │
           │ HTTP :80 (abierto)│
           v                   │
        +--------------------------------------------+
        |  EC2 184.193.197.193                       |
        |  i-0d95808ff553971c4 (t3.micro)            |
        |  Nginx :80  ->  Gunicorn :8000             |
        |  /home/ubuntu/IndieVault1                  |
        |  venv: indieEnv                            |
        +--------------------------------------------+
```

Dos caminos distintos, con dos security groups distintos:

- **EC2 → RDS**: por la red privada de la VPC. Lo permite `rds-ec2-1`, que
  autoriza el security group de la EC2 como origen.
- **PCs del equipo → RDS**: por Internet. Lo permite `indievault-rds-sg`, que
  autoriza una IP `/32` por persona.

La EC2 nunca se usa como puerta de entrada para los desarrolladores. Esa era la
arquitectura anterior (túnel SSH) y se descartó por comodidad; sigue disponible
como alternativa en la sección 6.

---

## 3. Base de datos (RDS)

| Dato | Valor |
|---|---|
| Identificador | `database-1` |
| Motor | MySQL Community 8.4.11 |
| Clase | `db.t4g.micro` |
| Región / AZ | `us-east-1` / `us-east-1d` |
| Endpoint | `database-1.cvv8xc2ptzxa.us-east-1.rds.amazonaws.com` |
| Puerto | `3306` |
| Base | `indievault` (`utf8mb4_unicode_ci`) |
| Usuario master | `admin` (solo administración; la app no lo usa) |
| Acceso público | **Sí** — el endpoint resuelve a una IP pública de AWS |
| Security groups | `indievault-rds-sg` (`sg-098fc11aefc930f20`), `rds-ec2-1` (`sg-0094e1692b8569827`) |
| Certificate authority | `rds-ca-rsa2048-g1` |
| Backups automáticos | Activados, retención 7 días |
| Route table de sus subredes | `rtb-034e43953211cbe41`: `172.31.0.0/16 local` + `0.0.0.0/0 → igw-0192d8e2ffb39b1e0` |

### Usuario de aplicación

| Dato | Valor |
|---|---|
| Usuario | `indievault_app` |
| Host permitido | `%` (`CURRENT_USER()` = `indievault_app@%`) |
| Permisos | `SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP, REFERENCES, CREATE TEMPORARY TABLES, LOCK TABLES` sobre `indievault.*` |
| Cifrado | TLS con el CA oficial de AWS (`certs/global-bundle.pem`) |

`require_secure_transport` está en `OFF`: el servidor no obliga a TLS, pero la
app lo usa porque el `.env` define `DJANGO_DB_SSL_CA`. Si se activa, cualquier
cliente sin TLS dejará de conectar.

### Security group de acceso público

`indievault-rds-sg` solo debe contener reglas `3306/tcp` con IPs `/32`:

| Tipo | Puerto | Origen |
|---|---|---|
| MySQL/Aurora | 3306 | IP pública `/32` de cada integrante |

Reglas:

- **Nunca `0.0.0.0/0`.**
- Cada integrante comprueba su IP con `curl -s https://checkip.amazonaws.com`
  y se la pasa al administrador.
- Si alguien cambia de red, su IP cambia y hay que actualizar su regla.
- Si el grupo tiene más de una regla amplia, revisar cuál sobra: las reglas de
  todos los security groups asociados a la instancia se **suman**, no se
  restringen entre sí.

### Verificación de la migración

Los conteos coinciden exactamente entre la base local original y RDS:

| Tabla | Registros |
|---|---|
| `IndieVault_game` | 51.408 |
| `auth_user` | 3 |
| `IndieVault_libraryentry` | 3 |
| `IndieVault_enterprise` | 1 |
| `django_migrations` | 24 |

Además se copiaron tablas antiguas vacías del modelo original
(`JUEGO`, `GENERO`, `Usuario`, `COMPRA`, `DESARROLLADOR`, `JUEGO_GENERO`).
Son inofensivas y no las usa Django.

### Procedimiento usado

1. Dump local con `mariadb-dump --single-transaction --quick --no-tablespaces
   --default-character-set=utf8mb4` (6,9 MB).
2. Copia del dump a la EC2 por `scp`.
3. Creación de la base `indievault` en RDS.
4. Importación con el cliente `mysql` de la EC2 usando el endpoint y SSL con
   `global-bundle.pem`.
5. Verificación de conteos tabla por tabla.
6. Creación del usuario `indievault_app` y prueba de conexión con SSL.

---

## 4. Instancia EC2

| Dato | Valor |
|---|---|
| Nombre | `MySql67` |
| ID | `i-0d95808ff553971c4` |
| Tipo | `t3.micro` |
| IP pública | `184.193.197.193` |
| DNS público | `ec2-184-193-197-193.compute-1.amazonaws.com` |
| Elastic IP | Sí: `184.193.197.193` (la IP se mantiene al detener/arrancar) |
| SO | Ubuntu 26.04.1 LTS |
| Usuario SSH | `ubuntu` |
| Security groups | `launch-wizard-1`, `ec2-rds-1` |

### Cambios hechos en la EC2

- **MariaDB local detenido y deshabilitado** (`systemctl disable --now mysql`).
  Ya no se usa: la base está en RDS. Esto libera ~490 MB de RAM.
- **Swap de 1 GB** añadido en `/swapfile`, persistente en `/etc/fstab`, para
  que el `t3.micro` (908 MB de RAM) no sufra con Gunicorn.
- Paquetes instalados: `python3-venv`, `python3-dev`,
  `default-libmysqlclient-dev`, `build-essential`, `pkg-config`, `nginx`.

---

## 5. Despliegue de la aplicación en la EC2

| Elemento | Ruta / valor |
|---|---|
| Proyecto | `/home/ubuntu/IndieVault1` |
| Entorno virtual | `/home/ubuntu/IndieVault1/indieEnv` |
| Variables de entorno | `/home/ubuntu/IndieVault1/.env` (permisos `600`) |
| Certificado CA de RDS | `/home/ubuntu/IndieVault1/certs/global-bundle.pem` |
| Estáticos | `/var/www/indievault/staticfiles` |
| Servicio Gunicorn | `indievault.service` (habilitado) |
| Nginx | `nginx.service` (habilitado) |

### Servicio Gunicorn

```
ExecStart=/home/ubuntu/IndieVault1/indieEnv/bin/gunicorn \
  --workers 2 --bind 127.0.0.1:8000 \
  --access-logfile - --error-logfile - \
  ProyectoIndieVault.wsgi:application
Usuario: ubuntu | Grupo: www-data | Restart: always
```

### Nginx

- Escucha en `:80`.
- Sirve `/static/` desde `/var/www/indievault/staticfiles/`.
- Hace proxy del resto a `127.0.0.1:8000`.

### Configuración de Django en producción

Variables definidas en `.env`:

| Variable | Valor |
|---|---|
| `DJANGO_DEBUG` | `False` |
| `DJANGO_SECRET_KEY` | Aleatoria, generada en la EC2 |
| `DJANGO_ALLOWED_HOSTS` | IP pública, DNS público, localhost |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `http://` + IP y DNS públicos |
| `DJANGO_DB_HOST` | Endpoint de RDS |
| `DJANGO_DB_PORT` | `3306` |
| `DJANGO_DB_NAME` | `indievault` |
| `DJANGO_DB_USER` | `indievault_app` |
| `DJANGO_DB_SSL_CA` | `certs/global-bundle.pem` |
| `DJANGO_STATIC_ROOT` | `/var/www/indievault/staticfiles` |

### Acceso público

- **http://184.193.197.193/**
- Cuentas de prueba: `admin` / `admin123`, `demo` / `demo1234`,
  `estudio` / `estudio1234`.
- Probado desde Internet: portada, explorar, login, suscripción, estáticos,
  panel, biblioteca y estadísticas responden correctamente.

> Nota: estas contraseñas son de cuentas de prueba y están visibles en el
> repositorio. Para un entorno real deben cambiarse.

---

## 6. Acceso desde los PCs del equipo

### Opción principal: conexión directa (RDS pública)

Cada integrante guarda el `.env` que le comparte el administrador en la raíz del
proyecto, junto a `manage.py`, y ejecuta:

```bash
python manage.py runserver
```

Variables relevantes:

```text
DJANGO_DB_HOST=database-1.cvv8xc2ptzxa.us-east-1.rds.amazonaws.com
DJANGO_DB_PORT=3306
DJANGO_DB_NAME=indievault
DJANGO_DB_USER=indievault_app
DJANGO_DB_SSL_CA=certs/global-bundle.pem
```

No hace falta AWS CLI, ni clave SSH, ni túnel, ni MariaDB local. Lo único que
necesita el equipo es que el administrador tenga RDS encendida y que la IP
pública de cada persona esté autorizada en `indievault-rds-sg`.

Comprobar el camino antes de culpar al código:

```bash
getent hosts database-1.cvv8xc2ptzxa.us-east-1.rds.amazonaws.com   # IP pública
timeout 8 bash -c '</dev/tcp/database-1.cvv8xc2ptzxa.us-east-1.rds.amazonaws.com/3306' \
  && echo "puerto abierto" || echo "puerto cerrado o filtrado"
```

- Si el host resuelve a `172.31...`, el acceso público no está activo.
- Si el puerto no responde, la IP de esa persona no está autorizada (o el
  problema de routing descrito en la sección 10).

### Alternativa: túnel SSH por la EC2

Para desarrollo sin abrir RDS a Internet, o para depurar cuando la conexión
directa falla:

```bash
ssh -N -L 127.0.0.1:3307:database-1.cvv8xc2ptzxa.us-east-1.rds.amazonaws.com:3306 \
    ubuntu@184.193.197.193
```

Y en el `.env`:

```text
DJANGO_DB_HOST=127.0.0.1
DJANGO_DB_PORT=3307
```

Este túnel lo usa el administrador con su clave `~/.ssh/indievault-aws.pem`.
**La clave privada no se comparte.** Si un integrante necesita el túnel, se le
genera su propio par de claves y se autoriza su clave pública en la EC2.

### Archivos locales del administrador (fuera del repositorio)

| Archivo | Contenido | Permisos |
|---|---|---|
| `~/.ssh/indievault-aws.pem` | Clave privada de la EC2 | `600` |
| `~/.indievault-local.env` | Variables de Django para el modo túnel | `600` |
| `~/.config/indievault/config` | IDs de EC2/RDS y rutas (sin secretos) | `600` |
| `~/indievault-equipo.env` | `.env` que se comparte con el equipo | `600` |

### Cómo comprobar que se está usando AWS y no una base local

```sql
SELECT CURRENT_USER(), USER(), DATABASE(), VERSION();
```

- En RDS: `CURRENT_USER()` = `indievault_app@%`, `VERSION()` = `8.4.11`.
- Una base local respondería `13.0.2-MariaDB` y un usuario `@localhost`.

---

## 7. Cambios de código (commit `caebad9`)

Archivos modificados y subidos a GitHub en `main`:

### `ProyectoIndieVault/settings.py`

- Soporte de certificado CA de RDS mediante `DJANGO_DB_SSL_CA`. Si la ruta es
  relativa, se resuelve contra `BASE_DIR`, así que
  `certs/global-bundle.pem` funciona desde cualquier directorio.
- `STATIC_ROOT` configurable con `DJANGO_STATIC_ROOT`
  (por defecto `BASE_DIR / 'staticfiles'`).
- `CSRF_TRUSTED_ORIGINS` configurable con `DJANGO_CSRF_TRUSTED_ORIGINS`.

### `.env.example`

- Documenta el endpoint público de RDS, el usuario `indievault_app`, el puerto
  `3306` y el CA de `certs/global-bundle.pem`.
- Ya no sugiere `127.0.0.1` ni el usuario `indievault` para el modo equipo.

---

## 8. Seguridad

| Tarea | Dónde | Estado |
|---|---|---|
| Allowlist de IPs `/32` en `indievault-rds-sg` | Consola AWS | Activo; mantener al día |
| Revisar que ningún SG asociado permita `0.0.0.0/0` en 3306 | Consola AWS | Verificado el 14 nov |
| Restringir el puerto 22 de `launch-wizard-1` a la IP del administrador | Consola AWS | Recomendado |
| HTTPS con Certbot cuando exista dominio | EC2 | Futuro |
| Cambiar contraseñas de las cuentas de prueba | App | Antes de producción |
| Separar usuario de app (`DML`) y de migraciones (`DDL`) | RDS | Opcional |

Notas:

- El riesgo real de RDS pública no es la fuerza bruta: es una regla demasiado
  amplia o un `.env` filtrado. Con IPs `/32`, contraseña fuerte, TLS y datos de
  prueba, el riesgo es bajo y aceptable para un proyecto universitario.
- Si alguien sale del equipo o pierde el portátil: rotar la contraseña de
  `indievault_app` y eliminar su regla del security group.
- No meter datos personales reales en la base compartida.

---

## 9. Operación

### Ver estado de los servicios (EC2)

```bash
systemctl is-active indievault nginx
sudo journalctl -u indievault -n 50 --no-pager
```

### Reiniciar la app

```bash
sudo systemctl restart indievault
```

### Desplegar cambios de código

En el equipo del administrador:

```bash
indievault deploy
```

Equivale a sincronizar con `rsync`, instalar dependencias, migrar, recolectar
estáticos y reiniciar el servicio. Manualmente:

```bash
rsync -az -e "ssh -i ~/.ssh/indievault-aws.pem" \
  --exclude '.git/' --exclude 'indieEnv/' --exclude '.env' \
  --exclude 'staticfiles/' --exclude '__pycache__/' \
  ./ ubuntu@184.193.197.193:/home/ubuntu/IndieVault1/
ssh -i ~/.ssh/indievault-aws.pem ubuntu@184.193.197.193 \
  'cd /home/ubuntu/IndieVault1 && ./indieEnv/bin/python manage.py migrate --noinput \
   && ./indieEnv/bin/python manage.py collectstatic --noinput \
   && sudo systemctl restart indievault'
```

### Encendido y apagado

```bash
indievault          # enciende EC2 y RDS, arranca servicios y Django local
indievault status   # estado de EC2, RDS, app local y túnel
indievault down     # detiene EC2 y RDS
```

También se puede apagar desde la consola de AWS. Al arrancar RDS desde
`stopped` hay que esperar 5–10 minutos. AWS reinicia sola una instancia
detenida después de 7 días.

### Copias de seguridad de la base

Los backups automáticos de RDS cubren 7 días. Para un respaldo manual:

```bash
mysqldump -h <endpoint> -u indievault_app -p \
  --single-transaction --no-tablespaces \
  --set-gtid-purged=OFF indievault > indievault-$(date +%F).sql
```

### Coordinación del equipo

- Solo el administrador aplica migraciones a la base compartida.
- Nadie ejecuta `flush`, `drop` ni borra tablas.
- Avisar antes de un cambio de modelos o de esquema.
- Snapshot manual en RDS antes de cambios grandes.

---

## 10. Limitaciones conocidas

- **La EC2 usa Elastic IP** (`184.193.197.193`), así que la dirección se
  mantiene al detener y arrancar la instancia.
- **RDS pública requiere que la subred tenga salida a Internet.** AWS asigna
  una IP pública a la instancia, pero si las subredes de su *DB subnet group*
  no tienen una ruta `0.0.0.0/0` hacia el internet gateway (o una NACL las
  bloquea), el puerto 3306 no responde desde fuera aunque el security group sea
  correcto. Señal típica: el endpoint resuelve a IP pública, la regla `/32` está
  puesta y aun así hay timeout, incluso desde la propia EC2 hacia el IP público.
  **Ocurrió en este proyecto y se corrigió el 14 nov**: las subredes de RDS
  usaban `rtb-034e43953211cbe41`, que solo tenía la ruta local. Se añadió
  `0.0.0.0/0 → igw-0192d8e2ffb39b1e0`. Comprobación: VPC → Subnets → subred de
  RDS → Route table.
- **Las IPs de los integrantes cambian** al cambiar de red. Cada vez que alguien
  reporte timeout, lo primero es comparar su IP actual con la regla del
  security group.
- **WiFi compartida o CGNAT**: la IP pública puede ser compartida con más
  gente, así que la allowlist protege menos. En ese caso, usar el túnel SSH.
- **`t3.micro` con 908 MB de RAM.** Gunicorn corre con 2 workers y hay 1 GB de
  swap. Suficiente para pruebas, justo para producción con tráfico.
- **HTTP sin TLS en la web pública.** Las contraseñas viajan sin cifrar hasta
  que se configure HTTPS.
- **Un solo usuario de base para todo el equipo.** No hay auditoría por persona
  ni separación de permisos.
- **Coste.** La EC2 y RDS consumen crédito mientras están encendidas.

---

## 11. Historial

| Fecha (2026) | Hecho |
|---|---|
| 10 nov | Dump local y migración a RDS `database-1` |
| 10 nov | Creación de `indievault_app` y verificación con SSL |
| 10 nov | Despliegue de la app en la EC2 (Gunicorn + Nginx) |
| 10 nov | Retirada del despliegue extra y vuelta a "solo base de datos" |
| 10 nov | Recreación del venv local tras actualizar a Python 3.14 |
| 10 nov | App local conectada a RDS mediante túnel SSH |
| 10 nov | Nuevo despliegue de la app en la EC2 (estado actual) |
| 10 nov | Commit `caebad9` subido a `main` |
| 14 nov | RDS pasa a acceso público; allowlist de IPs en `indievault-rds-sg` |
| 14 nov | `.env.example` corregido y este documento actualizado al modelo público |
| 14 nov | Automatización `indievault` (arranque, estado, despliegue, apagado) |
| 14 nov | Corregido el routing: ruta `0.0.0.0/0 → igw` en las subredes de RDS; conexión pública verificada con TLS |
