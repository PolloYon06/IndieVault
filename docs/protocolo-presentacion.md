# Protocolo Técnico y Guion de Contingencia — Día D (IndieVault)

Guía operativa accionable para asegurar una demostración fluida de **IndieVault**, tanto sobre la infraestructura principal en **AWS (EC2 + RDS MySQL)** como mediante conmutación inmediata a **SQLite local** ante cualquier corte de red en el aula.

> Este documento no contiene claves reales. Sustituye `<ClaveDemo>` por la contraseña definida para la sesión (por ejemplo, `ClaveDemo-2026!` en entorno local de prueba).

---

## 1. Checklist 30 minutos antes de presentar

Ejecutar en orden antes de conectar el proyector:

- [ ] **1.1. Definir modalidad de red y verificar AWS (si se presenta online):**
  - Comprobar que la instancia EC2 responde en `http://184.193.197.193/` (Nginx + Gunicorn activos).
  - Si se ejecutará Django local contra **Amazon RDS** (`database-1.cvv8xc2ptzxa.us-east-1.rds.amazonaws.com:3306`), verificar la IP pública de la red del aula:
    ```bash
    curl -s https://checkip.amazonaws.com
    ```
    Confirmar en el security group `indievault-rds-sg` que esa IP `/32` está autorizada (o comprobar estado general desde el equipo administrador con `indievault status`).
- [ ] **1.2. Sembrar o refrescar los datos de demostración (si aún no están cargados):**
  - Genera los usuarios ficticios (`demo_`), la cuenta jugador `demo_presentacion`, el estudio verificado `demo_estudio` (`[DEMO] Aurora Indie` con sus 3 juegos `[DEMO] Ecos del Sur`, `[DEMO] Cripta Solar` y `[DEMO] Marea de Cristal`) y los hilos de comunidad:
    ```bash
    ./indieEnv/bin/python manage.py seed_demo --clean --password ClaveDemo-2026!
    ```
- [ ] **1.3. Ejecutar la auditoría automática `verify_demo_readiness` en modo estricto:**
  - Valida motor de base de datos, catálogo, contraseñas de `demo_presentacion` y `demo_estudio`, estudio verificado, cuenta `staff`, actividad de comunidad y tiempos de respuesta HTTP (`200`) en las 10 rutas críticas:
    ```bash
    ./indieEnv/bin/python manage.py verify_demo_readiness --password ClaveDemo-2026! --strict
    ```
- [ ] **1.4. Dejar precalentado el Plan B local (SQLite) en segundo plano (sin arrancarlo aún):**
  - Ejecutar una vez la preparación de la sección 2 (pasos 1 a 4) para que `db.sqlite3` ya quede migrada y sembrada en disco antes de empezar.
- [ ] **1.5. Puesta a punto de pantalla:**
  - Activar **No molestar** en el sistema operativo, ajustar el zoom del navegador a **100%–110%** y abrir los **3 contextos aislados de navegador** (sección 3).

---

## 2. Plan B Offline en 5 segundos (Fallback SQLite local)

**Cuándo activarlo:** si cae el Wi-Fi del aula, la red bloquea el puerto `3306`, cambia la IP pública provocando *timeout* hacia RDS o la EC2 no responde.  
**Regla de oro:** no editar `.env` ni depurar red en vivo; `DJANGO_DB_ENGINE=sqlite` conmuta inmediatamente a `db.sqlite3` local.

### Paso a paso completo (preparación desde cero)

1. **Aplicar migraciones sobre SQLite local:**
   ```bash
   DJANGO_DB_ENGINE=sqlite ./indieEnv/bin/python manage.py migrate --noinput
   ```

2. **Crear o asegurar el administrador (`staff`) local de forma idempotente:**
   ```bash
   DJANGO_DB_ENGINE=sqlite ./indieEnv/bin/python manage.py shell -c "from django.contrib.auth import get_user_model; User = get_user_model(); u, _ = User.objects.get_or_create(username='admin_local', defaults={'email': 'admin@indievault.local'}); u.is_staff = True; u.is_superuser = True; u.is_active = True; u.set_password('ClaveDemo-2026!'); u.save(); print('Admin listo:', u.username)"
   ```

3. **Sembrar cuentas, biblioteca, estudio `[DEMO] Aurora Indie` y comunidad:**
   ```bash
   DJANGO_DB_ENGINE=sqlite ./indieEnv/bin/python manage.py seed_demo --clean --password ClaveDemo-2026!
   ```

4. **Verificar integridad completa y smoke test HTTP (`--strict`):**
   ```bash
   DJANGO_DB_ENGINE=sqlite ./indieEnv/bin/python manage.py verify_demo_readiness --password ClaveDemo-2026! --strict
   ```

