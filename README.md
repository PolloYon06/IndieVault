# IndieVault

Aplicación web de catálogo de videojuegos hecha con Django. La base de datos
vive en **Amazon RDS** y es compartida por todo el equipo, así que todos ven los
mismos juegos y usuarios.

---

## Puesta en marcha (solo la primera vez)

Necesitas **Git** y **Python 3.12 o superior**. En Windows, al instalar Python
marca la casilla **“Add python.exe to PATH”**.

1. **Descarga el proyecto**

   ```bash
   git clone https://github.com/PolloYon06/IndieVault.git
   cd IndieVault
   ```

2. **Ejecuta el instalador**

   - **Windows:** doble clic en `scripts\instalar.bat`
   - **macOS / Linux:** `./scripts/instalar.sh`

   El instalador crea el entorno virtual, instala las dependencias y genera el
   archivo `.env`. Cuando lo pida, pega la contraseña de la base de datos (te la
   da el administrador del proyecto).

3. **Arranca la app**

   ```bash
   # Windows
   indieEnv\Scripts\activate
   # macOS / Linux
   source indieEnv/bin/activate

   python manage.py runserver
   ```

   Abre <http://127.0.0.1:8000/>.

Si la conexión falla, el instalador te dice exactamente qué pasa y qué hacer. No
hace falta editar el `.env` a mano.

---

## Trabajo diario

```bash
git pull --rebase                     # traer los cambios del equipo
source indieEnv/bin/activate          # Windows: indieEnv\Scripts\activate
python manage.py runserver            # probar en http://127.0.0.1:8000/
```

Cuando algo funcione:

```bash
git checkout -b mi-cambio
git add .
git commit -m "Describe el cambio"
git push -u origin mi-cambio
```

Y se abre un Pull Request en GitHub.

---

## Problemas frecuentes

| Mensaje | Qué significa | Qué hacer |
|---|---|---|
| `Can't connect to server on '127.0.0.1' (10061)` | No hay `.env` o está mal nombrado | Vuelve a ejecutar `scripts\instalar.bat` |
| `Can't connect ... (10060)` o timeout | Tu IP no está autorizada, o AWS está apagado | Envía tu IP al administrador (`https://checkip.amazonaws.com`) |
| `Access denied for user` (1045) | Contraseña incorrecta | Ejecuta otra vez el instalador y pega la contraseña exacta |
| `Unknown database` (1049) | Falta la base en el servidor | Avisa al administrador |

**Tu IP pública cambia** si te conectas desde otra red. Si de repente deja de
funcionar, casi seguro es eso: consulta tu IP y pásasela al administrador.

---

## Reglas del equipo

- No subas el `.env` a Git: ya está ignorado, no lo fuerces.
- No ejecutes `flush`, `drop` ni borres tablas: la base es compartida.
- Solo el administrador aplica migraciones. Si cambias modelos, avisa antes.
- Usa cuentas y datos de prueba, no datos personales reales.

---

## Datos de demostración

Para poblar los paneles de jugador, empresa y administración durante una presentación sin mezclar datos reales, existe el comando `seed_demo`. Todos los registros creados llevan el prefijo `demo_` o `[DEMO]` para dejar constancia explícita de que son datos simulados:

```bash
# Crear u obtener datos de demostración (incluye demo_presentacion y demo_estudio)
python manage.py seed_demo --password TuClaveDemo-2026!

# Eliminar únicamente los datos de demostración
python manage.py seed_demo --clear
```

Más detalle en [`docs/trabajo-equipo.md`](docs/trabajo-equipo.md) y
[`docs/aws-rds.md`](docs/aws-rds.md).
