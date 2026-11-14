# Créditos y licencias

IndieVault es un proyecto académico sin ánimo de lucro. Este archivo reúne el
origen de los recursos que usa la aplicación y debe actualizarse cada vez que se
añada una imagen, una tipografía o una dependencia nueva.

## Marca y diseño

| Recurso | Origen | Licencia |
|---|---|---|
| Logotipo (`static/img/logo.png`, `logo-large.png`) | Recurso del propio proyecto | Uso interno del equipo |
| Hoja de estilos e interfaz | Elaboración propia | Uso interno del equipo |

## Portadas de los juegos

Las portadas se cargan **directamente desde el CDN público de Steam**:

```
https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/library_600x900.jpg
https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg
```

- Las imágenes pertenecen a sus desarrolladores y editores. Se muestran para
  identificar cada juego dentro de un catálogo académico y **no se descargan,
  modifican ni redistribuyen** con el repositorio.
- Si el proyecto dejara de ser académico o se publicara, habría que sustituirlas
  por material con licencia explícita o ajustarse a los términos de la API de
  Steam.
- Los juegos sin arte disponible muestran una portada generada por la propia app
  (degradado e iniciales), sin recursos externos.

## Datos del catálogo

Los metadatos de los juegos (título, estudio, año, géneros y precio) provienen de
un conjunto de datos público del catálogo de Steam, usado únicamente con fines
docentes. Los nombres y marcas de los juegos pertenecen a sus respectivos
titulares.

## Dependencias

| Dependencia | Versión | Licencia |
|---|---|---|
| [Django](https://www.djangoproject.com/) | 6.1.1 | BSD-3-Clause |
| [mysqlclient](https://github.com/PyMySQL/mysqlclient) | 2.3.0 | GPL-2.0 |
| [Pillow](https://python-pillow.org/) | 13.0.0 | MIT-CMU |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | 1.1.1 | BSD-3-Clause |
| [Chart.js](https://www.chartjs.org/) | 4.4.3 | MIT |

Chart.js se carga desde jsDelivr (`cdn.jsdelivr.net`) y solo se usa en las
páginas de estadísticas.

## Tipografías

La interfaz usa la pila de fuentes del sistema (`Inter`, `Segoe UI`, `system-ui`,
etc.). No se distribuye ninguna tipografía externa.

## Cómo añadir un recurso nuevo

1. Comprueba que la licencia permite su uso en un proyecto académico.
2. Guárdalo en `IndieVault/static/` o `media/` según corresponda.
3. Añade una fila a este archivo con el origen exacto y la licencia.
