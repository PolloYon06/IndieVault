import base64
import csv
import json
import tempfile
from io import BytesIO, StringIO
from pathlib import Path
from time import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connection
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from PIL import Image as PILImage

from .models import (
    Discussion,
    DiscussionReply,
    Enterprise,
    Game,
    LibraryEntry,
    Profile,
)
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
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse('explorar'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'explorar_descubrir.html')
        self.assertContains(response, 'Explora nuevos <span>mundos</span>')
        self.assertContains(response, 'Catálogo completo')
        self.assertContains(response, f'href="{reverse("explorar_catalogo")}">Explorar todos los juegos')
        for title in ('Elegidos para ti', 'Recién añadidos', 'Gratis para jugar', 'Según tu presupuesto'):
            self.assertContains(response, title)
        self.assertNotContains(response, 'class="game-grid"')
        self.assertNotContains(response, 'class="filter-form"')
        self.assertFalse(any(Game._meta.db_table in query['sql'] for query in queries))

    def test_legacy_explore_links_redirect_preserving_query(self):
        query = '?q=Cripta&genre=Puzle&sort=az&price=free&page=1'
        response = self.client.get(reverse('explorar') + query)
        self.assertRedirects(response, reverse('explorar_catalogo') + query)
        catalog = self.client.get(response.url)
        self.assertContains(catalog, 'Cripta de vidrio')
        self.assertContains(catalog, 'class="active" aria-current="page">Explorar')

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
        html = self.client.get(reverse('explorar_catalogo')).content.decode()
        self.assertIn('Añadir a biblioteca', html)
        self.assertNotIn('Quitar de la biblioteca', html)

    def test_catalog_shows_remove_for_saved_game(self):
        game = Game.objects.first()
        LibraryEntry.objects.create(
            user=self.user, game=game, status=LibraryEntry.Status.WANT
        )
        html = self.client.get(reverse('explorar_catalogo')).content.decode()
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
        return self.client.get(reverse('explorar_catalogo'), params).content.decode()

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

    def test_search_by_studio(self):
        game = Game.objects.create(title='Otro título', studio='Estudio Nébula', price=5)
        response = self.client.get(reverse('explorar_catalogo'), {'q': 'Nébula'})
        self.assertEqual(list(response.context['games']), [game])
        self.assertNotContains(response, 'aria-label="Paginación del catálogo"')

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

    def test_explore_heading_reflects_catalogue_filters(self):
        cases = (
            ({'q': 'faro', 'sort': 'az'}, 'Encuentra tu próximo <span>mundo</span>'),
            ({'genre': 'Puzle'}, 'Explora juegos de <span>Puzle</span>'),
            ({'price': 'free'}, 'Descubre juegos <span>gratuitos</span>'),
            ({'price': '10'}, 'Descubre juegos por <span>menos de $10</span>'),
            ({'genre': 'Inexistente'}, 'Encuentra tu próximo <span>mundo</span>'),
            ({'price': 'NaN'}, 'Encuentra tu próximo <span>mundo</span>'),
        )
        for params, heading in cases:
            with self.subTest(params=params):
                response = self.client.get(reverse('explorar_catalogo'), params)
                self.assertContains(response, f'<h1 id="page-title">{heading}</h1>', html=True)
                self.assertContains(response, 'Volver a descubrir')

        response = self.client.get(reverse('explorar_catalogo'), {'genre': 'Puzle', 'price': 'free'})
        self.assertContains(response, 'Explora juegos de <span>Puzle</span>')
        self.assertContains(response, 'Encuentra juegos independientes gratis de la categoría Puzle.')
        self.assertContains(response, f'href="{reverse("explorar_catalogo")}?price=free">Todos</a>')

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

        first_page = self.client.get(reverse('explorar_catalogo'))
        second_page = self.client.get(reverse('explorar_catalogo'), {'page': 2})

        self.assertEqual(len(first_page.context['games']), 24)
        self.assertEqual(len(second_page.context['games']), 1)
        self.assertContains(first_page, 'Página 1 de 2')
        self.assertContains(second_page, 'Página 2 de 2')
        self.assertContains(first_page, 'disabled>Anterior')
        self.assertContains(second_page, 'disabled>Siguiente')
        self.assertContains(first_page, 'Volver a descubrir')
        self.assertContains(second_page, 'Encuentra tu próximo <span>mundo</span>')
        self.assertContains(second_page, 'Volver a descubrir')

    def test_pagination_keeps_filters_and_genre_links_reset_page(self):
        Game.objects.bulk_create([
            Game(
                title='Título de prueba',
                slug=f'prueba-paginacion-{index}',
                studio='Estudio',
                genres='Puzle,Aventura',
                price=5,
            )
            for index in range(241)
        ])
        params = {'q': 'Título de prueba', 'genre': 'Puzle', 'sort': 'price_asc', 'price': '10', 'page': 5}
        response = self.client.get(reverse('explorar_catalogo'), params)
        self.assertEqual(response.context['page_range'], [1, None, 4, 5, 6, None, 11])
        self.assertContains(response, 'aria-current="page" aria-label="Página 5"')
        self.assertContains(response, 'aria-label="Primera página"')
        self.assertContains(response, 'aria-label="Última página"')
        self.assertContains(
            response,
            '?q=T%C3%ADtulo+de+prueba&amp;genre=Puzle&amp;sort=price_asc&amp;price=10&amp;page=6#catalogo',
        )
        self.assertContains(
            response,
            '?q=T%C3%ADtulo+de+prueba&amp;genre=Aventura&amp;sort=price_asc&amp;price=10"',
        )
        self.assertContains(response, f'action="{reverse("explorar_catalogo")}"')
        next_page = self.client.get(reverse('explorar_catalogo'), {**params, 'page': 6})
        current_ids = {game.pk for game in response.context['games']}
        next_ids = {game.pk for game in next_page.context['games']}
        self.assertEqual(len(current_ids), 24)
        self.assertEqual(len(next_ids), 24)
        self.assertLess(max(current_ids), min(next_ids))
        self.assertEqual(self.client.get(reverse('explorar_catalogo'), {**params, 'page': 999}).context['games'].number, 11)

    def test_invalid_page_and_price_fall_back_to_defaults(self):
        for page, price in [('texto', 'texto'), ('0', 'NaN'), ('-2', 'Infinity'), ('', '-5')]:
            with self.subTest(page=page, price=price):
                response = self.client.get(reverse('explorar_catalogo'), {'page': page, 'price': price})
                self.assertEqual(response.context['games'].number, 1)
                self.assertEqual(response.context['price'], '')
                self.assertEqual(response.context['games'].paginator.count, Game.objects.count())

    def test_numeric_price_caps_keep_strict_upper_bound(self):
        Game.objects.create(title='Prueba de límite', studio='Estudio', price=5)
        self.assertNotIn('Prueba de límite', self.page(price='5'))
        self.assertIn('Prueba de límite', self.page(price='5.001'))
        self.assertIn('Prueba de límite', self.page(price='1e1000000'))

    def test_discovery_links_open_added_and_free_collections(self):
        recent = [
            Game.objects.create(title=f'Alta {i}', studio='Estudio', year=2000, price=0) for i in range(4)
        ]
        user = get_user_model().objects.create_user(username='discoverer')
        LibraryEntry.objects.create(user=user, game=recent[-1], status=LibraryEntry.Status.DONE)
        self.client.force_login(user)

        catalog_url = reverse('explorar_catalogo')
        landing = self.client.get(reverse('explorar'))
        self.assertContains(landing, f'href="{catalog_url}?sort=added"')
        self.assertContains(landing, f'href="{catalog_url}?price=free"')
        added = self.client.get(catalog_url, {'sort': 'added'})
        self.assertEqual(list(added.context['games'])[:4], recent[::-1])
        self.assertContains(added, 'Las últimas <span>incorporaciones</span>')
        self.assertContains(added, reverse('remove_from_library', args=[recent[-1].pk]))
        self.assertContains(added, reverse('add_to_library', args=[recent[0].pk]))
        self.assertContains(added, 'Volver a descubrir')
        launched = self.client.get(catalog_url, {'sort': 'newest'})
        self.assertNotIn(launched.context['games'][0], recent)
        free = self.client.get(catalog_url, {'price': 'free'})
        self.assertIn(recent[-1], free.context['games'])
        self.assertTrue(all(game.is_free() for game in free.context['games']))

    def test_discovery_budget_links_to_real_catalog_price_filters(self):
        sample_games = [
            Game.objects.create(title=f'Límite {index}', studio='Estudio', price=price, genres='Acción,Simulation')
            for index, price in enumerate(('0', '4.99', '5', '10', '15', '15.01'))
        ]
        url = reverse('explorar_catalogo')
        landing = self.client.get(reverse('explorar'))
        self.assertNotContains(landing, '?genre=')

        cases = (
            ('free', sample_games[:1], 'gratuitos'),
            ('5', sample_games[1:2], 'menos de $5'),
            ('5-15', sample_games[2:5], 'entre $5 y $15'),
            ('over-15', sample_games[5:], 'más de $15'),
        )
        for price, expected_games, heading in cases:
            with self.subTest(price=price):
                self.assertContains(landing, f'href="{url}?price={price}"')
                results = self.client.get(url, {'price': price, 'q': 'Límite'})
                self.assertEqual(list(results.context['games']), expected_games)
                self.assertContains(results, f'<span>{heading}</span>')
                self.assertNotContains(results, 'class="explore-discovery"')


