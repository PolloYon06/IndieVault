from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .models import Discussion, DiscussionReply, Enterprise, Game


class PresentationQuickWinsTests(TestCase):
    """Pruebas de Área 1: filtro de estudios, insignia oficial y preview de comunidad."""

    def setUp(self):
        self.client = Client()
        User = get_user_model()

        self.player = User.objects.create_user(
            username='jugadora-area1',
            password='ClaveArea1-2026!',
        )
        self.studio_user = User.objects.create_user(
            username='estudio-area1',
            password='ClaveArea1-2026!',
        )
        self.enterprise = Enterprise.objects.create(
            user=self.studio_user,
            studio_name='Estudio Boreal',
            is_verified=True,
        )

        self.other_studio_user = User.objects.create_user(
            username='otro-estudio-area1',
            password='ClaveArea1-2026!',
        )
        self.other_enterprise = Enterprise.objects.create(
            user=self.other_studio_user,
            studio_name='Taller Austral',
            is_verified=False,
        )

        self.studio_game = Game.objects.create(
            title='Bruma del Sur',
            studio=self.enterprise.studio_name,
            description='Aventura publicada directamente en IndieVault.',
            genres='Aventura, Puzle',
            year=2026,
            price='7.50',
            publisher=self.enterprise,
        )
        self.unverified_studio_game = Game.objects.create(
            title='Pulso Mecánico',
            studio=self.other_enterprise.studio_name,
            description='Prototipo publicado por estudio aún no verificado.',
            genres='Acción',
            year=2026,
            price='0',
            publisher=self.other_enterprise,
        )
        self.imported_game = Game.objects.create(
            title='Reliquia Importada',
            studio='Estudio Externo',
            description='Juego importado sin empresa asociada en IndieVault.',
            genres='Aventura',
            year=2024,
            price='4.99',
            publisher=None,
        )

    def test_explorar_redirects_source_studios_preserving_querystring(self):
        response = self.client.get(
            reverse('explorar'),
            {'source': 'studios', 'sort': 'az'},
        )
        self.assertRedirects(
            response,
            f"{reverse('explorar_catalogo')}?source=studios&sort=az",
        )

    def test_explorar_catalogo_filters_published_by_studios(self):
        catalog_url = reverse('explorar_catalogo')
        response = self.client.get(catalog_url, {'source': 'studios'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['source'], 'studios')

        returned_games = list(response.context['games'])
        self.assertIn(self.studio_game, returned_games)
        self.assertIn(self.unverified_studio_game, returned_games)
        self.assertNotIn(self.imported_game, returned_games)
        self.assertTrue(all(g.publisher_id is not None for g in returned_games))

        self.assertContains(response, 'Publicados en <span>IndieVault</span>', html=True)
        self.assertContains(
            response,
            '<input type="hidden" name="source" value="studios">',
            html=True,
        )
        self.assertContains(response, 'aria-label="Filtrar por origen"')
        self.assertContains(response, 'Todo el catálogo')
        self.assertContains(response, 'Publicados en IndieVault')

        invalid = self.client.get(catalog_url, {'source': 'desconocido'})
        self.assertEqual(invalid.context['source'], '')
        self.assertIn(self.imported_game, list(invalid.context['games']))
        self.assertNotContains(invalid, 'name="source"')

    def test_official_developer_badge_on_discussion_detail_author_and_replies(self):
        dev_thread = Discussion.objects.create(
            game=self.studio_game,
            author=self.studio_user,
            title='Notas del parche 1.1',
            body='Compartimos las mejoras de rendimiento de esta versión.',
            category=Discussion.Category.GENERAL,
        )
        DiscussionReply.objects.create(
            discussion=dev_thread,
            author=self.player,
            body='¡Gracias por la actualización!',
        )
        DiscussionReply.objects.create(
            discussion=dev_thread,
            author=self.other_studio_user,
            body='Felicitaciones desde otro estudio.',
        )
        DiscussionReply.objects.create(
            discussion=dev_thread,
            author=self.studio_user,
            body='Seguiremos atentos a sus reportes.',
        )

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse('discussion_detail', args=[dev_thread.pk]))
        self.assertEqual(response.status_code, 200)
        # Aparece exactamente 2 veces: autor del hilo + respuesta del mismo desarrollador.
        self.assertContains(
            response,
            '<span class="badge ok">✓ Desarrollador oficial</span>',
            count=2,
            html=True,
        )
        enterprise_queries = [
            q['sql'] for q in queries
            if Enterprise._meta.db_table in q['sql'] and 'JOIN' not in q['sql'].upper()
        ]
        self.assertEqual(enterprise_queries, [])

    def test_official_developer_badge_absent_for_players_other_studios_and_general_threads(self):
        player_thread = Discussion.objects.create(
            game=self.studio_game,
            author=self.player,
            title='Busco consejos para el primer capítulo',
            body='¿Alguna recomendación sin spoilers?',
            category=Discussion.Category.HELP,
        )
        DiscussionReply.objects.create(
            discussion=player_thread,
            author=self.other_studio_user,
            body='A mí me sirvió explorar el mapa lateral.',
        )
        response = self.client.get(reverse('discussion_detail', args=[player_thread.pk]))
        self.assertNotContains(response, '✓ Desarrollador oficial')

        imported_thread = Discussion.objects.create(
            game=self.imported_game,
            author=self.studio_user,
            title='Hilo en juego importado',
            body='Comentando como jugador en un juego sin estudio registrado.',
        )
        response_imported = self.client.get(
            reverse('discussion_detail', args=[imported_thread.pk])
        )
        self.assertNotContains(response_imported, '✓ Desarrollador oficial')

        general_thread = Discussion.objects.create(
            game=None,
            author=self.studio_user,
            title='Presentación en el foro general',
            body='Hola a toda la comunidad de IndieVault.',
        )
        response_general = self.client.get(
            reverse('discussion_detail', args=[general_thread.pk])
        )
        self.assertNotContains(response_general, '✓ Desarrollador oficial')

    def test_game_detail_shows_publisher_badges_and_enriched_community_preview(self):
        thread = Discussion.objects.create(
            game=self.studio_game,
            author=self.player,
            title='Guía de coleccionables',
            body='Lista completa de objetos ocultos por región.',
            category=Discussion.Category.GUIDES,
        )
        DiscussionReply.objects.create(
            discussion=thread,
            author=self.player,
            body='Me faltaba el último cristal.',
        )
        DiscussionReply.objects.create(
            discussion=thread,
            author=self.other_studio_user,
            body='Gran trabajo recopilando todo.',
        )
        DiscussionReply.objects.create(
            discussion=thread,
            author=self.studio_user,
            body='¡Excelente guía! Añadiremos pistas opcionales pronto.',
        )

        response = self.client.get(reverse('game_detail', args=[self.studio_game.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            '<span class="badge lilac">Publicado en IndieVault · Estudio Boreal</span>',
            html=True,
        )
        self.assertContains(
            response,
            '<span class="badge ok">✓ Estudio verificado</span>',
            html=True,
        )
        self.assertContains(
            response,
            'Ver o debatir en comunidad (1 tema)',
        )
        self.assertContains(
            response,
            '<span class="badge">Guías</span>',
            html=True,
        )
        self.assertContains(
            response,
            '<span class="badge ok">✓ Desarrollador oficial</span>',
            count=1,
            html=True,
        )

        # Estudio no verificado: muestra sello de publicado en IndieVault, pero NO verificado.
        unverified_resp = self.client.get(
            reverse('game_detail', args=[self.unverified_studio_game.slug])
        )
        self.assertContains(
            unverified_resp,
            'Publicado en IndieVault · Taller Austral',
        )
        self.assertNotContains(unverified_resp, '✓ Estudio verificado')
        self.assertContains(
            unverified_resp,
            'Ver o debatir en comunidad (0 temas)',
        )

        # Juego importado sin publisher: no muestra bloque .detail-publisher.
        imported_resp = self.client.get(
            reverse('game_detail', args=[self.imported_game.slug])
        )
        self.assertNotContains(imported_resp, 'Publicado en IndieVault ·')
        self.assertNotContains(imported_resp, 'detail-publisher')
