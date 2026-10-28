# Importar el catálogo indie de Steam

El comando `import_steam_indies` importa juegos reales del CSV solo cuando el
campo `genres` incluye el género exacto `Indie`. No usa `tags` para clasificar,
porque las etiquetas de usuarios no son una señal suficientemente consistente.
El catálogo no crea entradas en bibliotecas personales.

1. Haz una copia de seguridad de la base de datos.
2. Aplica la migración que añade el ID de Steam y amplía el campo del título:

   ```bash
   python manage.py migrate
   ```

3. Simula la importación:

   ```bash
   python manage.py import_steam_indies \
     /ruta/games_march2025_cleaned_pt1_fixed.csv --dry-run
   ```

4. Si el resumen es correcto, importa los juegos y elimina los seis registros
   ficticios de demostración:

   ```bash
   python manage.py import_steam_indies \
     /ruta/games_march2025_cleaned_pt1_fixed.csv --remove-demo-games
   ```

El ID de aplicación de Steam se usa para evitar duplicados y actualizar
registros al repetir la importación. Las fechas no válidas se importan con año
`0`; se omiten filas sin ID, título o precio válido. El precio se conserva tal
como aparece en el CSV, sin conversión de moneda.

`--remove-demo-games` elimina únicamente los seis títulos y estudios de ejemplo
incluidos por la migración inicial. Sus entradas de biblioteca asociadas también
se eliminan, ya que apuntan a juegos ficticios. El modo `--dry-run` informa
cuántos registros coincidirían sin modificar la base. No se debe combinar
`--remove-demo-games` con `--limit`.

El explorador muestra 24 juegos por página para mantener manejable el catálogo
importado.
