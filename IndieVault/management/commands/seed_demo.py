"""Genera datos ficticios para una presentación de IndieVault.

Los datos se marcan con el prefijo ``demo_`` y pueden eliminarse sin tocar
las cuentas, bibliotecas ni conversaciones reales.
"""

import os
import random
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from IndieVault.models import (
    Discussion,
    DiscussionReply,
    Enterprise,
    Game,
    LibraryEntry,
    Profile,
)

DEMO_PREFIX = 'demo_'
DEMO_BIO = 'Cuenta de demostración · datos ficticios para la presentación.'
DEMO_TITLE_PREFIX = '[DEMO] '
DEMO_STUDIO_NAME = '[DEMO] Aurora Indie'
DEMO_STUDIO_GAMES = [
    {
        'title': f'{DEMO_TITLE_PREFIX}Ecos del Sur',
        'description': 'Aventura narrativa de demostración ambientada en archipiélagos australes.',
        'genres': 'Aventura, Narrativo',
        'year': 2026,
        'price': '6.99',
        'symbol': '◈',
    },
    {
        'title': f'{DEMO_TITLE_PREFIX}Cripta Solar',
        'description': 'Exploración de ruinas y acertijos de luz generados para la presentación.',
        'genres': 'Puzle, Exploración',
        'year': 2025,
        'price': '4.99',
        'symbol': '✦',
    },
    {
        'title': f'{DEMO_TITLE_PREFIX}Marea de Cristal',
        'description': 'Plataformas de precisión con banda sonora reactiva (ficha de demostración).',
        'genres': 'Plataformas, Acción',
        'year': 2026,
        'price': '0.00',
        'symbol': '❖',
    },
]


