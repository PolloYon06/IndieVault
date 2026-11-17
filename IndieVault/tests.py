import base64
import csv
import tempfile
from io import BytesIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from PIL import Image as PILImage

from .models import Enterprise, Game, LibraryEntry, Profile
from .stats import admin_stats, user_stats
from .templatetags.indievault_tags import avatar_url


class RouteTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = get_user_model().objects.create_user(
            username='rutas', password='clave-rutas-123'
        )

    def test_index(self):
        response = self.client.get(reverse('index'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'index.html')

    def test_explorar(self):
        response = self.client.get(reverse('explorar'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'explorar.html')

    def test_biblioteca(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('biblioteca'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'biblioteca.html')

    def test_biblioteca_requires_login(self):
        response = self.client.get(reverse('biblioteca'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_nav_marks_current_page(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('biblioteca'))
        self.assertContains(response, 'class="library active"')
        self.assertContains(response, 'aria-current="page"')

    def test_brand_uses_logo(self):
        response = self.client.get(reverse('index'))
        self.assertContains(response, 'img/logo.png')
        self.assertContains(response, 'img/logo-large.png')

    def test_subscription_has_trust_pills(self):
        response = self.client.get(reverse('suscripcion'))
        self.assertContains(response, 'Gratis para siempre')
        self.assertContains(response, 'Sin spam')
        self.assertContains(response, 'Cancela cuando quieras')

    def test_index_cards_link_to_real_pages(self):
        response = self.client.get(reverse('index'))
        self.assertContains(response, reverse('explorar'))
        self.assertContains(response, reverse('biblioteca'))

    def test_unknown_route_returns_404(self):
        self.assertEqual(self.client.get('/no-existe/').status_code, 404)

    def test_404_page_is_themed(self):
        response = self.client.get('/ruta-inexistente/')
        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, '404.html')
        self.assertContains(response, 'Página perdida en el vacío', status_code=404)


class DetailTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_game_detail(self):
        game = Game.objects.first()
        response = self.client.get(reverse('game_detail', args=[game.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'game_detail.html')
        self.assertContains(response, game.title)
        self.assertContains(response, game.studio)

    def test_game_detail_unknown_slug_404(self):
        self.assertEqual(self.client.get('/juego/no-existe/').status_code, 404)

    def test_detail_related_games(self):
        game = Game.objects.exclude(genres='').first()
        response = self.client.get(reverse('game_detail', args=[game.slug]))
        self.assertContains(response, 'Comparten género')


class LibraryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='lector', password='clave-lector-123'
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_catalog_shows_add_for_new_user(self):
        html = self.client.get(reverse('explorar')).content.decode()
        self.assertIn('Añadir a biblioteca', html)
        self.assertNotIn('Quitar de la biblioteca', html)

    def test_catalog_shows_remove_for_saved_game(self):
        game = Game.objects.first()
        LibraryEntry.objects.create(
            user=self.user, game=game, status=LibraryEntry.Status.WANT
        )
        html = self.client.get(reverse('explorar')).content.decode()
        self.assertIn('Quitar de la biblioteca', html)

    def test_remove_then_add_to_library(self):
        game = Game.objects.first()
        LibraryEntry.objects.get_or_create(user=self.user, game=game)
        self.client.post(reverse('remove_from_library', args=[game.pk]))
        self.assertEqual(
            LibraryEntry.objects.filter(user=self.user, game=game).count(), 0
        )
        self.client.post(reverse('add_to_library', args=[game.pk]))
        self.assertEqual(
            LibraryEntry.objects.filter(user=self.user, game=game).count(), 1
        )

    def test_add_does_not_duplicate(self):
        game = Game.objects.first()
        self.client.post(reverse('add_to_library', args=[game.pk]))
        self.client.post(reverse('add_to_library', args=[game.pk]))
        self.assertEqual(
            LibraryEntry.objects.filter(user=self.user, game=game).count(), 1
        )

    def test_library_entry_status_can_be_updated(self):
        entry = LibraryEntry.objects.create(
            user=self.user,
            game=Game.objects.first(),
            status=LibraryEntry.Status.WANT,
        )

        response = self.client.post(
            reverse('update_library_status', args=[entry.pk]),
            {'status': LibraryEntry.Status.PLAYING},
        )

        self.assertRedirects(response, reverse('biblioteca'))
        entry.refresh_from_db()
        self.assertEqual(entry.status, LibraryEntry.Status.PLAYING)

        response = self.client.post(
            reverse('update_library_status', args=[entry.pk]),
            {'status': LibraryEntry.Status.DONE},
        )

        self.assertRedirects(response, reverse('biblioteca'))
        entry.refresh_from_db()
        self.assertEqual(entry.status, LibraryEntry.Status.DONE)

    def test_library_status_rejects_invalid_value(self):
        entry = LibraryEntry.objects.create(
            user=self.user,
            game=Game.objects.first(),
            status=LibraryEntry.Status.WANT,
        )

        response = self.client.post(
            reverse('update_library_status', args=[entry.pk]),
            {'status': 'Inventado'},
        )

        self.assertRedirects(response, reverse('biblioteca'))
        entry.refresh_from_db()
        self.assertEqual(entry.status, LibraryEntry.Status.WANT)

    def test_library_status_cannot_change_another_users_entry(self):
        other = get_user_model().objects.create_user(
            username='otro-estado', password='clave-otro-estado-123'
        )
        entry = LibraryEntry.objects.create(
            user=other,
            game=Game.objects.first(),
            status=LibraryEntry.Status.WANT,
        )

        response = self.client.post(
            reverse('update_library_status', args=[entry.pk]),
            {'status': LibraryEntry.Status.DONE},
        )

        self.assertEqual(response.status_code, 404)
        entry.refresh_from_db()
        self.assertEqual(entry.status, LibraryEntry.Status.WANT)

    def test_library_status_update_requires_login_and_post(self):
        entry = LibraryEntry.objects.create(
            user=self.user,
            game=Game.objects.first(),
            status=LibraryEntry.Status.WANT,
        )
        url = reverse('update_library_status', args=[entry.pk])

        self.client.logout()
        response = self.client.post(url, {'status': LibraryEntry.Status.DONE})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)

    def test_libraries_are_isolated_per_user(self):
        game = Game.objects.first()
        other = get_user_model().objects.create_user(
            username='otro', password='clave-otro-123'
        )
        LibraryEntry.objects.create(user=other, game=game)

        response = self.client.get(reverse('biblioteca'))
        self.assertNotContains(response, game.title)

        self.client.post(reverse('add_to_library', args=[game.pk]))
        self.assertEqual(LibraryEntry.objects.filter(game=game).count(), 2)
        self.assertEqual(
            LibraryEntry.objects.filter(user=other, game=game).count(), 1
        )
        self.assertEqual(
            LibraryEntry.objects.filter(user=self.user, game=game).count(), 1
        )

    def test_add_requires_login(self):
        self.client.logout()
        game = Game.objects.first()
        response = self.client.post(reverse('add_to_library', args=[game.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)
        self.assertEqual(LibraryEntry.objects.count(), 0)

    def test_add_rejects_get(self):
        game = Game.objects.first()
        response = self.client.get(reverse('add_to_library', args=[game.pk]))
        self.assertEqual(response.status_code, 405)

    def test_detail_prompts_login_for_guests(self):
        self.client.logout()
        game = Game.objects.first()
        response = self.client.get(reverse('game_detail', args=[game.slug]))
        self.assertContains(response, 'Inicia sesión para guardar')


class FilterTests(TestCase):
    def setUp(self):
        self.client = Client()

    def page(self, **params):
        return self.client.get(reverse('explorar'), params).content.decode()

    def test_suscripcion(self):
        response = self.client.get(reverse('suscripcion'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'suscripcion.html')
        self.assertContains(response, 'Primer mes gratis')
        self.assertContains(response, '$5')

    def test_no_filter_shows_all_games(self):
        html = self.page()
        for game in ['Sendero de luciérnagas', 'Cripta de vidrio', 'Jardín de invierno',
                     'El último faro', 'Taller de engranajes', 'Aurora fija']:
            self.assertIn(game, html)

    def test_genre_filter(self):
        html = self.page(genre='Puzle')
        self.assertIn('Cripta de vidrio', html)
        self.assertIn('Taller de engranajes', html)
        self.assertNotIn('Sendero de luciérnagas', html)

    def test_search_by_title(self):
        html = self.page(q='faro')
        self.assertIn('El último faro', html)
        self.assertNotIn('Sendero de luciérnagas', html)

    def test_price_free(self):
        html = self.page(price='free')
        self.assertIn('Cripta de vidrio', html)
        self.assertIn('Aurora fija', html)
        self.assertNotIn('El último faro', html)

    def test_price_under_ten(self):
        html = self.page(price='10')
        self.assertIn('Sendero de luciérnagas', html)
        self.assertIn('$9.99', html)
        self.assertIn('$4.50', html)
        self.assertNotIn('El último faro', html)
        self.assertNotIn('class="price free"', html)

    def test_sort_a_to_z(self):
        html = self.page(sort='az')
        positions = [html.index(t) for t in ['Aurora fija', 'Cripta de vidrio', 'El último faro']]
        self.assertEqual(positions, sorted(positions))

    def test_sort_newest(self):
        html = self.page(sort='newest')
        last_year = html.index('El último faro')
        new_year = html.index('Sendero de luciérnagas')
        self.assertLess(new_year, last_year)

    def test_combined_genre_and_price(self):
        html = self.page(genre='Exploración', price='10')
        self.assertIn('Jardín de invierno', html)
        self.assertNotIn('Aurora fija', html)

    def test_no_results_empty_state(self):
        html = self.page(q='xyzabc')
        self.assertIn('No encontramos nada', html)
        self.assertIn('Limpiar filtros', html)

    def test_catalog_is_paginated(self):
        for index in range(19):
            Game.objects.create(
                title=f'Juego adicional {index}',
                studio='Estudio de prueba',
                year=2025,
                genres='Indie',
            )

        first_page = self.client.get(reverse('explorar'))
        second_page = self.client.get(reverse('explorar'), {'page': 2})

        self.assertEqual(len(first_page.context['games']), 24)
        self.assertEqual(len(second_page.context['games']), 1)
        self.assertContains(first_page, 'Página 1 de 2')
        self.assertContains(second_page, 'Página 2 de 2')


class SteamImportTests(TestCase):
    columns = [
        'appid', 'name', 'release_date', 'price', 'developers', 'publishers', 'genres',
    ]

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.csv_path = Path(self.temp_dir.name) / 'steam.csv'

    def write_csv(self, rows):
        with self.csv_path.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=self.columns)
            writer.writeheader()
            writer.writerows(rows)

    def test_imports_only_steam_indies_and_is_idempotent(self):
        self.write_csv([
            {
                'appid': '12345',
                'name': 'Juego Indie Real',
                'release_date': '21-08-2012',
                'price': '9.99',
                'developers': "['Estudio Real']",
                'publishers': "['Editorial Real']",
                'genres': "['Action', 'Indie']",
            },
            {
                'appid': '67890',
                'name': 'Juego no indie',
                'release_date': '21-08-2012',
                'price': '9.99',
                'developers': "['Estudio']",
                'publishers': "['Editorial']",
                'genres': "['Action']",
            },
            {
                'appid': '12346',
                'name': 'Precio inválido',
                'release_date': '21-08-2012',
                'price': 'NaN',
                'developers': "['Estudio']",
                'publishers': "['Editorial']",
                'genres': "['Indie']",
            },
        ])

        call_command('import_steam_indies', str(self.csv_path), remove_demo_games=True)
        call_command('import_steam_indies', str(self.csv_path))

        game = Game.objects.get(steam_app_id=12345)
        self.assertEqual(Game.objects.filter(steam_app_id__isnull=False).count(), 1)
        self.assertEqual(game.title, 'Juego Indie Real')
        self.assertEqual(game.studio, 'Estudio Real')
        self.assertEqual(game.year, 2012)
        self.assertNotIn('Indie', game.genre_list())
        self.assertFalse(Game.objects.filter(title='Sendero de luciérnagas').exists())

    def test_dry_run_does_not_change_games(self):
        before = Game.objects.count()
        self.write_csv([{
            'appid': '12345',
            'name': 'Juego Indie Real',
            'release_date': '21-08-2012',
            'price': '9.99',
            'developers': "['Estudio Real']",
            'publishers': "['Editorial Real']",
            'genres': "['Indie']",
        }])

        call_command('import_steam_indies', str(self.csv_path), dry_run=True)

        self.assertEqual(Game.objects.count(), before)
class AuthTests(TestCase):
    def setUp(self):
        self.player = get_user_model().objects.create_user(
            username='jugador', password='clave-segura-123'
        )
        self.admin = get_user_model().objects.create_user(
            username='admin', password='clave-admin-123', is_staff=True
        )
        self.studio_user = get_user_model().objects.create_user(
            username='estudio', password='clave-estudio-123'
        )
        self.enterprise = Enterprise.objects.create(
            user=self.studio_user, studio_name='Lumen Studio'
        )

    def test_login_page_renders(self):
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'login.html')
        self.assertContains(response, 'Iniciar sesión')
        self.assertNotContains(response, 'Administrador')

    def test_login_page_redirects_authenticated_users(self):
        self.client.force_login(self.player)
        response = self.client.get(reverse('login'))
        self.assertRedirects(response, reverse('index'))

    def test_user_login_redirects_home(self):
        response = self.client.post(reverse('login'), {
            'username': 'jugador',
            'password': 'clave-segura-123',
        })
        self.assertRedirects(response, reverse('index'))
        self.assertIn('_auth_user_id', self.client.session)

    def test_staff_login_redirects_to_panel(self):
        response = self.client.post(reverse('login'), {
            'username': 'admin',
            'password': 'clave-admin-123',
        })
        self.assertRedirects(response, reverse('panel_dashboard'), fetch_redirect_response=False)

    def test_enterprise_login_redirects_to_dashboard(self):
        response = self.client.post(reverse('login'), {
            'username': 'estudio',
            'password': 'clave-estudio-123',
        })
        self.assertRedirects(response, reverse('enterprise_dashboard'))

    def test_user_login_honours_safe_next(self):
        response = self.client.post(reverse('login'), {
            'username': 'jugador',
            'password': 'clave-segura-123',
            'next': reverse('biblioteca'),
        })
        self.assertRedirects(response, reverse('biblioteca'))

    def test_user_login_ignores_external_next(self):
        response = self.client.post(reverse('login'), {
            'username': 'jugador',
            'password': 'clave-segura-123',
            'next': 'https://example.com/robar',
        })
        self.assertRedirects(response, reverse('index'))

    def test_invalid_credentials_show_error(self):
        response = self.client.post(reverse('login'), {
            'username': 'jugador',
            'password': 'incorrecta',
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_admin_login_url_redirects_to_site_login(self):
        response = self.client.get('/admin/login/')
        self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)

    def test_logout_requires_post_and_redirects_home(self):
        self.client.force_login(self.player)
        response = self.client.post(reverse('logout'))
        self.assertRedirects(response, reverse('index'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_logout_rejects_get(self):
        self.client.force_login(self.player)
        response = self.client.get(reverse('logout'))
        self.assertEqual(response.status_code, 405)

    def test_nav_shows_login_link_for_guests(self):
        response = self.client.get(reverse('index'))
        self.assertContains(response, reverse('login'))

    def test_nav_shows_logout_form_for_users(self):
        self.client.force_login(self.player)
        response = self.client.get(reverse('index'))
        self.assertContains(response, reverse('logout'))
        self.assertContains(response, 'Salir')

    def test_nav_shows_studio_link_for_enterprises(self):
        self.client.force_login(self.studio_user)
        response = self.client.get(reverse('index'))
        self.assertContains(response, 'Mi estudio')


class EnterprisePortalTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='estudio', password='clave-estudio-123'
        )
        self.enterprise = Enterprise.objects.create(
            user=self.user, studio_name='Lumen Studio'
        )
        self.other_user = get_user_model().objects.create_user(
            username='otro', password='clave-otro-123'
        )
        self.other_enterprise = Enterprise.objects.create(
            user=self.other_user, studio_name='Otro Estudio'
        )

    def test_enterprise_login_page_renders(self):
        response = self.client.get(reverse('enterprise_login'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'enterprise_login.html')

    def test_enterprise_portal_accepts_enterprise(self):
        response = self.client.post(reverse('enterprise_login'), {
            'username': 'estudio',
            'password': 'clave-estudio-123',
        })
        self.assertRedirects(response, reverse('enterprise_dashboard'))

    def test_enterprise_portal_rejects_regular_user(self):
        get_user_model().objects.create_user(
            username='jugador', password='clave-jugador-123'
        )
        response = self.client.post(reverse('enterprise_login'), {
            'username': 'jugador',
            'password': 'clave-jugador-123',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'no es de empresa')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse('enterprise_dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('enterprise_login'), response.url)

    def test_regular_user_cannot_access_dashboard(self):
        regular = get_user_model().objects.create_user(
            username='regular', password='clave-regular-123'
        )
        self.client.force_login(regular)
        response = self.client.get(reverse('enterprise_dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('enterprise_login'))

    def test_dashboard_lists_only_own_games(self):
        Game.objects.create(title='Juego Propio', studio='Lumen Studio', publisher=self.enterprise)
        Game.objects.create(title='Juego Ajeno', studio='Otro Estudio', publisher=self.other_enterprise)
        self.client.force_login(self.user)
        response = self.client.get(reverse('enterprise_dashboard'))
        self.assertContains(response, 'Juego Propio')
        self.assertNotContains(response, 'Juego Ajeno')

    def test_enterprise_can_publish_game(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('enterprise_publish'), {
            'title': 'Mi Nuevo Juego',
            'description': 'Una aventura breve.',
            'genres': 'Aventura, Puzle',
            'year': 2026,
            'price': '4.99',
            'symbol': '✦',
            'tint': '',
        })
        self.assertRedirects(response, reverse('enterprise_dashboard'))
        game = Game.objects.get(title='Mi Nuevo Juego')
        self.assertEqual(game.publisher, self.enterprise)
        self.assertEqual(game.studio, 'Lumen Studio')
        self.assertEqual(game.slug, 'mi-nuevo-juego')

    def test_published_game_appears_in_explorar(self):
        self.client.force_login(self.user)
        self.client.post(reverse('enterprise_publish'), {
            'title': 'Juego Visible',
            'description': '',
            'genres': 'Puzle',
            'year': 2026,
            'price': '0',
            'symbol': '✦',
            'tint': '',
        })
        response = self.client.get(reverse('explorar'))
        self.assertContains(response, 'Juego Visible')

    def test_publish_requires_enterprise_account(self):
        regular = get_user_model().objects.create_user(
            username='regular2', password='clave-regular-123'
        )
        self.client.force_login(regular)
        response = self.client.get(reverse('enterprise_publish'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('enterprise_login'))

    def test_enterprise_registration_creates_account(self):
        response = self.client.post(reverse('enterprise_register'), {
            'studio_name': 'Nuevo Estudio',
            'username': 'nuevo',
            'email': 'nuevo@example.com',
            'website': '',
            'description': '',
            'password1': 'clave-muy-segura-987',
            'password2': 'clave-muy-segura-987',
        })
        self.assertRedirects(response, reverse('enterprise_dashboard'))
        user = get_user_model().objects.get(username='nuevo')
        self.assertTrue(
            Enterprise.objects.filter(user=user, studio_name='Nuevo Estudio').exists()
        )
        self.assertIn('_auth_user_id', self.client.session)

    def test_enterprise_registration_rejects_duplicate_username(self):
        response = self.client.post(reverse('enterprise_register'), {
            'studio_name': 'Otro',
            'username': 'estudio',
            'email': 'duplicado@example.com',
            'website': '',
            'description': '',
            'password1': 'clave-muy-segura-987',
            'password2': 'clave-muy-segura-987',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ya está en uso')

    def test_enterprise_registration_rejects_mismatched_passwords(self):
        response = self.client.post(reverse('enterprise_register'), {
            'studio_name': 'Otro',
            'username': 'nuevo2',
            'email': 'nuevo2@example.com',
            'website': '',
            'description': '',
            'password1': 'clave-muy-segura-987',
            'password2': 'otra-clave-987',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'no coinciden')


class GameSlugTests(TestCase):
    def test_game_slug_is_unique(self):
        first = Game.objects.create(title='Mismo Título', studio='Uno')
        second = Game.objects.create(title='Mismo Título', studio='Dos')
        self.assertEqual(first.slug, 'mismo-titulo')
        self.assertEqual(second.slug, 'mismo-titulo-2')


class StatsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='stats', password='clave-stats-123'
        )
        self.admin = get_user_model().objects.create_user(
            username='statsadmin', password='clave-admin-123', is_staff=True
        )
        LibraryEntry.objects.create(
            user=self.user,
            game=Game.objects.first(),
            status=LibraryEntry.Status.DONE,
        )

    def test_user_stats_requires_login(self):
        response = self.client.get(reverse('estadisticas'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_user_stats_renders_four_charts(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('estadisticas'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Tus estadísticas')
        self.assertContains(response, 'Mi biblioteca por estado')
        self.assertContains(response, 'Mis géneros más guardados')
        self.assertContains(response, 'Mi progreso')
        self.assertContains(response, 'Mi cobertura del catálogo')
        self.assertContains(response, 'Haz clic en un elemento del gráfico')

    def test_user_stats_empty_state(self):
        empty = get_user_model().objects.create_user(
            username='vacio', password='clave-vacio-123'
        )
        self.client.force_login(empty)
        response = self.client.get(reverse('estadisticas'))
        self.assertContains(response, 'Aún no has guardado ningún juego')

    def test_user_stats_values(self):
        stats = user_stats(self.user)
        self.assertEqual(stats['charts'][0]['values'], [0, 0, 1])
        self.assertEqual(stats['charts'][3]['values'][0], 1)
        self.assertEqual(stats['coverage'], round(100 / Game.objects.count()))

        # El gráfico por estado abre un desglose de géneros.
        status_chart = stats['charts'][0]
        self.assertIn('Terminado', status_chart['levels'])
        level = status_chart['levels']['Terminado']
        self.assertEqual(level['type'], 'bar')
        self.assertEqual(len(level['labels']), len(level['values']))

        # Los géneros se desglosan por estado y el progreso por géneros.
        genre_chart = stats['charts'][1]
        first_genre = genre_chart['labels'][0]
        self.assertIn(first_genre, genre_chart['levels'])
        self.assertEqual(len(genre_chart['levels'][first_genre]['values']), 3)

        progress_chart = stats['charts'][2]
        self.assertEqual(
            set(progress_chart['levels']), {'Terminados', 'Pendientes'}
        )

    def test_admin_stats_requires_staff(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('panel_stats'))
        self.assertEqual(response.status_code, 403)

    def test_admin_stats_requires_login(self):
        response = self.client.get(reverse('panel_stats'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_admin_stats_renders_four_charts(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('panel_stats'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Estadísticas')
        self.assertContains(response, 'Juegos por género')
        self.assertContains(response, 'Gratis vs pagos')
        self.assertContains(response, 'Biblioteca global por estado')
        self.assertContains(response, 'Nuevos usuarios por mes')

    def test_admin_stats_values(self):
        stats = admin_stats()
        price_chart = stats['charts'][1]
        self.assertEqual(sum(price_chart['values']), Game.objects.count())
        users_chart = stats['charts'][3]
        self.assertEqual(len(users_chart['labels']), 6)
        self.assertEqual(len(users_chart['values']), 6)

    def test_nav_links_to_stats(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('index'))
        self.assertContains(response, reverse('estadisticas'))

        self.client.force_login(self.admin)
        response = self.client.get(reverse('index'))
        self.assertContains(response, reverse('panel_dashboard'))


class PanelTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user(
            username='staff', password='clave-staff-123', is_staff=True
        )
        self.superuser = User.objects.create_superuser(
            username='super', password='clave-super-123', email='super@example.com'
        )
        self.player = User.objects.create_user(
            username='jugadora', password='clave-jugadora-123'
        )
        self.studio_user = User.objects.create_user(
            username='estudio-panel', password='clave-estudio-123'
        )
        self.enterprise = Enterprise.objects.create(
            user=self.studio_user,
            studio_name='Estudio Panel',
            website='https://panel.example.com',
        )
        self.game = Game.objects.create(
            title='Juego de Panel',
            studio='Estudio Panel',
            genres='Puzzle, Aventura',
            year=2024,
            price=0,
            publisher=self.enterprise,
        )
        self.entry = LibraryEntry.objects.create(
            user=self.player,
            game=self.game,
            status=LibraryEntry.Status.WANT,
        )

    def test_panel_requires_login(self):
        response = self.client.get(reverse('panel_dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_panel_rejects_players(self):
        self.client.force_login(self.player)
        for name in [
            'panel_dashboard', 'panel_games', 'panel_enterprises',
            'panel_users', 'panel_library', 'panel_stats',
        ]:
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 403, name)

    def test_dashboard_renders_sections(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('panel_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'panel/dashboard.html')
        self.assertContains(response, 'Panel de control')
        self.assertContains(response, 'Juego de Panel')
        self.assertContains(response, 'Estudio Panel')
        self.assertContains(response, reverse('admin:index'))

    def test_game_list_filters(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('panel_games'), {'q': 'Panel'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Juego de Panel')

        response = self.client.get(reverse('panel_games'), {'price': 'paid'})
        self.assertNotContains(response, 'Juego de Panel')

    def test_game_create_edit_delete(self):
        self.client.force_login(self.staff)
        response = self.client.post(reverse('panel_game_create'), {
            'title': 'Nuevo Juego',
            'studio': 'Nuevo Estudio',
            'publisher': self.enterprise.id,
            'description': 'Una prueba.',
            'genres': 'Acción',
            'year': 2025,
            'price': '9.99',
            'symbol': '★',
            'tint': '',
        })
        self.assertRedirects(response, reverse('panel_games'))
        game = Game.objects.get(title='Nuevo Juego')
        self.assertEqual(game.publisher, self.enterprise)

        response = self.client.post(reverse('panel_game_edit', args=[game.id]), {
            'title': 'Juego Editado',
            'studio': 'Nuevo Estudio',
            'publisher': '',
            'description': '',
            'genres': 'Acción',
            'year': 2025,
            'price': '0',
            'symbol': '★',
            'tint': '',
        })
        self.assertRedirects(response, reverse('panel_games'))
        game.refresh_from_db()
        self.assertEqual(game.title, 'Juego Editado')
        self.assertIsNone(game.publisher)

        response = self.client.post(reverse('panel_game_delete', args=[game.id]))
        self.assertRedirects(response, reverse('panel_games'))
        self.assertFalse(Game.objects.filter(pk=game.pk).exists())

    def test_game_export(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('panel_games_export'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Type'].startswith('text/csv'))
        self.assertIn('indievault-juegos.csv', response['Content-Disposition'])
        content = response.content.decode('utf-8-sig')
        self.assertIn('Título,Estudio,Empresa', content)
        self.assertIn('Juego de Panel', content)

    def test_enterprise_verify_and_edit(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse('panel_enterprise_verify', args=[self.enterprise.id])
        )
        self.assertRedirects(response, reverse('panel_enterprises'))
        self.enterprise.refresh_from_db()
        self.assertTrue(self.enterprise.is_verified)

        response = self.client.post(
            reverse('panel_enterprise_edit', args=[self.enterprise.id]),
            {
                'studio_name': 'Estudio Renombrado',
                'website': 'https://nuevo.example.com',
                'description': 'Perfil actualizado.',
                'is_verified': 'on',
            },
        )
        self.assertRedirects(response, reverse('panel_enterprises'))
        self.enterprise.refresh_from_db()
        self.assertEqual(self.enterprise.studio_name, 'Estudio Renombrado')
        self.assertTrue(self.enterprise.is_verified)

    def test_enterprise_export(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('panel_enterprises_export'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Type'].startswith('text/csv'))
        content = response.content.decode('utf-8-sig')
        self.assertIn('Estudio,Usuario,Correo', content)
        self.assertIn('Estudio Panel', content)

    def test_user_active_toggle(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse('panel_user_toggle_active', args=[self.player.id])
        )
        self.assertRedirects(response, reverse('panel_users'))
        self.player.refresh_from_db()
        self.assertFalse(self.player.is_active)

        self.client.post(reverse('panel_user_toggle_active', args=[self.player.id]))
        self.player.refresh_from_db()
        self.assertTrue(self.player.is_active)

    def test_user_cannot_deactivate_self(self):
        self.client.force_login(self.staff)
        self.client.post(reverse('panel_user_toggle_active', args=[self.staff.id]))
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.is_active)

    def test_staff_toggle_requires_superuser(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse('panel_user_toggle_staff', args=[self.player.id])
        )
        self.assertEqual(response.status_code, 403)
        self.player.refresh_from_db()
        self.assertFalse(self.player.is_staff)

        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse('panel_user_toggle_staff', args=[self.player.id])
        )
        self.assertRedirects(response, reverse('panel_users'))
        self.player.refresh_from_db()
        self.assertTrue(self.player.is_staff)

    def test_user_export(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('panel_users_export'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Type'].startswith('text/csv'))
        content = response.content.decode('utf-8-sig')
        self.assertIn('Usuario,Correo,Nombre', content)
        self.assertIn('jugadora', content)

    def test_library_status_and_delete(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse('panel_library_status', args=[self.entry.id]),
            {'status': LibraryEntry.Status.DONE},
        )
        self.assertRedirects(response, reverse('panel_library'))
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.status, LibraryEntry.Status.DONE)

        response = self.client.post(
            reverse('panel_library_delete', args=[self.entry.id])
        )
        self.assertRedirects(response, reverse('panel_library'))
        self.assertFalse(LibraryEntry.objects.filter(pk=self.entry.pk).exists())

    def test_library_rejects_invalid_status(self):
        self.client.force_login(self.staff)
        self.client.post(
            reverse('panel_library_status', args=[self.entry.id]),
            {'status': 'Inventado'},
        )
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.status, LibraryEntry.Status.WANT)

    def test_library_export(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('panel_library_export'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Type'].startswith('text/csv'))
        content = response.content.decode('utf-8-sig')
        self.assertIn('Usuario,Juego,Estado', content)
        self.assertIn('jugadora', content)

    def test_export_requires_staff(self):
        self.client.force_login(self.player)
        response = self.client.get(reverse('panel_games_export'))
        self.assertEqual(response.status_code, 403)


class ProfileTests(TestCase):
    tiny_png = base64.b64decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk'
        '+A8AAQUBAScY42YAAAAASUVORK5CYII='
    )

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='perfil', password='clave-perfil-123'
        )

    def test_profile_created_with_user(self):
        self.assertTrue(Profile.objects.filter(user=self.user).exists())

    def test_profile_requires_login(self):
        response = self.client.get(reverse('perfil'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_profile_page_renders(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('perfil'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Mi perfil')
        self.assertContains(response, 'Foto de perfil')

    def test_profile_updates_data_and_avatar(self):
        self.client.force_login(self.user)
        avatar = SimpleUploadedFile(
            'avatar.png', self.tiny_png, content_type='image/png'
        )

        response = self.client.post(reverse('perfil'), {
            'first_name': 'Ada',
            'last_name': 'Lovelace',
            'email': 'ada@example.com',
            'bio': 'Exploradora de mundos pequeños.',
            'avatar': avatar,
        })

        self.assertRedirects(response, reverse('perfil'))
        self.user.refresh_from_db()
        profile = Profile.objects.get(user=self.user)
        self.assertEqual(self.user.first_name, 'Ada')
        self.assertEqual(self.user.last_name, 'Lovelace')
        self.assertEqual(self.user.email, 'ada@example.com')
        self.assertEqual(profile.bio, 'Exploradora de mundos pequeños.')
        self.assertTrue(profile.avatar_data)
        self.assertEqual(profile.avatar_mime, 'image/jpeg')
        self.assertEqual(profile.avatar_version, 1)
        self.assertEqual(profile.avatar, '')

    def test_avatar_is_served_from_database(self):
        self.client.force_login(self.user)
        self.client.post(reverse('perfil'), {
            'avatar': SimpleUploadedFile('avatar.png', self.tiny_png, content_type='image/png'),
        })

        response = self.client.get(reverse('profile_avatar', args=[self.user.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/jpeg')
        self.assertTrue(response.content.startswith(b'\xff\xd8'))
        self.assertIn('immutable', response['Cache-Control'])

    def test_avatar_url_uses_stored_photo(self):
        self.client.force_login(self.user)
        self.client.post(reverse('perfil'), {
            'avatar': SimpleUploadedFile('avatar.png', self.tiny_png, content_type='image/png'),
        })

        user = get_user_model().objects.get(pk=self.user.pk)
        url = avatar_url(user)
        self.assertTrue(url.startswith(reverse('profile_avatar', args=[self.user.id])))
        self.assertIn('?v=1', url)

    def test_avatar_url_falls_back_to_legacy_file(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                profile = Profile.objects.get(user=self.user)
                profile.avatar.save('vieja.png', ContentFile(self.tiny_png), save=True)
                user = get_user_model().objects.get(pk=self.user.pk)
                self.assertTrue(avatar_url(user).startswith('/media/avatars/'))

    def test_invalid_avatar_is_rejected(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('perfil'), {
            'avatar': SimpleUploadedFile(
                'texto.png', b'esto no es una imagen', content_type='image/png'
            ),
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('avatar', response.context['form'].errors)
        self.assertFalse(Profile.objects.get(user=self.user).avatar_data)

    def test_import_avatars_command_moves_legacy_photo(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                profile = Profile.objects.get(user=self.user)
                profile.avatar.save('vieja.png', ContentFile(self.tiny_png), save=True)

                call_command('import_avatars')

                profile.refresh_from_db()
                self.assertTrue(profile.avatar_data)
                self.assertEqual(profile.avatar_mime, 'image/jpeg')
                self.assertEqual(profile.avatar_version, 1)
                self.assertTrue(default_storage.exists(profile.avatar.name))


class StaffExperienceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user(
            username='staff-experiencia', password='clave-staff-123', is_staff=True
        )
        self.player = User.objects.create_user(
            username='jugador-experiencia', password='clave-jugador-123'
        )

    def test_staff_login_ignores_next(self):
        response = self.client.post(reverse('login'), {
            'username': 'staff-experiencia',
            'password': 'clave-staff-123',
            'next': reverse('explorar'),
        })
        self.assertRedirects(
            response, reverse('panel_dashboard'), fetch_redirect_response=False
        )

    def test_staff_cannot_open_personal_library(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('biblioteca'))
        self.assertRedirects(response, reverse('panel_dashboard'))

    def test_staff_cannot_open_personal_stats(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('estadisticas'))
        self.assertRedirects(response, reverse('panel_stats'))


class AtypicalStatsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user(
            username='staff-graficos', password='clave-staff-123', is_staff=True
        )
        Game.objects.create(
            title='Juego Radar', studio='Estudio Radar', genres='Puzzle, Aventura',
            year=2020, price=9.99,
        )
        Game.objects.create(
            title='Juego Mosaico', studio='Estudio Mosaico', genres='Acción',
            year=2024, price=0,
        )

    def test_admin_stats_contains_atypical_charts(self):
        chart_types = {chart['type'] for chart in admin_stats()['charts']}
        self.assertTrue(
            {'radar', 'polarArea', 'bubble', 'heatmap', 'mosaic'}.issubset(chart_types)
        )

    def test_admin_charts_have_drilldown_levels(self):
        charts = {chart['id']: chart for chart in admin_stats()['charts']}

        genre_levels = charts['admin-genres']['levels']
        self.assertIn('Puzzle', genre_levels)
        self.assertEqual(genre_levels['Puzzle']['type'], 'bar')
        self.assertEqual(
            len(genre_levels['Puzzle']['labels']),
            len(genre_levels['Puzzle']['values']),
        )

        price_levels = charts['admin-price']['levels']
        self.assertEqual(set(price_levels), {'Gratis', 'Pagos'})
        self.assertTrue(price_levels['Gratis']['labels'])

        decade_levels = charts['admin-decades']['levels']
        self.assertIn('2020s', decade_levels)
        self.assertIn('2020', decade_levels['2020s']['labels'])
        self.assertIn('2024', decade_levels['2020s']['labels'])

        user_levels = charts['admin-users']['levels']
        self.assertEqual(len(user_levels), 6)
        first_month = next(iter(user_levels.values()))
        self.assertEqual(len(first_month['labels']), 7)

    def test_admin_stats_renders_drilldown_hint(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('panel_stats'))
        self.assertContains(response, 'Haz clic en un elemento del gráfico')
        self.assertContains(response, 'chart-level')

    def test_dashboard_renders_charts(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('panel_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ADN del catálogo')
        self.assertContains(response, 'Altas por día y mes')
        self.assertContains(response, 'Estudios líderes')
        self.assertContains(response, 'chart-specs')


class PersonalizationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='afinidad', password='clave-afinidad-123'
        )
        self.client.force_login(self.user)
        LibraryEntry.objects.create(
            user=self.user, game=Game.objects.get(title='Cripta de vidrio')
        )

    def test_index_suggests_games_from_library_genres(self):
        response = self.client.get(reverse('index'))
        html = response.content.decode()
        self.assertContains(response, 'Elegidos para ti')
        self.assertContains(response, 'Porque te gustan Puzle')
        self.assertIn('Taller de engranajes', html)
        self.assertNotIn('Cripta de vidrio', html)

    def test_index_without_library_has_no_suggestions(self):
        other = get_user_model().objects.create_user(
            username='sin-biblioteca', password='clave-sin-123'
        )
        self.client.force_login(other)
        response = self.client.get(reverse('index'))
        self.assertNotContains(response, 'Elegidos para ti')
        self.assertContains(response, 'Tu biblioteca está esperando su primer título')

    def test_guest_index_has_no_suggestions(self):
        self.client.logout()
        response = self.client.get(reverse('index'))
        self.assertNotContains(response, 'Elegidos para ti')

    def test_indie_is_hidden_from_filters_and_urls(self):
        self.assertNotContains(self.client.get(reverse('explorar')), 'genre=Indie')
        html = self.client.get(
            reverse('explorar'), {'genre': 'indie'}
        ).content.decode()
        self.assertIn('Sendero de luciérnagas', html)


class AppearanceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='paleta', password='clave-paleta-123'
        )

    def test_appearance_requires_login(self):
        response = self.client.get(reverse('apariencia'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_appearance_page_renders(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('apariencia'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Color de acento')
        self.assertContains(response, 'Vista previa')

    def test_manual_accent_is_saved_and_applied(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('apariencia'), {'accent': '#ff0000'})
        self.assertRedirects(response, reverse('apariencia'))

        profile = Profile.objects.get(user=self.user)
        self.assertEqual(profile.accent, '#ff0000')
        self.assertFalse(profile.auto_accent)
        self.assertContains(self.client.get(reverse('index')), '--accent-dark:')

    def test_invalid_accent_is_rejected(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('apariencia'), {'accent': 'naranja'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Usa un color en formato #rrggbb')
        self.assertEqual(Profile.objects.get(user=self.user).accent, '')

    def test_auto_accent_uses_avatar_colour(self):
        buffer = BytesIO()
        PILImage.new('RGB', (40, 40), (200, 30, 40)).save(buffer, format='PNG')
        self.client.force_login(self.user)

        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                profile = Profile.objects.get(user=self.user)
                profile.avatar.save(
                    'rojo.png', ContentFile(buffer.getvalue()), save=True
                )
                response = self.client.post(reverse('apariencia'), {
                    'auto_accent': 'on',
                    'accent': '#000000',
                })
                self.assertRedirects(response, reverse('apariencia'))
                profile.refresh_from_db()
                accent = profile.accent

        self.assertTrue(profile.auto_accent)
        self.assertRegex(accent, r'^#[0-9a-f]{6}$')
        red, green, blue = (int(accent[i:i + 2], 16) for i in (1, 3, 5))
        self.assertGreater(red, green)
        self.assertGreater(red, blue)

    def test_auto_accent_uses_uploaded_photo(self):
        buffer = BytesIO()
        PILImage.new('RGB', (120, 120), (30, 90, 210)).save(buffer, format='PNG')
        self.client.force_login(self.user)

        response = self.client.post(reverse('perfil'), {
            'avatar': SimpleUploadedFile(
                'azul.png', buffer.getvalue(), content_type='image/png'
            ),
        })
        self.assertRedirects(response, reverse('perfil'))

        profile = Profile.objects.get(user=self.user)
        accent = profile.accent
        self.assertRegex(accent, r'^#[0-9a-f]{6}$')
        red, green, blue = (int(accent[i:i + 2], 16) for i in (1, 3, 5))
        self.assertGreater(blue, red)
