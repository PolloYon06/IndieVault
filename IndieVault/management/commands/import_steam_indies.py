import ast
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from IndieVault.models import Game, LibraryEntry


DEMO_GAMES = (
    ('Sendero de luciérnagas', 'Bruma Studio'),
    ('Cripta de vidrio', 'Nueve Lentes'),
    ('Jardín de invierno', 'Marea Baja'),
    ('El último faro', 'Ala Rota'),
    ('Taller de engranajes', 'Cuarto Piso'),
    ('Aurora fija', 'Senda Norte'),
)

BULK_UPDATE_FIELDS = (
    'slug',
    'title',
    'studio',
    'year',
    'genres',
    'price',
    'symbol',
    'tint',
)


def parse_list(value):
    try:
        parsed = ast.literal_eval(value or '[]')
    except (ValueError, SyntaxError):
        return []
    return parsed if isinstance(parsed, (list, tuple)) else []


def make_game(row):
    try:
        app_id = int(row['appid'])
    except (KeyError, TypeError, ValueError):
        return None, 'invalid_appid'
    if app_id <= 0:
        return None, 'invalid_appid'

    title = (row.get('name') or '').strip()
    if not title:
        return None, 'missing_title'

    genres = parse_list(row.get('genres'))
    if not any(str(genre).casefold() == 'indie' for genre in genres):
        return None, 'not_indie'

    try:
        price = Decimal((row.get('price') or '').strip()).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return None, 'invalid_price'
    if not price.is_finite() or price < 0 or price >= Decimal('1000'):
        return None, 'invalid_price'

    release_date = (row.get('release_date') or '').strip()
    try:
        year = datetime.strptime(release_date, '%d-%m-%Y').year
    except ValueError:
        year = 0

    developers = parse_list(row.get('developers'))
    publishers = parse_list(row.get('publishers'))
    studio = next(
        (str(name).strip() for name in developers if str(name).strip()),
        '',
    )
    if not studio:
        studio = next(
            (str(name).strip() for name in publishers if str(name).strip()),
            'Desarrollador independiente',
        )

    genre_text = ','.join(str(genre).strip() for genre in genres if str(genre).strip())
    base_slug = slugify(title)[:100].strip('-') or 'juego'
    slug = f'{base_slug}-steam-{app_id}'

    return Game(
        steam_app_id=app_id,
        title=title,
        slug=slug,
        studio=studio[:120],
        year=year,
        genres=genre_text[:255],
        price=price,
        symbol='◈',
        tint='',
    ), None


class Command(BaseCommand):
    help = 'Importa juegos marcados con el género Indie en el CSV de Steam.'

    def add_arguments(self, parser):
        parser.add_argument('csv_file', type=Path)
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Valida el CSV y muestra qué se importaría sin modificar la base.',
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Procesa como máximo este número de filas CSV.',
        )
        parser.add_argument(
            '--remove-demo-games',
            action='store_true',
            help='Elimina los seis juegos ficticios de demostración y sus entradas de biblioteca.',
        )

    def handle(self, *args, **options):
        csv_path = options['csv_file']
        if not csv_path.is_file():
            raise CommandError(f'No existe el archivo CSV: {csv_path}')
        if options['limit'] is not None and options['limit'] < 1:
            raise CommandError('--limit debe ser mayor que cero.')
        if options['limit'] is not None and options['remove_demo_games']:
            raise CommandError('--remove-demo-games no se puede combinar con --limit.')

        counts = {
            'rows': 0,
            'indie_rows': 0,
            'imported': 0,
            'not_indie': 0,
            'invalid_appid': 0,
            'missing_title': 0,
            'invalid_price': 0,
            'invalid_release_date': 0,
            'duplicate_appid': 0,
        }
        seen_app_ids = set()
        batch = []

        try:
            source = csv_path.open(encoding='utf-8-sig', newline='')
        except OSError as exc:
            raise CommandError(f'No se pudo abrir {csv_path}: {exc}') from exc

        with source:
            reader = csv.DictReader(source)
            required_columns = {'appid', 'name', 'genres', 'price'}
            if not reader.fieldnames or not required_columns <= set(reader.fieldnames):
                raise CommandError(
                    'El CSV debe contener al menos las columnas appid, name, genres y price.'
                )

            for row in reader:
                counts['rows'] += 1
                game, error = make_game(row)
                if error:
                    counts[error] += 1
                    if options['limit'] and counts['rows'] >= options['limit']:
                        break
                    continue

                counts['indie_rows'] += 1
                if game.steam_app_id in seen_app_ids:
                    counts['duplicate_appid'] += 1
                    continue
                seen_app_ids.add(game.steam_app_id)
                if game.year == 0:
                    counts['invalid_release_date'] += 1
                batch.append(game)

                if len(batch) >= 500:
                    self._flush_batch(batch, counts, options['dry_run'])
                    batch.clear()

                if options['limit'] and counts['rows'] >= options['limit']:
                    break

        if batch:
            self._flush_batch(batch, counts, options['dry_run'])

        if options['remove_demo_games']:
            demo_games = Game.objects.none()
            for title, studio in DEMO_GAMES:
                demo_games = demo_games | Game.objects.filter(
                    steam_app_id__isnull=True,
                    title=title,
                    studio=studio,
                )
            counts['removed_demo_library_entries'] = LibraryEntry.objects.filter(
                game__in=demo_games
            ).count()
            counts['removed_demo_games'] = demo_games.count()
        if not options['dry_run'] and options['remove_demo_games']:
            with transaction.atomic():
                demo_games.delete()

        self.stdout.write(f"Filas revisadas: {counts['rows']}")
        self.stdout.write(f"Filas marcadas Indie por Steam: {counts['indie_rows']}")
        self.stdout.write(f"Juegos procesados: {counts['imported']}")
        self.stdout.write(f"Filas no Indie omitidas: {counts['not_indie']}")
        invalid_rows = (
            counts['invalid_appid']
            + counts['missing_title']
            + counts['invalid_price']
        )
        self.stdout.write(f'Filas inválidas omitidas: {invalid_rows}')
        self.stdout.write(
            'Fechas inválidas, año guardado como 0: '
            f"{counts['invalid_release_date']}"
        )
        self.stdout.write(f"App IDs repetidos omitidos: {counts['duplicate_appid']}")
        if options['remove_demo_games']:
            self.stdout.write(
                'Juegos de demostración eliminados: '
                f"{counts.get('removed_demo_games', 0)}"
            )
            self.stdout.write(
                'Entradas de biblioteca asociadas eliminadas: '
                f"{counts.get('removed_demo_library_entries', 0)}"
            )
        if options['dry_run']:
            self.stdout.write(
                self.style.WARNING('Simulación: no se modificó la base de datos.')
            )

    def _flush_batch(self, batch, counts, dry_run):
        if not dry_run:
            Game.objects.bulk_create(
                batch,
                batch_size=500,
                update_conflicts=True,
                update_fields=BULK_UPDATE_FIELDS,
                unique_fields=('steam_app_id',),
            )
        counts['imported'] += len(batch)