class Command(BaseCommand):
    help = 'Crea usuarios, bibliotecas y actividad de comunidad de demostración.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--users',
            type=int,
            default=150,
            help='Cantidad de usuarios ficticios a crear (por defecto: 150).',
        )
        parser.add_argument(
            '--threads',
            type=int,
            default=20,
            help='Cantidad de temas de comunidad a crear (por defecto: 20).',
        )
        parser.add_argument(
            '--clean',
            action='store_true',
            help='Elimina los datos demo existentes antes de crear los nuevos.',
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Elimina los datos demo y termina, sin crear datos nuevos.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Muestra lo que se crearía o eliminaría, sin modificar la base.',
        )
        parser.add_argument(
            '--seed',
            type=int,
            default=20261125,
            help='Semilla aleatoria para que la simulación sea reproducible.',
        )
        parser.add_argument(
            '--password',
            type=str,
            default=os.environ.get('DEMO_PASSWORD', ''),
            help='Contraseña opcional para las cuentas demo_presentacion y demo_estudio.',
        )

    def handle(self, *args, **options):
        if options['users'] < 0 or options['threads'] < 0:
            raise CommandError('--users y --threads no pueden ser negativos.')

        User = get_user_model()
        demo_users = User.objects.filter(username__startswith=DEMO_PREFIX)
        demo_games = Game.objects.filter(title__startswith=DEMO_TITLE_PREFIX)
        demo_entries = LibraryEntry.objects.filter(user__in=demo_users)
        demo_threads = Discussion.objects.filter(author__in=demo_users)
        demo_replies = DiscussionReply.objects.filter(author__in=demo_users)

        if options['dry_run']:
            self.stdout.write(
                'Datos demo actuales: '
                f'{demo_users.count()} usuarios, '
                f'{demo_games.count()} juegos demo, '
                f'{demo_entries.count()} entradas de biblioteca, '
                f'{demo_threads.count()} temas, '
                f'{demo_replies.count()} respuestas.'
            )
            if options['clear'] or options['clean']:
                self.stdout.write('Se eliminarían esos datos demo.')
            else:
                self.stdout.write(
                    f'Se crearían {options["users"]} usuarios, 1 estudio verificado '
                    f'con {len(DEMO_STUDIO_GAMES)} juegos y {options["threads"]} temas nuevos.'
                )
            return

        if options['clear'] or options['clean']:
            with transaction.atomic():
                deleted_games, _ = demo_games.delete()
                deleted_users, _ = demo_users.delete()
                deleted = deleted_games + deleted_users
            self.stdout.write(
                self.style.WARNING(f'Datos demo eliminados: {deleted} objetos.')
            )
            if options['clear']:
                return

        if demo_users.exists() or demo_games.exists():
            raise CommandError(
                'Ya existen datos demo. Usa --clean para reemplazarlos o '
                '--clear para eliminarlos.'
            )

        rng = random.Random(options['seed'])
        now = timezone.now()
        users = []
        demo_password = options.get('password') or os.environ.get('DEMO_PASSWORD')

        with transaction.atomic():
            for index in range(options['users']):
                user = User.objects.create_user(
                    username=f'{DEMO_PREFIX}{index:04d}',
                    password=None,
                )
                user.first_name = 'Demo'
                user.last_name = f'Usuario {index:04d}'
                users.append(user)

            presenter = User.objects.create_user(
                username=f'{DEMO_PREFIX}presentacion',
                password=demo_password or None,
            )
            presenter.first_name = 'Demo'
            presenter.last_name = 'Presentación'
            users.append(presenter)

            studio_user = User.objects.create_user(
                username=f'{DEMO_PREFIX}estudio',
                email='demo_estudio@example.com',
                password=demo_password or None,
            )
            studio_user.first_name = 'Aurora'
            studio_user.last_name = 'Indie'
            studio_user.date_joined = now - timedelta(days=14)
            studio_user.save(update_fields=['first_name', 'last_name', 'date_joined'])

            demo_enterprise = Enterprise.objects.create(
                user=studio_user,
                studio_name=DEMO_STUDIO_NAME,
                website='https://aurora-demo.example.com',
                description='Estudio de demostración para exhibir el panel de empresa en IndieVault.',
                is_verified=True,
            )
            studio_games = []
            for spec in DEMO_STUDIO_GAMES:
                studio_games.append(
                    Game.objects.create(
                        title=spec['title'],
                        studio=DEMO_STUDIO_NAME,
                        description=spec['description'],
                        genres=spec['genres'],
                        year=spec['year'],
                        price=spec['price'],
                        symbol=spec['symbol'],
                        publisher=demo_enterprise,
                    )
                )
            studio_game_ids = [game.pk for game in studio_games]
            game_ids = list(Game.objects.values_list('pk', flat=True))

            # Reparte las altas en el último año para que el panel tenga
            # actividad reciente y una línea temporal creíble.
            for index, user in enumerate(users[:-1]):
                if index < 8:
                    days = rng.uniform(0, 7)
                elif index < 38:
                    days = rng.uniform(7, 30)
                else:
                    days = rng.uniform(30, 365)
                user.date_joined = now - timedelta(days=days)
            presenter.date_joined = now - timedelta(days=2)

            User.objects.bulk_update(
                users,
                ['first_name', 'last_name', 'date_joined'],
                batch_size=200,
            )

            Profile.objects.filter(user__in=[*users, studio_user]).update(
                bio=DEMO_BIO,
                visibility=Profile.Visibility.MEMBERS,
            )
            public_ids = [user.pk for user in users[:6]]
            Profile.objects.filter(user_id__in=public_ids).update(
                visibility=Profile.Visibility.PUBLIC,
            )

            statuses = [
                LibraryEntry.Status.WANT.value,
                LibraryEntry.Status.PLAYING.value,
                LibraryEntry.Status.DONE.value,
            ]
            entries = []
            for index, game_id in enumerate(studio_game_ids):
                entries.append(
                    LibraryEntry(
                        user=presenter,
                        game_id=game_id,
                        status=statuses[index % len(statuses)],
                    )
                )
            for user in users:
                amount = min(6 if user == presenter else rng.randint(3, 6), len(game_ids))
                for game_id in rng.sample(game_ids, amount):
                    entries.append(
                        LibraryEntry(
                            user=user,
                            game_id=game_id,
                            status=rng.choices(
                                statuses,
                                weights=[0.4, 0.3, 0.3],
                                k=1,
                            )[0],
                        )
                    )
            LibraryEntry.objects.bulk_create(
                entries,
                ignore_conflicts=True,
                batch_size=500,
            )

            categories = [category.value for category in Discussion.Category]
            created_threads = []
            for index in range(options['threads']):
                created_at = now - timedelta(
                    days=rng.randint(0, 45),
                    hours=rng.randint(0, 23),
                )
                if index < len(studio_game_ids):
                    target_game_id = studio_game_ids[index]
                elif index % 3:
                    target_game_id = rng.choice(game_ids)
                else:
                    target_game_id = None
                thread = Discussion.objects.create(
                    game_id=target_game_id,
                    author=presenter if index == 0 else rng.choice(users),
                    title=f'{DEMO_TITLE_PREFIX}Tema de prueba {index + 1:02d}',
                    body=(
                        'Contenido de demostración generado para la presentación. '
                        'No representa una conversación real.'
                    ),
                    category=rng.choice(categories),
                    is_pinned=index == 0,
                )
                Discussion.objects.filter(pk=thread.pk).update(
                    created_at=created_at,
                    last_activity_at=created_at,
                )
                created_threads.append((thread, created_at))

            for thread, created_at in created_threads:
                reply_times = []
                for _ in range(rng.randint(2, 4)):
                    reply_at = created_at + timedelta(
                        days=rng.randint(0, 5),
                        hours=rng.randint(1, 23),
                    )
                    if reply_at > now:
                        reply_at = now - timedelta(hours=rng.randint(1, 24))
                    reply = DiscussionReply.objects.create(
                        discussion=thread,
                        author=rng.choice(users),
                        body=(
                            'Respuesta de demostración. Este comentario forma '
                            'parte de los datos ficticios de la presentación.'
                        ),
                    )
                    DiscussionReply.objects.filter(pk=reply.pk).update(
                        created_at=reply_at,
                        updated_at=reply_at,
                    )
                    reply_times.append(reply_at)
                if reply_times:
                    Discussion.objects.filter(pk=thread.pk).update(
                        last_activity_at=max(reply_times),
                    )

        self.stdout.write(
            self.style.SUCCESS(
                f'Demo creada: {len(users)} jugadores + 1 estudio ({studio_user.username}), '
                f'{len(studio_games)} juegos demo, '
                f'{len(entries)} entradas de biblioteca, '
                f'{options["threads"]} temas y respuestas.'
            )
        )
        if not demo_password:
            self.stdout.write(
                'Las cuentas demo_presentacion y demo_estudio no tienen contraseña. '
                'Usa `--password <clave>` o `manage.py changepassword` si necesitas entrar con ellas.'
            )