5. **Levantar el servidor local de contingencia:**
   ```bash
   DJANGO_DB_ENGINE=sqlite ./indieEnv/bin/python manage.py runserver 127.0.0.1:8000
   ```

### Arranque instantáneo en vivo (si `db.sqlite3` ya se dejó precalentada en el checklist)

Si el corte ocurre a mitad de la presentación, abrir terminal en la raíz del repositorio y ejecutar únicamente:

```bash
DJANGO_DB_ENGINE=sqlite ./indieEnv/bin/python manage.py runserver 127.0.0.1:8000
```

Cambiar la base de las pestañas a `http://127.0.0.1:8000/` y continuar desde el minuto exacto del guion.

---

## 3. Preparación de ventanas del navegador (3 contextos aislados)

Para **no perder tiempo cerrando e iniciando sesión en vivo**, mantener abiertas 3 instancias con cookies independientes antes de comenzar (sustituir `http://127.0.0.1:8000` por `http://184.193.197.193` si se proyecta contra EC2):

| Contexto de navegador | Rol | Usuario | URL de acceso previo | Pestañas listas para mostrar |
|---|---|---|---|---|
| **1. Ventana normal (Perfil 1)** | Jugador | `demo_presentacion` | `http://127.0.0.1:8000/login/` | `/` · `/explorar/` · `/explorar/catalogo/` · `/buscar/` · `/comunidad/` · `/estadisticas/` · `/biblioteca/` |
| **2. Ventana privada / Perfil 2** | Estudio verificado (`[DEMO] Aurora Indie`) | `demo_estudio` | `http://127.0.0.1:8000/empresa/login/` | `/empresa/` · `/empresa/publicar/` · `/juego/demo-ecos-del-sur/` |
| **3. Perfil 3 / Segundo navegador** | Administrador (`is_staff=True`) | `admin` (RDS/EC2) o `admin_local` (SQLite) | `http://127.0.0.1:8000/login/` *(redirige solo a `/panel/`)* | `/panel/` · `/panel/empresas/` · `/panel/juegos/` · `/panel/estadisticas/` |

> Si alguna cuenta demo perdió su clave o se sembró sin `--password`, repararla en 1 segundo sin recrear datos:
> ```bash
> DJANGO_DB_ENGINE=sqlite ./indieEnv/bin/python manage.py verify_demo_readiness --fix-passwords --password ClaveDemo-2026! --strict
> ```

---

## 4. Guion cronometrado de presentación (10–12 minutos)

### Min 0–2 · Inicio, Explorar y Buscador Global
- **Contexto:** Ventana 1 (`demo_presentacion`).
- **Recorrido de URLs:** `/` → `/explorar/` → `/explorar/catalogo/` → `/buscar/`.
- **Acciones en vivo:**
  1. Mostrar la portada (`/`) con el resumen rápido de actividad del jugador autenticado.
  2. Entrar a **Explorar** (`/explorar/`), mostrar colecciones curadas y pasar al catálogo paginado (`/explorar/catalogo/`).
  3. Activar el filtro **"Publicados en IndieVault"** para distinguir los lanzamientos publicados directamente por estudios verificados de la plataforma frente al catálogo general importado.
  4. Abrir el **Buscador Global** (`/buscar/`) y buscar `"Aurora"` o `"Ecos del Sur"` para demostrar resultados unificados de juegos, estudios y conversaciones de comunidad.

### Min 2–5 · Ficha de Juego, Reseñas y Comunidad Oficial
- **Contexto:** Ventana 1 (`demo_presentacion`) + breve apoyo en Ventana 2 (`demo_estudio`).
- **Recorrido de URLs:** `/juego/demo-ecos-del-sur/` → `/comunidad/` → `/comunidad/<id>/`.
- **Acciones en vivo:**
  1. Abrir la ficha de **`[DEMO] Ecos del Sur`** (`/juego/demo-ecos-del-sur/`): destacar portada/identidad visual, géneros, estudio editor vinculado, bloque de **valoraciones y reseñas** y vista previa de hilos activos del juego.
  2. Entrar a un hilo de discusión del juego (`/comunidad/<id>/`) y señalar la respuesta de `demo_estudio` identificada con la insignia **`✓ Desarrollador oficial`**.
  3. Mostrar el sistema de **notificaciones internas** cuando otro usuario o el estudio oficial responde en un hilo seguido/creado por el jugador.