class RecommendationTests(TestCase):
    def setUp(self):
        cache.clear()
        Game.objects.all().delete()
        self.catalog_url = reverse('explorar_catalogo')
        self.url = f'{self.catalog_url}?coleccion=para-ti'
        self.member = get_user_model().objects.create_user(username='recomendaciones')

    def game(self, title, genres, price=5):
        return Game.objects.create(title=title, studio='Estudio de prueba', genres=genres, price=price)

    def page_url(self, response, page):
        params = response.context['pagination_params'].copy()
        params['page'] = page
        return f'{self.catalog_url}?{params.urlencode()}'

    def test_recommendations_use_all_three_statuses_and_full_genre_labels(self):
        matches = [
            self.game('Coincide aventura', 'Aventura, Narrativa', price=0),
            self.game('Coincide RPG', '  Puzle, rpg  , Narrativa'),
            self.game('Coincide acción', 'Acción'),
            self.game('Coincide alternativa', 'Acción, Indie'),
        ]
        self.game('Coincidencia parcial RPG', 'JRPG, RPG táctico')
        self.game('Coincidencia parcial acción', 'Acción táctica')
        self.game('Coincidencia parcial aventura', 'Aventura gráfica')
        self.game('Género fuera de los tres primeros', 'Terror, Indie')
        saved = [
            self.game('Pendiente', 'Acción, acción, RPG, Terror, Terror, Terror, Indie'),
            self.game('En curso', 'Acción, Aventura'),
            self.game('Terminado', 'Acción, RPG'),
        ]
        for game, status in zip(saved, LibraryEntry.Status.values):
            LibraryEntry.objects.create(user=self.member, game=game, status=status)
        self.client.force_login(self.member)
        response = self.client.get(self.url)

        self.assertEqual(list(response.context['games']), matches[::-1])
        self.assertContains(response, 'Aventuras <span>para ti</span>')
        self.assertContains(response, 'Porque te gustan los juegos de Acción, RPG y Aventura.')
        self.assertContains(response, reverse('add_to_library', args=[matches[0].pk]))
        self.assertContains(response, reverse('game_detail', args=[matches[0].slug]))

    def test_recommendations_handle_literal_punctuation_and_paginate_at_most_200(self):
        saved = self.game('Guardado', 'C++')
        LibraryEntry.objects.create(user=self.member, game=saved)
        matches = Game.objects.bulk_create([
            Game(title=f'Coincide {index}', slug=f'coincide-{index}', studio='Estudio', genres=' C++ ', price=0)
            for index in range(208)
        ])
        self.game('No es la misma etiqueta', 'C+, C+++')
        self.client.force_login(self.member)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.url)
        expected = matches[-200:][::-1]
        self.assertEqual(list(response.context['games']), expected[:16])
        self.assertEqual(response.context['games'].paginator.count, 200)
        recommendation_queries = [query['sql'] for query in queries if 'REGEXP' in query['sql']]
        self.assertEqual(len(recommendation_queries), 1)
        self.assertIn('LIMIT 200', recommendation_queries[0])
        second_url = self.page_url(response, 2)
        query = second_url.split('?', 1)[1].replace('&', '&amp;')
        self.assertContains(response, f'href="?{query}#catalogo" rel="next"')
        self.assertContains(response, 'aria-current="page" aria-label="Página 1"')
        self.assertContains(response, 'Porque te gustan los juegos de C++.')
        with CaptureQueriesContext(connection) as subsequent_queries:
            second = self.client.get(second_url)
            last = self.client.get(self.page_url(second, 13))
        self.assertEqual(list(second.context['games']), expected[16:32])
        self.assertEqual(list(last.context['games']), expected[192:])
        self.assertContains(second, 'aria-current="page" aria-label="Página 2"')
        self.assertContains(last, 'disabled>Siguiente')
        self.assertFalse(any('REGEXP' in query['sql'] for query in subsequent_queries))

        filtered = self.client.get(f'{self.url}&q=Coincide+207&price=free')
        self.assertEqual(list(filtered.context['games']), [matches[-1]])
        self.assertContains(filtered, 'name="coleccion" value="para-ti"')

    def test_saving_a_recommendation_refreshes_the_candidate_pool(self):
        saved = self.game('Guardado', 'Acción')
        LibraryEntry.objects.create(user=self.member, game=saved)
        candidate = self.game('Candidato', 'Acción')
        backup = self.game('Alternativa', 'Acción')
        self.client.force_login(self.member)
        self.assertEqual(list(self.client.get(self.url).context['games']), [backup, candidate])
        self.client.post(reverse('add_to_library', args=[backup.pk]))
        self.assertEqual(list(self.client.get(self.url).context['games']), [candidate])

    def test_library_changes_restart_old_links_with_filters(self):
        saved = self.game('Guardado', 'Acción')
        LibraryEntry.objects.create(user=self.member, game=saved)
        candidates = [self.game(f'Juego {index}', 'Acción', price=0) for index in range(21)]
        self.client.force_login(self.member)
        filtered_url = self.url + '&q=Juego&genre=Acci%C3%B3n&price=free&sort=added'
        initial = self.client.get(filtered_url)
        old_second_url = self.page_url(initial, 2)
        top_game = candidates[-1]

        self.client.post(reverse('add_to_library', args=[top_game.pk]))
        updated = self.client.get(old_second_url, follow=True)
        self.assertEqual(updated.redirect_chain, [(filtered_url, 302)])
        self.assertEqual(updated.context['games'].number, 1)
        self.assertNotIn(top_game, updated.context['games'])
        new_second_url = self.page_url(updated, 2)
        second = self.client.get(new_second_url)
        self.assertEqual(second.context['games'].number, 2)
        self.assertFalse(set(updated.context['games']) & set(second.context['games']))

        self.client.post(reverse('remove_from_library', args=[top_game.pk]))
        restored = self.client.get(new_second_url, follow=True)
        self.assertEqual(restored.redirect_chain, [(filtered_url, 302)])
        self.assertIn(top_game, restored.context['games'])
        self.assertRedirects(self.client.get(old_second_url), filtered_url)

    def test_changed_genres_restart_an_old_page(self):
        saved = self.game('Guardado', 'Acción')
        LibraryEntry.objects.create(user=self.member, game=saved)
        for index in range(17):
            self.game(f'Acción {index}', 'Acción')
        candidate = self.game('Alternativa puzle', 'Puzle')
        self.client.force_login(self.member)
        old_second_url = self.page_url(self.client.get(self.url), 2)

        saved.genres = 'Puzle'
        saved.save(update_fields=['genres'])
        updated = self.client.get(old_second_url, follow=True)
        self.assertEqual(updated.redirect_chain, [(self.url, 302)])
        self.assertEqual(updated.context['recommendation_genres'], 'Puzle')
        self.assertEqual(list(updated.context['games']), [candidate])

    def test_selection_version_survives_worker_cache_miss_only_if_the_selection_matches(self):
        saved = self.game('Guardado', 'Acción')
        LibraryEntry.objects.create(user=self.member, game=saved)
        for index in range(20):
            self.game(f'Juego {index}', 'Acción')
        self.client.force_login(self.member)
        first = self.client.get(self.url)
        old_second_url = self.page_url(first, 2)

        cache.clear()
        second = self.client.get(old_second_url)
        self.assertEqual(second.context['games'].number, 2)
        self.assertEqual(self.page_url(second, 2), old_second_url)
        self.assertFalse(set(first.context['games']) & set(second.context['games']))

        self.game('Juego recién añadido', 'Acción')
        cache.clear()
        self.assertRedirects(self.client.get(old_second_url), self.url)

    def test_live_price_changes_restart_an_old_sorted_page_without_recomputing_candidates(self):
        saved = self.game('Guardado', 'Acción')
        LibraryEntry.objects.create(user=self.member, game=saved)
        candidates = [self.game(f'Juego {index}', 'Acción') for index in range(20)]
        self.client.force_login(self.member)
        sorted_url = self.url + '&sort=price_asc'
        old_second_url = self.page_url(self.client.get(sorted_url), 2)
        Game.objects.filter(pk=candidates[-1].pk).update(price=0)

        with CaptureQueriesContext(connection) as queries:
            updated = self.client.get(old_second_url, follow=True)
        self.assertEqual(updated.redirect_chain, [(sorted_url, 302)])
        self.assertEqual(updated.context['games'][0], candidates[-1])
        self.assertFalse(any('REGEXP' in query['sql'] for query in queries))

    def test_expired_selection_and_unversioned_page_return_to_first_page(self):
        saved = self.game('Guardado', 'Acción')
        LibraryEntry.objects.create(user=self.member, game=saved)
        for index in range(20):
            self.game(f'Juego {index}', 'Acción')
        self.client.force_login(self.member)
        first = self.client.get(self.url)
        old_second_url = self.page_url(first, 2)
        self.assertRedirects(self.client.get(f'{self.url}&page=2'), self.url)
        tampered = first.context['pagination_params'].copy()
        tampered['version_recomendaciones'] += 'x'
        tampered['page'] = 2
        self.assertRedirects(self.client.get(self.catalog_url, tampered), self.url)

        with patch('IndieVault.views.time', return_value=time() + 121):
            with CaptureQueriesContext(connection) as queries:
                refreshed = self.client.get(old_second_url, follow=True)
            self.assertEqual(refreshed.redirect_chain, [(self.url, 302)])
            self.assertEqual(refreshed.context['games'].number, 1)
            self.assertNotEqual(self.page_url(refreshed, 2), old_second_url)
            self.assertEqual(sum('REGEXP' in query['sql'] for query in queries), 1)

    def test_versions_are_bound_to_each_user_even_with_identical_candidates(self):
        other_user = get_user_model().objects.create_user(username='otra-cuenta')
        saved = self.game('Guardado', 'Acción')
        for user in (self.member, other_user):
            LibraryEntry.objects.create(user=user, game=saved)
        for index in range(20):
            self.game(f'Juego {index}', 'Acción')
        self.client.force_login(self.member)
        first = self.client.get(self.url)
        member_second_url = self.page_url(first, 2)
        other = Client()
        other.force_login(other_user)
        other_first = other.get(member_second_url, follow=True)
        self.assertEqual(other_first.redirect_chain, [(self.url, 302)])
        self.assertEqual(list(other_first.context['games']), list(first.context['games']))
        self.assertNotEqual(self.page_url(other_first, 2), member_second_url)
        self.assertEqual(self.client.get(member_second_url).context['games'].number, 2)

    def test_member_without_usable_recommendations_gets_a_compact_invitation(self):
        self.client.force_login(self.member)
        self.assertContains(self.client.get(self.url), 'Guarda juegos del catálogo')
        for title, genres in [('Género ignorado', 'Indie,  '), ('Sin candidatos', 'Puzle')]:
            game = self.game(title, genres)
            LibraryEntry.objects.create(user=self.member, game=game)
            response = self.client.get(self.url)
            self.assertContains(response, 'Guarda juegos del catálogo')
            self.assertNotContains(response, 'class="game-card"')
            self.assertContains(response, 'Ver catálogo completo')

    def test_guest_and_staff_skip_library_queries(self):
        staff = get_user_model().objects.create_user(username='equipo', is_staff=True)
        game = self.game('Juego guardado por un administrador', 'Acción')
        LibraryEntry.objects.create(user=staff, game=game)
        with CaptureQueriesContext(connection) as guest_queries:
            landing = self.client.get(reverse('explorar'))
            guest = self.client.get(self.url)
        self.assertContains(landing, 'Inicia sesión para recibir recomendaciones')
        self.assertContains(landing, guest.url)
        self.assertEqual(guest.status_code, 302)
        self.assertTrue(guest.url.startswith(reverse('login')))

        self.client.force_login(staff)
        with CaptureQueriesContext(connection) as staff_queries:
            landing = self.client.get(reverse('explorar'))
            redirect = self.client.get(self.url)
            admin = self.client.get(self.catalog_url)
        self.assertNotContains(landing, 'Elegidos para ti')
        self.assertRedirects(redirect, self.catalog_url)
        self.assertContains(admin, reverse('panel_game_edit', args=[game.pk]))
        for queries in (guest_queries, staff_queries):
            self.assertFalse(any(LibraryEntry._meta.db_table in query['sql'] for query in queries))

    def test_filtered_catalog_skips_personalized_discovery(self):
        saved = self.game('Guardado', 'Acción')
        LibraryEntry.objects.create(user=self.member, game=saved)
        candidate = self.game('Candidato', 'Acción')
        self.client.force_login(self.member)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.catalog_url, {'genre': 'Acción'})
        self.assertEqual(list(response.context['games']), [saved, candidate])
        self.assertContains(response, 'Volver a descubrir')
        self.assertNotContains(response, 'Aventuras <span>para ti</span>')
        self.assertEqual(sum(LibraryEntry._meta.db_table in query['sql'] for query in queries), 1)


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
        response = self.client.get(reverse('explorar_catalogo'))
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


