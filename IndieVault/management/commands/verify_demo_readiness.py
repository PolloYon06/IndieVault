"""Audita que el entorno de IndieVault esté listo para la presentación (Día D).

Comprueba motor de base de datos, catálogo, cuentas de demostración
(``demo_presentacion`` y ``demo_estudio``), cuenta ``staff``, actividad de
comunidad y tiempos de respuesta HTTP locales en las rutas clave.
"""

from time import perf_counter

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.test import Client

from IndieVault.models import (
    Discussion,
    DiscussionReply,
    Enterprise,
    Game,
    LibraryEntry,
)

DEMO_PLAYER_USERNAME = 'demo_presentacion'
DEMO_STUDIO_USERNAME = 'demo_estudio'
DEMO_PREFIX = 'demo_'
DEMO_TITLE_PREFIX = '[DEMO] '

PUBLIC_SMOKE_ROUTES = (
    ('/', 'Pública · Inicio'),
    ('/explorar/', 'Pública · Explorar'),
    ('/explorar/catalogo/', 'Pública · Catálogo'),
    ('/buscar/?q=DEMO', 'Pública · Buscador'),
    ('/comunidad/', 'Pública · Comunidad'),
    ('/login/', 'Pública · Login'),
    ('/registro/', 'Pública · Registro'),
)

PLAYER_SMOKE_ROUTES = (
    ('/estadisticas/', 'Jugador · Estadísticas'),
    ('/biblioteca/', 'Jugador · Biblioteca'),
    ('/notificaciones/', 'Jugador · Notificaciones'),
)

ENTERPRISE_SMOKE_ROUTES = (
    ('/empresa/', 'Empresa · Dashboard'),
)

STAFF_SMOKE_ROUTES = (
    ('/panel/', 'Staff · Panel'),
)


