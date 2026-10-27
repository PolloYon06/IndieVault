from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .models import Enterprise, Game, LibraryEntry
from .stats import admin_stats, user_stats


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