class HomeProgressTests(SimpleTestCase):
    def test_guest_home_links_to_catalog_without_querying_it(self):
        response = self.client.get(reverse('index'))
        self.assertContains(response, 'Los mundos pequeños,')
        self.assertContains(
            response,
            'Descubre videojuegos independientes, organiza tu biblioteca y '
            'comparte tus experiencias con otros jugadores',
        )
        self.assertContains(response, reverse('explorar'))
        self.assertContains(response, reverse('biblioteca'))
        self.assertContains(response, reverse('community'))
        self.assertContains(response, 'home-action-library')
        self.assertNotContains(response, 'home-actions-pair')
        self.assertNotContains(response, 'Tu aventura continúa')
        self.assertNotContains(response, 'Lo último del catálogo')

    def test_staff_home_prioritizes_panel_without_querying_library(self):
        staff = get_user_model()(username='admin', is_staff=True)
        with patch('django.contrib.auth.middleware.get_user', return_value=staff):
            response = self.client.get(reverse('index'))

        self.assertContains(response, 'Panel de control')
        self.assertContains(response, reverse('panel_dashboard'))
        self.assertContains(response, 'Abrir el panel')
        self.assertContains(response, 'home-actions-pair')
        self.assertNotContains(response, 'Tu aventura continúa')
        self.assertNotContains(response, 'Mi biblioteca')

    @patch('IndieVault.views.LibraryEntry.objects.filter')
    def test_home_displays_playing_games_and_summary(self, filter_entries):
        user = get_user_model()(username='jugadora')
        entries = filter_entries.return_value
        entries.aggregate.return_value = {
            'saved_count': 11, 'pending_count': 2, 'playing_count': 5, 'finished_count': 4,
        }
        playing = entries.filter.return_value.select_related.return_value.order_by.return_value
        game = Game(title='Cripta de vidrio', slug='cripta-de-vidrio', steam_app_id=123)
        playing.__getitem__.return_value = [LibraryEntry(game=game)]

        with patch('django.contrib.auth.middleware.get_user', return_value=user):
            response = self.client.get(reverse('index'))

        filter_entries.assert_called_once_with(user=response.wsgi_request.user)
        entries.filter.assert_called_once_with(status=LibraryEntry.Status.PLAYING)
        playing.__getitem__.assert_called_once_with(slice(None, 3))
        self.assertContains(response, 'Tu aventura continúa')
        self.assertContains(response, 'Ir a mi biblioteca')
        self.assertContains(response, 'home-actions-pair')
        self.assertNotContains(response, 'home-action-library')
        self.assertContains(response, 'Cripta de vidrio')
        self.assertContains(response, reverse('game_detail', args=[game.slug]))
        self.assertContains(response, 'header.jpg')
        self.assertContains(response, '<dt>Pendientes</dt><dd>2</dd>', html=True)
        self.assertContains(response, '<dt>En curso</dt><dd>5</dd>', html=True)
        self.assertContains(response, '<span class="home-playing-status">En curso</span>', html=True)
        self.assertContains(response, '<dt>Terminados</dt><dd>4</dd>', html=True)

    @patch('IndieVault.views.LibraryEntry.objects.filter')
    def test_empty_progress_invites_player_to_use_library(self, filter_entries):
        user = get_user_model()(username='jugadora')
        entries = filter_entries.return_value
        playing = entries.filter.return_value.select_related.return_value.order_by.return_value
        playing.__getitem__.return_value = []

        for pending_count in (0, 1):
            with self.subTest(pending_count=pending_count):
                entries.aggregate.return_value = {
                    'saved_count': pending_count, 'pending_count': pending_count,
                    'playing_count': 0, 'finished_count': 0,
                }
                with patch('django.contrib.auth.middleware.get_user', return_value=user):
                    response = self.client.get(reverse('index'))

                self.assertContains(response, 'Marca un juego como «En curso»')
                self.assertNotContains(response, 'aria-label="Juegos en curso"')
                if pending_count:
                    self.assertContains(response, 'Ir a mi biblioteca')
                    self.assertContains(response, 'home-actions-pair')
                    self.assertNotContains(response, 'home-action-library')
                else:
                    self.assertNotContains(response, 'Ir a mi biblioteca')
                    self.assertNotContains(response, 'home-actions-pair')
                    self.assertContains(response, 'home-action-library')


class PersonalizationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='afinidad', password='clave-afinidad-123'
        )
        self.client.force_login(self.user)
        LibraryEntry.objects.create(
            user=self.user, game=Game.objects.get(title='Cripta de vidrio')
        )

    def test_indie_is_hidden_from_filters_and_urls(self):
        self.assertNotContains(self.client.get(reverse('explorar_catalogo')), 'genre=Indie')
        html = self.client.get(
            reverse('explorar_catalogo'), {'genre': 'indie'}
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


class AccountCreationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.User = get_user_model()
        self.staff = self.User.objects.create_user(
            username='cuentas-staff',
            password='ClaveStaff-2026!',
            is_staff=True,
        )
        self.player = self.User.objects.create_user(
            username='cuentas-jugador',
            password='ClaveJugador-2026!',
        )

    def test_register_page_has_username_and_password_but_no_email(self):
        response = self.client.get(reverse('register'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'register.html')
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="password1"')
        self.assertContains(response, 'name="password2"')
        self.assertNotContains(response, 'name="email"')

    def test_register_creates_user_without_email_and_logs_in(self):
        response = self.client.post(reverse('register'), {
            'username': 'nueva-cuenta',
            'password1': 'ClaveNueva-2026!',
            'password2': 'ClaveNueva-2026!',
        })
        self.assertRedirects(response, reverse('index'))
        account = self.User.objects.get(username='nueva-cuenta')
        self.assertEqual(account.email, '')
        self.assertIn('_auth_user_id', self.client.session)
        self.assertTrue(Profile.objects.filter(user=account).exists())

    def test_register_rejects_duplicate_username_ignoring_case(self):
        self.User.objects.create_user(
            username='CuentaUnica', password='ClaveUnica-2026!'
        )
        response = self.client.post(reverse('register'), {
            'username': 'cuentaunica',
            'password1': 'ClaveNueva-2026!',
            'password2': 'ClaveNueva-2026!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('username', response.context['form'].errors)

    def test_register_rejects_weak_password(self):
        response = self.client.post(reverse('register'), {
            'username': 'clave-debil',
            'password1': '12345678',
            'password2': '12345678',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.User.objects.filter(username='clave-debil').exists())
        self.assertTrue(
            response.context['form'].errors.get('password1')
            or response.context['form'].errors.get('password2')
        )

    def test_register_rejects_mismatched_passwords(self):
        response = self.client.post(reverse('register'), {
            'username': 'clave-distinta',
            'password1': 'ClaveNueva-2026!',
            'password2': 'OtraClave-2026!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.User.objects.filter(username='clave-distinta').exists())

    def test_panel_account_create_requires_staff(self):
        self.client.force_login(self.player)
        response = self.client.get(reverse('panel_user_create'))
        self.assertEqual(response.status_code, 403)

    def test_panel_account_create_makes_player_without_email(self):
        self.client.force_login(self.staff)
        response = self.client.post(reverse('panel_user_create'), {
            'username': 'panel-jugador',
            'password1': 'ClavePanel-2026!',
            'password2': 'ClavePanel-2026!',
        })
        self.assertRedirects(response, reverse('panel_users'))
        account = self.User.objects.get(username='panel-jugador')
        self.assertEqual(account.email, '')
        self.assertFalse(account.is_staff)

    def test_panel_account_create_can_mark_staff(self):
        self.client.force_login(self.staff)
        response = self.client.post(reverse('panel_user_create'), {
            'username': 'panel-staff',
            'password1': 'ClavePanel-2026!',
            'password2': 'ClavePanel-2026!',
            'is_staff': 'on',
        })
        self.assertRedirects(response, reverse('panel_users'))
        self.assertTrue(self.User.objects.get(username='panel-staff').is_staff)


class CommunityTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            username='foro', password='ClaveForo-2026!'
        )
        self.other = self.User.objects.create_user(
            username='foro-otro', password='ClaveForo-2026!'
        )
        self.staff = self.User.objects.create_user(
            username='foro-staff', password='ClaveForo-2026!', is_staff=True
        )
        self.game = Game.objects.first()
        self.client = Client()

    def make_thread(self, **overrides):
        data = {
            'game': self.game,
            'author': self.user,
            'title': 'Tema de prueba',
            'body': 'Un cuerpo suficientemente largo para la comunidad.',
            'category': Discussion.Category.GENERAL,
        }
        data.update(overrides)
        return Discussion.objects.create(**data)

    def test_community_page_is_public(self):
        thread = self.make_thread()
        response = self.client.get(reverse('community'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'community.html')
        self.assertContains(response, thread.title)

    def test_game_community_page_is_public(self):
        thread = self.make_thread()
        response = self.client.get(reverse('game_community', args=[self.game.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, thread.title)

    def test_create_thread_requires_login(self):
        response = self.client.get(reverse('discussion_create'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_create_general_thread(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('discussion_create'), {
            'title': '¿Qué juego me recomiendan?',
            'body': 'Busco algo corto y narrativo para el fin de semana.',
            'category': Discussion.Category.HELP,
        })
        thread = Discussion.objects.get(title='¿Qué juego me recomiendan?')
        self.assertRedirects(response, reverse('discussion_detail', args=[thread.pk]))
        self.assertEqual(thread.author, self.user)
        self.assertIsNone(thread.game)
        self.assertEqual(thread.category, Discussion.Category.HELP)

    def test_create_game_thread(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('game_discussion_create', args=[self.game.slug]),
            {
                'title': 'Comparto mi final',
                'body': 'Me encantó la última parte de este juego.',
                'category': Discussion.Category.GENERAL,
            },
        )
        thread = Discussion.objects.get(title='Comparto mi final')
        self.assertRedirects(response, reverse('discussion_detail', args=[thread.pk]))
        self.assertEqual(thread.game, self.game)

    def test_invalid_thread_is_not_created(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('discussion_create'), {
            'title': 'x',
            'body': 'corto',
            'category': Discussion.Category.GENERAL,
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Discussion.objects.exists())

    def test_reply_updates_activity_and_renders(self):
        thread = self.make_thread()
        before = thread.last_activity_at
        self.client.force_login(self.other)
        response = self.client.post(
            reverse('discussion_reply', args=[thread.pk]),
            {'body': 'Yo también lo jugué y me gustó.'},
        )
        self.assertEqual(response.status_code, 302)
        thread.refresh_from_db()
        self.assertGreater(thread.last_activity_at, before)
        reply = thread.replies.get()
        self.assertEqual(reply.author, self.other)
        self.assertContains(
            self.client.get(reverse('discussion_detail', args=[thread.pk])),
            'Yo también lo jugué y me gustó.',
        )

    def test_locked_thread_rejects_replies(self):
        thread = self.make_thread(is_locked=True)
        self.client.force_login(self.user)
        self.client.post(
            reverse('discussion_reply', args=[thread.pk]),
            {'body': 'Esto no debería publicarse.'},
        )
        self.assertEqual(thread.replies.count(), 0)

    def test_author_can_delete_thread(self):
        thread = self.make_thread()
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('discussion_delete', args=[thread.pk])
        )
        self.assertRedirects(response, reverse('game_community', args=[self.game.slug]))
        self.assertFalse(Discussion.objects.filter(pk=thread.pk).exists())

    def test_other_user_cannot_delete_thread(self):
        thread = self.make_thread()
        self.client.force_login(self.other)
        response = self.client.post(
            reverse('discussion_delete', args=[thread.pk])
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Discussion.objects.filter(pk=thread.pk).exists())

    def test_author_can_delete_reply(self):
        thread = self.make_thread()
        reply = DiscussionReply.objects.create(
            discussion=thread, author=self.user, body='Comentario propio.'
        )
        self.client.force_login(self.user)
        response = self.client.post(reverse('reply_delete', args=[reply.pk]))
        self.assertRedirects(
            response, reverse('discussion_detail', args=[thread.pk])
        )
        self.assertFalse(DiscussionReply.objects.filter(pk=reply.pk).exists())

    def test_staff_can_pin_and_lock_thread(self):
        thread = self.make_thread()
        self.client.force_login(self.staff)

        self.client.post(
            reverse('discussion_moderate', args=[thread.pk]),
            {'action': 'pin'},
        )
        self.client.post(
            reverse('discussion_moderate', args=[thread.pk]),
            {'action': 'lock'},
        )

        thread.refresh_from_db()
        self.assertTrue(thread.is_pinned)
        self.assertTrue(thread.is_locked)

    def test_game_detail_shows_community_preview(self):
        thread = self.make_thread()
        DiscussionReply.objects.create(
            discussion=thread,
            author=self.other,
            body='Un comentario reciente para la ficha.',
        )
        response = self.client.get(reverse('game_detail', args=[self.game.slug]))
        self.assertContains(response, 'Habla de')
        self.assertContains(response, thread.title)
        self.assertContains(response, 'Un comentario reciente para la ficha.')

    def test_community_filters_by_category(self):
        self.make_thread(title='Tema general')
        self.make_thread(
            title='Tema de ayuda',
            category=Discussion.Category.HELP,
        )
        response = self.client.get(reverse('community'), {'category': 'Ayuda'})
        self.assertContains(response, 'Tema de ayuda')
        self.assertNotContains(response, 'Tema general')


class PrivacyTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.owner = self.User.objects.create_user(
            username='privacidad', password='ClavePrivada-2026!'
        )
        self.member = self.User.objects.create_user(
            username='miembro', password='ClaveMiembro-2026!'
        )
        self.staff = self.User.objects.create_user(
            username='privacidad-staff',
            password='ClaveStaff-2026!',
            is_staff=True,
        )
        self.profile = Profile.objects.get(user=self.owner)
        self.profile.bio = 'Bio visible para quien corresponda.'
        self.profile.save(update_fields=['bio'])
        self.game = Game.objects.first()
        self.client = Client()

    def test_default_visibility_is_members(self):
        self.assertEqual(self.profile.visibility, Profile.Visibility.MEMBERS)

    def test_anonymous_cannot_see_members_profile(self):
        response = self.client.get(
            reverse('public_profile', args=[self.owner.username])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'solo está visible para cuentas registradas')
        self.assertNotContains(response, 'Bio visible para quien corresponda.')

    def test_member_sees_members_profile(self):
        self.client.force_login(self.member)
        response = self.client.get(
            reverse('public_profile', args=[self.owner.username])
        )
        self.assertContains(response, 'Bio visible para quien corresponda.')

    def test_public_profile_is_visible_to_anonymous(self):
        self.profile.visibility = Profile.Visibility.PUBLIC
        self.profile.save(update_fields=['visibility'])
        response = self.client.get(
            reverse('public_profile', args=[self.owner.username])
        )
        self.assertContains(response, 'Bio visible para quien corresponda.')

    def test_private_profile_is_hidden_from_members(self):
        self.profile.visibility = Profile.Visibility.PRIVATE
        self.profile.save(update_fields=['visibility'])
        self.client.force_login(self.member)
        response = self.client.get(
            reverse('public_profile', args=[self.owner.username])
        )
        self.assertContains(response, 'Perfil privado')
        self.assertNotContains(response, 'Bio visible para quien corresponda.')

    def test_owner_sees_own_private_profile(self):
        self.profile.visibility = Profile.Visibility.PRIVATE
        self.profile.save(update_fields=['visibility'])
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse('public_profile', args=[self.owner.username])
        )
        self.assertContains(response, 'Bio visible para quien corresponda.')
        self.assertContains(response, 'Así ve tu perfil')

    def test_hidden_sections_do_not_render(self):
        LibraryEntry.objects.create(
            user=self.owner,
            game=self.game,
            status=LibraryEntry.Status.DONE,
        )
        thread = Discussion.objects.create(
            game=self.game,
            author=self.owner,
            title='Tema que no debe verse',
            body='Cuerpo del tema que no debe verse en el perfil.',
        )
        self.profile.visibility = Profile.Visibility.PUBLIC
        self.profile.show_library = False
        self.profile.show_stats = False
        self.profile.show_discussions = False
        self.profile.save(update_fields=[
            'visibility', 'show_library', 'show_stats', 'show_discussions',
        ])

        response = self.client.get(
            reverse('public_profile', args=[self.owner.username])
        )
        self.assertNotContains(response, self.game.title)
        self.assertNotContains(response, thread.title)
        self.assertContains(response, 'Perfil sin secciones públicas')

    def test_privacy_form_updates_settings(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse('privacy'), {
            'visibility': Profile.Visibility.PUBLIC,
            'show_stats': 'on',
        })
        self.assertRedirects(response, reverse('privacy'))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.visibility, Profile.Visibility.PUBLIC)
        self.assertTrue(self.profile.show_stats)
        self.assertFalse(self.profile.show_library)
        self.assertFalse(self.profile.show_discussions)

    def test_account_export_contains_data_and_no_password(self):
        LibraryEntry.objects.create(
            user=self.owner,
            game=self.game,
            status=LibraryEntry.Status.PLAYING,
        )
        Discussion.objects.create(
            game=self.game,
            author=self.owner,
            title='Tema exportable',
            body='Contenido del tema exportable.',
        )
        self.client.force_login(self.owner)
        response = self.client.get(reverse('account_export'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('application/json', response['Content-Type'])
        payload = json.loads(response.content)
        self.assertEqual(payload['cuenta']['usuario'], 'privacidad')
        self.assertEqual(payload['biblioteca'][0]['juego'], self.game.title)
        self.assertEqual(payload['temas'][0]['titulo'], 'Tema exportable')
        self.assertNotIn('password', response.content.decode().lower())


class SecurityTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            username='seguridad', password='ClaveSegura-2026!'
        )
        self.client = Client()

    def test_security_requires_login(self):
        response = self.client.get(reverse('security'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_security_page_renders_password_and_sessions(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('security'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Cambiar contraseña')
        self.assertContains(response, 'Sesiones activas')
        self.assertContains(response, 'Esta sesión')

    def test_password_change_keeps_current_session(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('security'), {
            'old_password': 'ClaveSegura-2026!',
            'new_password1': 'NuevaClave-2026!',
            'new_password2': 'NuevaClave-2026!',
        })
        self.assertRedirects(response, reverse('security'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NuevaClave-2026!'))
        self.assertEqual(self.client.get(reverse('security')).status_code, 200)

    def test_password_change_rejects_wrong_current_password(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('security'), {
            'old_password': 'incorrecta',
            'new_password1': 'NuevaClave-2026!',
            'new_password2': 'NuevaClave-2026!',
        })
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('ClaveSegura-2026!'))

    def test_close_other_sessions_keeps_current(self):
        first = Client()
        second = Client()
        first.force_login(self.user)
        second.force_login(self.user)

        response = first.post(reverse('close_other_sessions'))
        self.assertRedirects(response, reverse('security'))
        self.assertEqual(first.get(reverse('security')).status_code, 200)
        self.assertEqual(second.get(reverse('perfil')).status_code, 302)

    def test_close_all_sessions_logs_everywhere_out(self):
        first = Client()
        second = Client()
        first.force_login(self.user)
        second.force_login(self.user)

        response = first.post(reverse('close_all_sessions'))
        self.assertRedirects(response, reverse('index'))
        self.assertEqual(first.get(reverse('perfil')).status_code, 302)
        self.assertEqual(second.get(reverse('perfil')).status_code, 302)


class RoleDashboardsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user(
            username='admin-dash', password='clave-admin-123', is_staff=True
        )
        self.player = User.objects.create_user(
            username='jugador-dash', password='clave-jugador-123'
        )
        self.studio_user = User.objects.create_user(
            username='estudio-dash', password='clave-estudio-123'
        )
        self.enterprise = Enterprise.objects.create(
            user=self.studio_user,
            studio_name='Aurora Indie',
            website='https://aurora.example.com',
            is_verified=False,
        )
        self.other_user = User.objects.create_user(
            username='otro-estudio-dash', password='clave-estudio-123'
        )
        self.other_enterprise = Enterprise.objects.create(
            user=self.other_user,
            studio_name='Norte Digital',
            is_verified=True,
        )
        self.game = Game.objects.create(
            title='Ecos del Sur',
            studio='Aurora Indie',
            description='Aventura narrativa.',
            genres='Aventura, Narrativo',
            year=2026,
            price='5.99',
            publisher=self.enterprise,
        )
        self.other_game = Game.objects.create(
            title='Horizonte Cero',
            studio='Norte Digital',
            description='',
            genres='',
            year=2026,
            price=0,
            publisher=self.other_enterprise,
        )
        self.playing_entry = LibraryEntry.objects.create(
            user=self.player,
            game=self.game,
            status=LibraryEntry.Status.PLAYING,
        )
        self.discussion = Discussion.objects.create(
            game=self.game,
            author=self.player,
            title='Duda con el capítulo final',
            body='¿Cómo se desbloquea el epílogo?',
            category=Discussion.Category.HELP,
        )
        DiscussionReply.objects.create(
            discussion=self.discussion,
            author=self.studio_user,
            body='Conseguí las tres llaves ocultas.',
        )

    def test_enterprise_dashboard_shows_kpis_verification_and_community(self):
        self.client.force_login(self.studio_user)
        response = self.client.get(reverse('enterprise_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Verificación en revisión')
        self.assertContains(response, 'En bibliotecas')
        self.assertContains(response, '1 en biblioteca · 1 en curso · 0 terminados')
        self.assertContains(response, 'Duda con el capítulo final')
        self.assertContains(response, reverse('enterprise_game_edit', args=[self.game.id]))

        self.enterprise.is_verified = True
        self.enterprise.save(update_fields=['is_verified'])
        response = self.client.get(reverse('enterprise_dashboard'))
        self.assertContains(response, 'Estudio verificado')

    def test_enterprise_can_edit_own_game_and_not_others(self):
        self.client.force_login(self.studio_user)
        edit_url = reverse('enterprise_game_edit', args=[self.game.id])
        response = self.client.get(edit_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Guardar cambios')

        response = self.client.post(edit_url, {
            'title': 'Ecos del Sur: Edición Definitiva',
            'description': 'Aventura narrativa expandida.',
            'genres': 'Aventura, Puzle',
            'year': 2026,
            'price': '7.99',
            'symbol': '◈',
            'tint': '',
        })
        self.assertRedirects(response, reverse('enterprise_dashboard'))
        self.game.refresh_from_db()
        self.assertEqual(self.game.title, 'Ecos del Sur: Edición Definitiva')
        self.assertEqual(self.game.publisher, self.enterprise)
        self.assertEqual(self.game.studio, 'Aurora Indie')

        forbidden_url = reverse('enterprise_game_edit', args=[self.other_game.id])
        self.assertEqual(self.client.get(forbidden_url).status_code, 404)

    def test_player_dashboard_shows_kpis_quick_resume_and_community(self):
        self.client.force_login(self.player)
        response = self.client.get(reverse('estadisticas'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Continuar jugando')
        self.assertContains(response, 'Ecos del Sur')
        self.assertContains(response, 'Marcar terminado')
        self.assertContains(response, 'Tu actividad en comunidad')
        self.assertContains(response, 'Duda con el capítulo final')
        self.assertContains(
            response,
            reverse('update_library_status', args=[self.playing_entry.id]),
        )

    def test_admin_dashboard_supports_time_ranges_and_catalog_health(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('panel_dashboard'), {'range': '7d'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['range_key'], '7d')
        self.assertContains(response, 'Salud del catálogo:')
        self.assertContains(response, 'Últimos temas')
        self.assertContains(response, 'Duda con el capítulo final')

        response_all = self.client.get(reverse('panel_dashboard'), {'range': 'all'})
        self.assertEqual(response_all.status_code, 200)
        self.assertEqual(response_all.context['range_key'], 'all')
        self.assertContains(response_all, 'respuestas totales')

        response_invalid = self.client.get(reverse('panel_dashboard'), {'range': 'invalid'})
        self.assertEqual(response_invalid.context['range_key'], '30d')


class SeedDemoCommandTests(TestCase):
    def test_seed_demo_creates_player_studio_and_clears_cleanly(self):
        User = get_user_model()
        initial_games = Game.objects.count()
        initial_users = User.objects.count()

        out = StringIO()
        call_command(
            'seed_demo',
            users=5,
            threads=3,
            password='ClaveDemo-2026!',
            stdout=out,
        )

        presenter = User.objects.get(username='demo_presentacion')
        studio_user = User.objects.get(username='demo_estudio')
        self.assertTrue(presenter.check_password('ClaveDemo-2026!'))
        self.assertTrue(studio_user.check_password('ClaveDemo-2026!'))
        self.assertTrue(studio_user.enterprise.is_verified)
        self.assertEqual(Game.objects.filter(title__startswith='[DEMO] ').count(), 3)
        self.assertGreaterEqual(LibraryEntry.objects.filter(user=presenter).count(), 3)
        self.assertEqual(Discussion.objects.filter(title__startswith='[DEMO] ').count(), 3)

        # El panel de empresa y el de jugador funcionan con las cuentas demo.
        self.client.force_login(studio_user)
        studio_resp = self.client.get(reverse('enterprise_dashboard'))
        self.assertEqual(studio_resp.status_code, 200)
        self.assertContains(studio_resp, 'Estudio verificado')
        self.assertContains(studio_resp, '[DEMO] Ecos del Sur')

        self.client.force_login(presenter)
        player_resp = self.client.get(reverse('estadisticas'))
        self.assertEqual(player_resp.status_code, 200)
        self.assertContains(player_resp, 'Continuar jugando')

        # --clear borra todos los datos demo y preserva el catálogo real.
        call_command('seed_demo', clear=True, stdout=StringIO())
        self.assertEqual(User.objects.filter(username__startswith='demo_').count(), 0)
        self.assertEqual(Game.objects.filter(title__startswith='[DEMO] ').count(), 0)
        self.assertEqual(Game.objects.count(), initial_games)
        self.assertEqual(User.objects.count(), initial_users)