class Command(BaseCommand):
    help = (
        'Verifica que la base de datos, cuentas demo, comunidad y rutas HTTP '
        'estén listas para la presentación en vivo.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--seed-if-missing',
            action='store_true',
            help=(
                'Si faltan cuentas demo (demo_presentacion o demo_estudio), '
                'ejecuta automáticamente seed_demo antes de verificar.'
            ),
        )
        parser.add_argument(
            '--users',
            type=int,
            default=30,
            help=(
                'Cantidad de usuarios ficticios para seed_demo cuando se usa '
                '--seed-if-missing (por defecto: 30).'
            ),
        )
        parser.add_argument(
            '--threads',
            type=int,
            default=10,
            help=(
                'Cantidad de temas de comunidad para seed_demo cuando se usa '
                '--seed-if-missing (por defecto: 10).'
            ),
        )
        parser.add_argument(
            '--password',
            type=str,
            default='',
            help=(
                'Contraseña esperada para verificar con check_password() en '
                'demo_presentacion y demo_estudio (o asignarla con '
                '--seed-if-missing / --fix-passwords).'
            ),
        )
        parser.add_argument(
            '--fix-passwords',
            action='store_true',
            help=(
                'Si se pasa junto con --password, actualiza la contraseña de '
                'demo_presentacion y demo_estudio si no tenían clave utilizable '
                'o no coincidían.'
            ),
        )
        parser.add_argument(
            '--strict',
            action='store_true',
            help='Lanza CommandError si alguna verificación crítica falla.',
        )

    def _status_badge(self, ok):
        if ok:
            return self.style.SUCCESS('[OK]')
        return self.style.ERROR('[FALLO]')

    def _run_route_checks(self, client, routes):
        results = []
        for path, label in routes:
            start = perf_counter()
            response = client.get(path)
            elapsed_ms = (perf_counter() - start) * 1000.0
            results.append(
                {
                    'label': label,
                    'path': path,
                    'status_code': response.status_code,
                    'elapsed_ms': elapsed_ms,
                    'ok': response.status_code == 200,
                    'skipped': False,
                }
            )
        return results

    def handle(self, *args, **options):
        password = options.get('password') or ''
        fix_passwords = bool(options.get('fix_passwords'))
        seed_if_missing = bool(options.get('seed_if_missing'))
        strict = bool(options.get('strict'))
        users_count = options.get('users', 30)
        threads_count = options.get('threads', 10)

        if fix_passwords and not password:
            raise CommandError(
                'La opción --fix-passwords requiere indicar --password <clave>.'
            )
        if users_count < 0 or threads_count < 0:
            raise CommandError('--users y --threads no pueden ser negativos.')

        User = get_user_model()

        if seed_if_missing:
            missing_player = not User.objects.filter(
                username=DEMO_PLAYER_USERNAME
            ).exists()
            missing_studio = not User.objects.filter(
                username=DEMO_STUDIO_USERNAME
            ).exists()
            if missing_player or missing_studio:
                has_partial_demo = (
                    User.objects.filter(username__startswith=DEMO_PREFIX).exists()
                    or Game.objects.filter(
                        title__startswith=DEMO_TITLE_PREFIX
                    ).exists()
                )
                self.stdout.write(
                    self.style.WARNING(
                        'Cuentas demo faltantes detectadas; ejecutando '
                        'seed_demo automáticamente...'
                    )
                )
                seed_kwargs = {
                    'users': users_count,
                    'threads': threads_count,
                    'clean': has_partial_demo,
                    'stdout': self.stdout,
                    'stderr': self.stderr,
                }
                if password:
                    seed_kwargs['password'] = password
                call_command('seed_demo', **seed_kwargs)

        if fix_passwords and password:
            repaired = []
            for username in (DEMO_PLAYER_USERNAME, DEMO_STUDIO_USERNAME):
                account = User.objects.filter(username=username).first()
                if account is None:
                    continue
                if not account.has_usable_password() or not account.check_password(
                    password
                ):
                    account.set_password(password)
                    account.save(update_fields=['password'])
                    repaired.append(username)
            if repaired:
                self.stdout.write(
                    self.style.SUCCESS(
                        'Contraseñas reparadas/actualizadas en: '
                        + ', '.join(repaired)
                    )
                )

        critical_failures = []
        check_rows = []

        # 1. Motor de base de datos y catálogo de juegos
        engine_setting = settings.DATABASES['default']['ENGINE']
        engine_name = engine_setting.rsplit('.', 1)[-1]
        total_games = Game.objects.count()
        demo_games = Game.objects.filter(
            title__startswith=DEMO_TITLE_PREFIX
        ).count()
        db_ok = total_games > 0
        if not db_ok:
            critical_failures.append(
                'El catálogo no contiene juegos (Game.objects.count() == 0).'
            )
        check_rows.append(
            (
                '1. Base de datos y catálogo',
                db_ok,
                f'Motor: {engine_name} | Juegos: {total_games} '
                f'({demo_games} con prefijo {DEMO_TITLE_PREFIX.strip()})',
            )
        )

        # 2. Cuenta jugador demo_presentacion
        presenter = User.objects.filter(username=DEMO_PLAYER_USERNAME).first()
        if presenter is None:
            player_ok = False
            critical_failures.append(
                f'Falta la cuenta jugador {DEMO_PLAYER_USERNAME}.'
            )
            player_detail = 'No existe (ejecuta seed_demo o usa --seed-if-missing)'
        else:
            usable_pw = presenter.has_usable_password()
            pw_match = presenter.check_password(password) if password else True
            lib_qs = LibraryEntry.objects.filter(user=presenter)
            want_count = lib_qs.filter(status=LibraryEntry.Status.WANT).count()
            playing_count = lib_qs.filter(
                status=LibraryEntry.Status.PLAYING
            ).count()
            done_count = lib_qs.filter(status=LibraryEntry.Status.DONE).count()
            total_lib = want_count + playing_count + done_count

            player_ok = (
                presenter.is_active
                and usable_pw
                and pw_match
                and total_lib >= 1
            )
            if not presenter.is_active:
                critical_failures.append(
                    f'La cuenta {DEMO_PLAYER_USERNAME} está inactiva.'
                )
            if not usable_pw:
                critical_failures.append(
                    f'{DEMO_PLAYER_USERNAME} no tiene contraseña utilizable.'
                )
            elif password and not pw_match:
                critical_failures.append(
                    f'La contraseña de {DEMO_PLAYER_USERNAME} no coincide con --password.'
                )
            if total_lib < 1:
                critical_failures.append(
                    f'La biblioteca de {DEMO_PLAYER_USERNAME} está vacía.'
                )

            pw_note = (
                f'clave usable={"sí" if usable_pw else "no"}'
                + (
                    f', coincide={"sí" if pw_match else "no"}'
                    if password
                    else ''
                )
            )
            player_detail = (
                f'Existe ({pw_note}) | Biblioteca: {total_lib} '
                f'(Pendiente: {want_count}, En curso: {playing_count}, '
                f'Terminado: {done_count})'
            )
        check_rows.append(
            (f'2. Jugador ({DEMO_PLAYER_USERNAME})', player_ok, player_detail)
        )

        # 3. Cuenta empresa demo_estudio
        studio_user = User.objects.filter(username=DEMO_STUDIO_USERNAME).first()
        enterprise = (
            Enterprise.objects.filter(user=studio_user).first()
            if studio_user is not None
            else None
        )
        if studio_user is None:
            studio_ok = False
            critical_failures.append(
                f'Falta la cuenta empresa {DEMO_STUDIO_USERNAME}.'
            )
            studio_detail = 'No existe (ejecuta seed_demo o usa --seed-if-missing)'
        else:
            usable_pw = studio_user.has_usable_password()
            pw_match = studio_user.check_password(password) if password else True
            has_enterprise = enterprise is not None
            is_verified = bool(enterprise and enterprise.is_verified)
            published_count = enterprise.games.count() if enterprise else 0

            studio_ok = (
                studio_user.is_active
                and usable_pw
                and pw_match
                and has_enterprise
                and is_verified
                and published_count >= 1
            )
            if not studio_user.is_active:
                critical_failures.append(
                    f'La cuenta {DEMO_STUDIO_USERNAME} está inactiva.'
                )
            if not usable_pw:
                critical_failures.append(
                    f'{DEMO_STUDIO_USERNAME} no tiene contraseña utilizable.'
                )
            elif password and not pw_match:
                critical_failures.append(
                    f'La contraseña de {DEMO_STUDIO_USERNAME} no coincide con --password.'
                )
            if not has_enterprise:
                critical_failures.append(
                    f'{DEMO_STUDIO_USERNAME} no tiene Enterprise vinculada.'
                )
            else:
                if not is_verified:
                    critical_failures.append(
                        f'La empresa {enterprise.studio_name} no tiene is_verified=True.'
                    )
                if published_count < 1:
                    critical_failures.append(
                        f'La empresa {enterprise.studio_name} no tiene juegos publicados.'
                    )

            pw_note = (
                f'clave usable={"sí" if usable_pw else "no"}'
                + (
                    f', coincide={"sí" if pw_match else "no"}'
                    if password
                    else ''
                )
            )
            ent_note = (
                f'{enterprise.studio_name} (verificada={"sí" if is_verified else "no"}, '
                f'juegos publicados={published_count})'
                if enterprise
                else 'sin Enterprise vinculada'
            )
            studio_detail = f'Existe ({pw_note}) | {ent_note}'
        check_rows.append(
            (f'3. Empresa ({DEMO_STUDIO_USERNAME})', studio_ok, studio_detail)
        )

        # 4. Cuenta administradora (is_staff=True)
        staff_qs = User.objects.filter(is_staff=True, is_active=True).order_by(
            'id'
        )
        staff_count = staff_qs.count()
        staff_user = staff_qs.first()
        staff_ok = staff_count >= 1
        if not staff_ok:
            critical_failures.append(
                'No hay ninguna cuenta administradora activa (is_staff=True).'
            )
            staff_detail = '0 administradores activos disponibles'
        else:
            staff_detail = (
                f'{staff_count} activo(s) (principal: {staff_user.username})'
            )
        check_rows.append(('4. Administración (is_staff)', staff_ok, staff_detail))

        # 5. Actividad de comunidad
        discussions_total = Discussion.objects.count()
        replies_total = DiscussionReply.objects.count()
        community_ok = discussions_total >= 1
        if not community_ok:
            critical_failures.append(
                'No existen temas en comunidad (Discussion.objects.count() == 0).'
            )
        check_rows.append(
            (
                '5. Comunidad',
                community_ok,
                f'Temas (Discussion): {discussions_total} | '
                f'Comentarios (DiscussionReply): {replies_total}',
            )
        )

        # 6. Smoke test HTTP + tiempos de respuesta locales
        smoke_results = []
        anon_client = Client(HTTP_HOST='127.0.0.1')
        smoke_results.extend(
            self._run_route_checks(anon_client, PUBLIC_SMOKE_ROUTES)
        )

        if presenter is not None:
            player_client = Client(HTTP_HOST='127.0.0.1')
            player_client.force_login(presenter)
            smoke_results.extend(
                self._run_route_checks(player_client, PLAYER_SMOKE_ROUTES)
            )
        else:
            for path, label in PLAYER_SMOKE_ROUTES:
                smoke_results.append(
                    {
                        'label': label,
                        'path': path,
                        'status_code': None,
                        'elapsed_ms': 0.0,
                        'ok': False,
                        'skipped': True,
                    }
                )

        if studio_user is not None:
            studio_client = Client(HTTP_HOST='127.0.0.1')
            studio_client.force_login(studio_user)
            smoke_results.extend(
                self._run_route_checks(studio_client, ENTERPRISE_SMOKE_ROUTES)
            )
        else:
            for path, label in ENTERPRISE_SMOKE_ROUTES:
                smoke_results.append(
                    {
                        'label': label,
                        'path': path,
                        'status_code': None,
                        'elapsed_ms': 0.0,
                        'ok': False,
                        'skipped': True,
                    }
                )

        if staff_user is not None:
            staff_client = Client(HTTP_HOST='127.0.0.1')
            staff_client.force_login(staff_user)
            smoke_results.extend(
                self._run_route_checks(staff_client, STAFF_SMOKE_ROUTES)
            )
        else:
            for path, label in STAFF_SMOKE_ROUTES:
                smoke_results.append(
                    {
                        'label': label,
                        'path': path,
                        'status_code': None,
                        'elapsed_ms': 0.0,
                        'ok': False,
                        'skipped': True,
                    }
                )

        for item in smoke_results:
            if not item['skipped'] and not item['ok']:
                critical_failures.append(
                    f"Smoke test en {item['path']} ({item['label']}) devolvió "
                    f"HTTP {item['status_code']} (esperado: 200)."
                )

        executed_smoke = [r for r in smoke_results if not r['skipped']]
        passed_smoke = [r for r in executed_smoke if r['ok']]
        smoke_all_ok = (
            len(executed_smoke) == len(smoke_results)
            and len(passed_smoke) == len(executed_smoke)
        )
        check_rows.append(
            (
                '6. Smoke test HTTP local',
                smoke_all_ok,
                f'{len(passed_smoke)}/{len(smoke_results)} rutas en HTTP 200',
            )
        )

        # Impresión del reporte consolidado
        separator = '=' * 88
        thin_sep = '-' * 88
        self.stdout.write(separator)
        self.stdout.write(
            'AUDITORÍA DE PREPARACIÓN DÍA D · INDIEVAULT (verify_demo_readiness)'
        )
        self.stdout.write(separator)
        for section, ok, detail in check_rows:
            badge = self._status_badge(ok)
            self.stdout.write(f'{badge} {section:<32} | {detail}')

        self.stdout.write(thin_sep)
        self.stdout.write(
            f"{'CONTEXTO':<26} | {'RUTA':<22} | {'HTTP':<6} | {'TIEMPO':>10} | ESTADO"
        )
        self.stdout.write(thin_sep)
        for item in smoke_results:
            if item['skipped']:
                code_str = '---'
                time_str = '---'
                state_str = self.style.WARNING('OMITIDA')
            else:
                code_str = str(item['status_code'])
                time_str = f"{item['elapsed_ms']:.1f} ms"
                state_str = (
                    self.style.SUCCESS('OK')
                    if item['ok']
                    else self.style.ERROR('FALLO')
                )
            self.stdout.write(
                f"{item['label']:<26} | {item['path']:<22} | "
                f"{code_str:<6} | {time_str:>10} | {state_str}"
            )
        self.stdout.write(separator)

        if critical_failures:
            self.stdout.write(
                self.style.WARNING(
                    f'Resultado: {len(critical_failures)} verificación(es) pendiente(s) o con fallo:'
                )
            )
            for issue in critical_failures:
                self.stdout.write(f'  - {issue}')
            if strict:
                raise CommandError(
                    'Verificación estricta fallida: '
                    + '; '.join(critical_failures)
                )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    'Resultado: ENTORNO 100% LISTO PARA PRESENTACIÓN.'
                )
            )