### Min 5–7 · Dashboard del Jugador y Biblioteca Personal
- **Contexto:** Ventana 1 (`demo_presentacion`).
- **Recorrido de URLs:** `/estadisticas/` → `/biblioteca/`.
- **Acciones en vivo:**
  1. En **Estadísticas del jugador** (`/estadisticas/`), explicar los KPIs personales de biblioteca, distribución por géneros/estados y la sección rápida **"Continuar jugando"**.
  2. Usar la acción rápida para **marcar un juego como `Terminado`** (o cambiar estado en `/biblioteca/` entre `Pendiente`, `En curso` y `Terminado`).
  3. **Calificar el título con 1–5 estrellas** (y reseña breve), comprobando que la media y el estado personal se actualizan al instante.

### Min 7–9 · Dashboard de Empresa (`[DEMO] Aurora Indie`)
- **Contexto:** Cambiar con `Alt+Tab` a la **Ventana 2 (`demo_estudio`)**.
- **Recorrido de URLs:** `/empresa/` → `/empresa/juegos/<id>/editar/`.
- **Acciones en vivo:**
  1. Mostrar el encabezado de `[DEMO] Aurora Indie` con la insignia de **Estudio verificado**.
  2. Recorrer las **métricas agregadas de bibliotecas** (total guardados, pendientes, en curso, terminados y tasa de finalización) y el bloque de **feedback reciente de comunidad** sobre sus juegos.
  3. Hacer clic en **Editar** sobre uno de sus juegos propios (`/empresa/juegos/<id>/editar/`), ajustar precio o descripción en vivo, guardar y mostrar el cambio reflejado inmediatamente en el panel.

### Min 9–11 · Dashboard de Administración (`staff`)
- **Contexto:** Cambiar con `Alt+Tab` al **Perfil 3 (`staff`)**.
- **Recorrido de URLs:** `/panel/` → `/panel/empresas/` → `/panel/estadisticas/`.
- **Acciones en vivo:**
  1. En `/panel/`, alternar en vivo el **filtro temporal (`7d` / `30d` / `Todo`)** (`?range=7d`, `?range=30d`, `?range=all`) mostrando cómo recalculan las altas y la actividad de comunidad.
  2. Señalar el indicador de **salud del catálogo** (juegos gratuitos vs. de pago y detección de fichas con descripción o géneros incompletos).
  3. Mostrar la gestión y **verificación de empresas** (`/panel/empresas/`) y cerrar la vista administrativa exhibiendo los **gráficos avanzados y heatmap de actividad**.

### Min 11–12 · Cierre Técnico y Limpieza Segura de Datos Simulados
- **Contexto:** Terminal proyectada junto al navegador.
- **Acciones en vivo:**
  1. Resumir en dos frases la arquitectura: aplicación desplegada en **AWS EC2 (Nginx + Gunicorn)** conectada por TLS a **Amazon RDS MySQL 8.4**, con auditoría automatizada (`verify_demo_readiness`) y contingencia local determinista en SQLite.
  2. Mostrar cómo todos los registros ficticios están aislados bajo los prefijos `demo_` y `[DEMO]` y ejecutar una vista previa sin borrado (o el borrado en vivo si ya concluyó la ronda de preguntas):
     ```bash
     DJANGO_DB_ENGINE=sqlite ./indieEnv/bin/python manage.py seed_demo --clear --dry-run
     ```

---

## 5. Limpieza post-presentación

Una vez finalizadas las preguntas del jurado/docente, dejar la base limpia de registros simulados:

1. **Previsualizar qué objetos se eliminarán (opcional pero recomendado en RDS compartida):**
   ```bash
   # En entorno principal (RDS/EC2)
   ./indieEnv/bin/python manage.py seed_demo --clear --dry-run

   # En entorno de contingencia local (SQLite)
   DJANGO_DB_ENGINE=sqlite ./indieEnv/bin/python manage.py seed_demo --clear --dry-run
   ```

2. **Ejecutar la limpieza definitiva de datos demo:**
   ```bash
   # En entorno principal (RDS/EC2)
   ./indieEnv/bin/python manage.py seed_demo --clear

   # En entorno de contingencia local (SQLite)
   DJANGO_DB_ENGINE=sqlite ./indieEnv/bin/python manage.py seed_demo --clear
   ```

3. **Constancia de trazabilidad y seguridad de datos:**
   - `seed_demo --clear` elimina exclusivamente dentro de una transacción atómica:
     - Usuarios cuyo `username` comienza con `demo_` (`demo_0000`…`demo_XXXX`, `demo_presentacion` y `demo_estudio`), junto con su `Enterprise` (`[DEMO] Aurora Indie`), entradas de `LibraryEntry`, temas (`Discussion`) y comentarios (`DiscussionReply`) asociados por cascada.
     - Juegos cuyo `title` comienza con `[DEMO] ` (`[DEMO] Ecos del Sur`, `[DEMO] Cripta Solar`, `[DEMO] Marea de Cristal`).
   - El catálogo real de IndieVault (~51.408 juegos indie) y las cuentas reales del equipo permanecen intactos.
