from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.template.loader import render_to_string
from django.test import Client, RequestFactory, SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .models import (
    Discussion,
    DiscussionReply,
    Enterprise,
    Game,
    LibraryEntry,
    LibraryReview,
    Notification,
    Profile,
)
from .platform_views import get_game_rating_context


class RatingAndReviewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username='critico', password='ClaveSegura-2026!'
        )
        self.other = User.objects.create_user(
            username='otro-critico', password='ClaveSegura-2026!'
        )
        self.staff = User.objects.create_user(
            username='staff-critico', password='ClaveSegura-2026!', is_staff=True
        )
        self.game = Game.objects.create(
            title='Bosque de Ámbar',
            studio='Estudio Bruma',
            genres='Aventura, Puzle',
            year=2026,
            price='9.99',
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_rate_done_entry_saves_rating_and_trimmed_review(self):
        entry = LibraryEntry.objects.create(
            user=self.user,
            game=self.game,
            status=LibraryEntry.Status.DONE,
        )
        response = self.client.post(
            reverse('rate_library_entry', args=[entry.pk]),
            {'rating': '5', 'review': '  Una joya inolvidable.  '},
        )
        self.assertRedirects(response, reverse('biblioteca'))
        entry.refresh_from_db()
        self.assertEqual(entry.rating, 5)
        self.assertEqual(entry.review, 'Una joya inolvidable.')

        # Limpiar valoración con cadena vacía borra nota y micro-reseña.
        response = self.client.post(
            reverse('rate_library_entry', args=[entry.pk]),
            {'rating': '', 'review': 'Texto previo que se limpia'},
        )
        self.assertRedirects(response, reverse('biblioteca'))
        entry.refresh_from_db()
        self.assertIsNone(entry.rating)
        self.assertEqual(entry.review, '')

    def test_cannot_rate_unless_status_is_done(self):
        for status in (LibraryEntry.Status.WANT, LibraryEntry.Status.PLAYING):
            with self.subTest(status=status):
                entry, _ = LibraryEntry.objects.update_or_create(
                    user=self.user,
                    game=self.game,
                    defaults={'status': status},
                )
                LibraryReview.objects.filter(entry=entry).delete()
                response = self.client.post(
                    reverse('rate_library_entry', args=[entry.pk]),
                    {'rating': '4', 'review': 'Intento antes de terminar'},
                    follow=True,
                )
                self.assertContains(response, 'Terminado')
                entry.refresh_from_db()
                self.assertIsNone(entry.rating)
                self.assertEqual(entry.review, '')

    def test_rejects_out_of_range_ratings_and_overlong_reviews(self):
        entry = LibraryEntry.objects.create(
            user=self.user,
            game=self.game,
            status=LibraryEntry.Status.DONE,
        )
        url = reverse('rate_library_entry', args=[entry.pk])

        for invalid_rating in ('0', '6', '-2', 'cinco'):
            with self.subTest(rating=invalid_rating):
                self.client.post(url, {'rating': invalid_rating, 'review': 'Texto'})
                entry.refresh_from_db()
                self.assertIsNone(entry.rating)

        self.client.post(url, {'rating': '4', 'review': 'x' * 281})
        entry.refresh_from_db()
        self.assertIsNone(entry.rating)
        self.assertEqual(entry.review, '')

    def test_permissions_login_post_ownership_staff_and_safe_referer(self):
        other_entry = LibraryEntry.objects.create(
            user=self.other,
            game=self.game,
            status=LibraryEntry.Status.DONE,
        )
        own_entry = LibraryEntry.objects.create(
            user=self.user,
            game=Game.objects.create(title='Otro Juego', studio='Estudio'),
            status=LibraryEntry.Status.DONE,
        )

        # No puede valorar la entrada de otra cuenta.
        self.assertEqual(
            self.client.post(
                reverse('rate_library_entry', args=[other_entry.pk]),
                {'rating': '5'},
            ).status_code,
            404,
        )

        # GET rechazado con 405.
        self.assertEqual(
            self.client.get(reverse('rate_library_entry', args=[own_entry.pk])).status_code,
            405,
        )

        # Referer seguro vuelve a la ficha; referer externo cae en biblioteca.
        detail_url = reverse('game_detail', args=[own_entry.game.slug])
        resp_internal = self.client.post(
            reverse('rate_library_entry', args=[own_entry.pk]),
            {'rating': '4', 'review': 'Muy bueno'},
            HTTP_REFERER=f'http://testserver{detail_url}',
        )
        self.assertRedirects(resp_internal, f'http://testserver{detail_url}')

        resp_external = self.client.post(
            reverse('rate_library_entry', args=[own_entry.pk]),
            {'rating': '3'},
            HTTP_REFERER='https://evil.example.com/phish',
        )
        self.assertRedirects(resp_external, reverse('biblioteca'))

        # Staff redirige al panel.
        self.client.force_login(self.staff)
        self.assertRedirects(
            self.client.post(reverse('rate_library_entry', args=[own_entry.pk]), {'rating': '5'}),
            reverse('panel_dashboard'),
        )

        # Anónimo redirige a login.
        self.client.logout()
        anon_resp = self.client.post(
            reverse('rate_library_entry', args=[own_entry.pk]),
            {'rating': '5'},
        )
        self.assertEqual(anon_resp.status_code, 302)
        self.assertIn(reverse('login'), anon_resp.url)

    def test_biblioteca_displays_rating_form_only_for_done_entries_and_rating_context(self):
        pending_game = Game.objects.create(title='Juego Pendiente', studio='Estudio A')
        LibraryEntry.objects.create(
            user=self.user,
            game=pending_game,
            status=LibraryEntry.Status.WANT,
        )
        done_entry = LibraryEntry.objects.create(
            user=self.user,
            game=self.game,
            status=LibraryEntry.Status.DONE,
        )
        LibraryReview.objects.create(
            entry=done_entry,
            rating=5,
            review='Arte precioso.',
        )
        other_done = LibraryEntry.objects.create(
            user=self.other,
            game=self.game,
            status=LibraryEntry.Status.DONE,
        )
        LibraryReview.objects.create(
            entry=other_done,
            rating=4,
            review='Buen ritmo.',
        )

        response = self.client.get(reverse('biblioteca'))
        self.assertContains(response, reverse('rate_library_entry', args=[done_entry.pk]))
        self.assertContains(response, '★★★★★')
        self.assertContains(response, 'Arte precioso.')
        self.assertEqual(response.content.decode().count('class="entry-review-form"'), 1)

        ctx = get_game_rating_context(self.game, self.user)
        self.assertEqual(ctx['rating_avg'], 4.5)
        self.assertEqual(ctx['rating_count'], 2)
        self.assertEqual(len(ctx['rated_entries']), 2)
        self.assertEqual(ctx['user_library_entry'], done_entry)

        request = RequestFactory().get(reverse('game_detail', args=[self.game.slug]))
        request.user = self.user
        rendered = render_to_string(
            'partials/_game_ratings.html',
            {'game': self.game, 'in_library': done_entry, **ctx},
            request=request,
        )
        self.assertIn('2 valoraciones', rendered)
        self.assertIn('Arte precioso.', rendered)
        self.assertIn('Buen ritmo.', rendered)
        self.assertIn(reverse('rate_library_entry', args=[done_entry.pk]), rendered)

        detail_resp = self.client.get(reverse('game_detail', args=[self.game.slug]))
        self.assertEqual(detail_resp.status_code, 200)
        self.assertContains(detail_resp, 'Opiniones de quienes lo terminaron')
        self.assertContains(detail_resp, 'Arte precioso.')
        self.assertContains(detail_resp, 'Buen ritmo.')


class GlobalSearchTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.viewer = User.objects.create_user(
            username='explorador', password='ClaveSegura-2026!'
        )
        self.staff = User.objects.create_user(
            username='moderador', password='ClaveSegura-2026!', is_staff=True
        )

        self.pub_user = User.objects.create_user(
            username='nexo_publico',
            first_name='Clara',
            password='ClaveSegura-2026!',
        )
        self.pub_user.profile.visibility = Profile.Visibility.PUBLIC
        self.pub_user.profile.bio = 'Coleccionista nexo de aventuras.'
        self.pub_user.profile.save()

        self.mem_user = User.objects.create_user(
            username='nexo_miembros',
            first_name='Mateo',
            password='ClaveSegura-2026!',
        )
        self.mem_user.profile.visibility = Profile.Visibility.MEMBERS
        self.mem_user.profile.bio = 'Perfil nexo solo miembros.'
        self.mem_user.profile.save()

        self.priv_user = User.objects.create_user(
            username='nexo_privado',
            first_name='Lucía',
            password='ClaveSegura-2026!',
        )
        self.priv_user.profile.visibility = Profile.Visibility.PRIVATE
        self.priv_user.profile.bio = 'Secreto nexo totalmente privado.'
        self.priv_user.profile.save()

        self.inactive_user = User.objects.create_user(
            username='nexo_inactivo',
            password='ClaveSegura-2026!',
            is_active=False,
        )
        self.inactive_user.profile.visibility = Profile.Visibility.PUBLIC
        self.inactive_user.profile.bio = 'Cuenta nexo desactivada.'
        self.inactive_user.profile.save()

        self.game = Game.objects.create(
            title='Crónicas del Nexo',
            studio='Taller Boreal',
            genres='Metroidvania, Puzle',
        )
        self.thread = Discussion.objects.create(
            game=self.game,
            author=self.viewer,
            title='Guía secreta del Nexo',
            body='Cómo abrir la puerta norte sin perder objetos.',
        )
        self.client = Client()

    def test_empty_search_renders_clean_initial_state(self):
        response = self.client.get(reverse('search_global'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'search_results.html')
        self.assertContains(response, '¿Qué estás buscando hoy?')

    def test_grouped_search_finds_games_threads_and_respects_profile_privacy_for_anonymous(self):
        response = self.client.get(reverse('search_global'), {'q': 'Nexo'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Crónicas del Nexo')
        self.assertContains(response, 'Guía secreta del Nexo')
        self.assertContains(response, 'nexo_publico')
        self.assertNotContains(response, 'nexo_miembros')
        self.assertNotContains(response, 'nexo_privado')
        self.assertNotContains(response, 'Secreto nexo totalmente privado.')
        self.assertNotContains(response, 'nexo_inactivo')
        self.assertEqual(response.context['profiles_count'], 1)

    def test_profile_privacy_across_member_owner_and_staff(self):
        url = reverse('search_global')

        # Usuario registrado: ve public + members, pero NO private ajeno ni inactivo.
        self.client.force_login(self.viewer)
        resp_member = self.client.get(url, {'q': 'nexo', 'type': 'profiles'})
        usernames_member = [p.user.username for p in resp_member.context['profiles_results']]
        self.assertEqual(usernames_member, ['nexo_miembros', 'nexo_publico'])
        self.assertEqual(resp_member.context['profiles_count'], 2)
        self.assertNotContains(resp_member, 'nexo_privado')

        # El propio dueño sí ve su perfil privado.
        self.client.force_login(self.priv_user)
        resp_owner = self.client.get(url, {'q': 'nexo', 'type': 'profiles'})
        usernames_owner = [p.user.username for p in resp_owner.context['profiles_results']]
        self.assertEqual(
            usernames_owner,
            ['nexo_miembros', 'nexo_privado', 'nexo_publico'],
        )

        # El staff también ve perfiles privados activos, pero no cuentas inactivas.
        self.client.force_login(self.staff)
        resp_staff = self.client.get(url, {'q': 'nexo', 'type': 'profiles'})
        usernames_staff = [p.user.username for p in resp_staff.context['profiles_results']]
        self.assertEqual(
            usernames_staff,
            ['nexo_miembros', 'nexo_privado', 'nexo_publico'],
        )

    def test_search_all_caps_at_six_and_specific_types_paginate_by_twelve(self):
        for idx in range(15):
            Game.objects.create(
                title=f' serieCometa {idx:02d}',
                studio='Estudio Cometa',
                genres='Acción',
            )

        all_resp = self.client.get(reverse('search_global'), {'q': 'Cometa', 'type': 'all'})
        self.assertEqual(all_resp.context['games_count'], 15)
        self.assertEqual(len(all_resp.context['games_results']), 6)
        self.assertContains(all_resp, 'type=games')

        page1 = self.client.get(
            reverse('search_global'),
            {'q': 'Cometa', 'type': 'games', 'page': 1},
        )
        page2 = self.client.get(
            reverse('search_global'),
            {'q': 'Cometa', 'type': 'games', 'page': 2},
        )
        self.assertEqual(len(page1.context['games_results']), 12)
        self.assertEqual(len(page2.context['games_results']), 3)
        self.assertContains(page1, 'Página 1 de 2')


class NotificationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.author = User.objects.create_user(
            username='autora', password='ClaveSegura-2026!'
        )
        self.replier = User.objects.create_user(
            username='comentarista', password='ClaveSegura-2026!'
        )
        self.studio_user = User.objects.create_user(
            username='estudio_notif', password='ClaveSegura-2026!'
        )
        self.staff = User.objects.create_user(
            username='staff_notif', password='ClaveSegura-2026!', is_staff=True
        )
        self.enterprise = Enterprise.objects.create(
            user=self.studio_user,
            studio_name='Estudio Austral',
            is_verified=False,
        )
        self.discussion = Discussion.objects.create(
            author=self.author,
            title='Recomendaciones de puzles cortos',
            body='¿Qué títulos recomiendan para una tarde?',
        )
        self.client = Client()

    def test_reply_by_other_creates_notification_but_self_reply_does_not(self):
        # Auto-respuesta: no genera notificación.
        DiscussionReply.objects.create(
            discussion=self.discussion,
            author=self.author,
            body='Añado un detalle más a mi pregunta.',
        )
        self.assertEqual(Notification.objects.count(), 0)

        # Respuesta de otra persona: genera notificación para la autora.
        reply = DiscussionReply.objects.create(
            discussion=self.discussion,
            author=self.replier,
            body='Te recomiendo Cripta de vidrio.',
        )
        self.assertEqual(Notification.objects.count(), 1)
        notif = Notification.objects.get()
        self.assertEqual(notif.recipient, self.author)
        self.assertEqual(notif.actor, self.replier)
        self.assertEqual(notif.discussion, self.discussion)
        self.assertEqual(notif.reply, reply)
        self.assertIn('Recomendaciones de puzles cortos', notif.verb)
        self.assertEqual(
            notif.target_url,
            f'{self.discussion.get_absolute_url()}#reply-{reply.pk}',
        )
        self.assertFalse(notif.is_read)

    def test_enterprise_verification_signal_only_on_false_to_true_transition(self):
        # Al crearse sin verificar no había notificaciones.
        self.assertEqual(Notification.objects.filter(recipient=self.studio_user).count(), 0)

        # Al verificarse desde el panel, recibe una notificación.
        self.client.force_login(self.staff)
        self.client.post(reverse('panel_enterprise_verify', args=[self.enterprise.pk]))
        self.enterprise.refresh_from_db()
        self.assertTrue(self.enterprise.is_verified)

        notifs = Notification.objects.filter(recipient=self.studio_user)
        self.assertEqual(notifs.count(), 1)
        notif = notifs.first()
        self.assertIn('Estudio Austral', notif.verb)
        self.assertEqual(notif.target_url, reverse('enterprise_dashboard'))

        # Guardar cambios manteniéndola verificada NO duplica la notificación.
        self.enterprise.description = 'Descripción actualizada'
        self.enterprise.save()
        self.assertEqual(Notification.objects.filter(recipient=self.studio_user).count(), 1)

        # Quitar verificación tampoco crea notificación de verificación.
        self.client.post(reverse('panel_enterprise_verify', args=[self.enterprise.pk]))
        self.assertEqual(Notification.objects.filter(recipient=self.studio_user).count(), 1)

    def test_navbar_badge_and_mark_one_or_all_notifications_as_read(self):
        r1 = DiscussionReply.objects.create(
            discussion=self.discussion,
            author=self.replier,
            body='Primera respuesta.',
        )
        DiscussionReply.objects.create(
            discussion=self.discussion,
            author=self.replier,
            body='Segunda respuesta.',
        )
        n1 = Notification.objects.get(reply=r1)

        # Otra cuenta también tiene una notificación que no debe tocarse.
        other_notif = Notification.objects.create(
            recipient=self.replier,
            verb='Aviso independiente',
        )

        # Anónimo: redirige a login al abrir /notificaciones/.
        anon = self.client.get(reverse('notifications'))
        self.assertEqual(anon.status_code, 302)
        self.assertIn(reverse('login'), anon.url)

        self.client.force_login(self.author)
        inbox = self.client.get(reverse('notifications'))
        self.assertEqual(inbox.status_code, 200)
        self.assertContains(inbox, '<span class="notif-badge" aria-label="2 sin leer">2</span>', html=True)

        # No puede marcar notificación ajena.
        self.assertEqual(
            self.client.post(reverse('notification_mark_read', args=[other_notif.pk])).status_code,
            404,
        )

        # Marcar una notificación con go=1 redirige al hilo correspondiente.
        go_resp = self.client.post(
            reverse('notification_mark_read', args=[n1.pk]),
            {'go': '1'},
        )
        self.assertEqual(go_resp.status_code, 302)
        self.assertEqual(go_resp['Location'], n1.target_url)
        n1.refresh_from_db()
        self.assertTrue(n1.is_read)

        # El contador del navbar baja a 1.
        inbox_after_one = self.client.get(reverse('notifications'))
        self.assertContains(
            inbox_after_one,
            '<span class="notif-badge" aria-label="1 sin leer">1</span>',
            html=True,
        )

        # Marcar todas como leídas deja el contador en 0 y oculta el badge.
        mark_all_resp = self.client.post(reverse('notifications_mark_all_read'))
        self.assertRedirects(mark_all_resp, reverse('notifications'))
        self.assertEqual(
            Notification.objects.filter(recipient=self.author, is_read=False).count(),
            0,
        )
        inbox_clean = self.client.get(reverse('notifications'))
        self.assertNotContains(inbox_clean, 'class="notif-badge"')

        # La notificación de la otra cuenta sigue intacta.
        other_notif.refresh_from_db()
        self.assertFalse(other_notif.is_read)


class NotificationSimpleTestCaseCompatibilityTests(SimpleTestCase):
    @patch('IndieVault.views.LibraryEntry.objects.filter')
    def test_in_memory_user_without_pk_does_not_hit_database(self, filter_entries):
        user = get_user_model()(username='memoria')
        entries = filter_entries.return_value
        entries.aggregate.return_value = {
            'saved_count': 0,
            'pending_count': 0,
            'playing_count': 0,
            'finished_count': 0,
        }
        entries.filter.return_value.select_related.return_value.order_by.return_value.__getitem__.return_value = []

        with patch('django.contrib.auth.middleware.get_user', return_value=user):
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(reverse('index'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(queries), 0)
        self.assertContains(response, reverse('notifications'))
        self.assertContains(response, reverse('search_global'))
        self.assertNotContains(response, 'class="notif-badge"')
