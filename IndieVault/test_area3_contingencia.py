"""Pruebas automatizadas de preparación técnica y contingencia Día D (Área 4)."""

from io import StringIO
import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from IndieVault.models import (
    Discussion,
    DiscussionReply,
    Enterprise,
    LibraryEntry,
)


@override_settings(ALLOWED_HOSTS=['127.0.0.1', 'localhost', 'testserver'])
class ContingencyReadinessTests(TestCase):
    """Valida el comando verify_demo_readiness y sus modos de reparación."""

    def test_strict_fails_when_demo_and_staff_accounts_are_missing(self):
        User = get_user_model()
        User.objects.filter(username__startswith='demo_').delete()
        User.objects.filter(is_staff=True).delete()

        out = StringIO()
        with self.assertRaises(CommandError) as ctx:
            call_command('verify_demo_readiness', '--strict', stdout=out)

        error_text = str(ctx.exception)
        self.assertIn('demo_presentacion', error_text)
        self.assertIn('demo_estudio', error_text)
        self.assertIn('is_staff=True', error_text)

    def test_seed_if_missing_creates_demo_verifies_passwords_and_runs_smoke_test(self):
        User = get_user_model()
        out = StringIO()

        call_command(
            'verify_demo_readiness',
            '--seed-if-missing',
            '--users',
            '12',
            '--threads',
            '4',
            '--password',
            'ClaveDemo-2026!',
            stdout=out,
        )

        presenter = User.objects.get(username='demo_presentacion')
        studio_user = User.objects.get(username='demo_estudio')
        enterprise = Enterprise.objects.get(user=studio_user)

        self.assertTrue(presenter.has_usable_password())
        self.assertTrue(presenter.check_password('ClaveDemo-2026!'))
        self.assertTrue(studio_user.has_usable_password())
        self.assertTrue(studio_user.check_password('ClaveDemo-2026!'))
        self.assertTrue(enterprise.is_verified)
        self.assertGreaterEqual(enterprise.games.count(), 1)
        self.assertGreaterEqual(
            LibraryEntry.objects.filter(user=presenter).count(), 1
        )
        self.assertGreaterEqual(Discussion.objects.count(), 1)
        self.assertGreaterEqual(DiscussionReply.objects.count(), 1)

        report = out.getvalue()
        for route in (
            '/',
            '/explorar/',
            '/explorar/catalogo/',
            '/comunidad/',
            '/login/',
            '/registro/',
            '/estadisticas/',
            '/biblioteca/',
            '/empresa/',
        ):
            self.assertIn(route, report)
        self.assertIn('200', report)
        self.assertIn('ms', report)

    def test_strict_passes_with_staff_user_and_reports_all_routes_200(self):
        User = get_user_model()
        User.objects.create_user(
            username='admin_dia_d',
            password='AdminClave-2026!',
            is_staff=True,
        )
        call_command(
            'seed_demo',
            users=10,
            threads=4,
            password='ClaveDemo-2026!',
            stdout=StringIO(),
        )

        out = StringIO()
        call_command(
            'verify_demo_readiness',
            '--password',
            'ClaveDemo-2026!',
            '--strict',
            stdout=out,
        )

        report = out.getvalue()
        self.assertIn('ENTORNO 100% LISTO PARA PRESENTACIÓN', report)
        expected_routes = (
            '/',
            '/explorar/',
            '/explorar/catalogo/',
            '/buscar/?q=DEMO',
            '/comunidad/',
            '/login/',
            '/registro/',
            '/estadisticas/',
            '/biblioteca/',
            '/notificaciones/',
            '/empresa/',
            '/panel/',
        )
        smoke_lines = [
            line
            for line in report.splitlines()
            if '|' in line and any(f' {r} ' in line for r in expected_routes)
        ]
        self.assertEqual(len(smoke_lines), len(expected_routes))
        for route in expected_routes:
            matching = [line for line in smoke_lines if f' {route} ' in line]
            self.assertEqual(len(matching), 1, f'No se reportó la ruta {route}')
            self.assertIn('200', matching[0])
            self.assertIn('OK', matching[0])

    def test_fix_passwords_repairs_unusable_passwords_for_demo_accounts(self):
        User = get_user_model()
        User.objects.create_user(
            username='admin_reparacion',
            password='AdminClave-2026!',
            is_staff=True,
        )
        with patch.dict(os.environ, {'DEMO_PASSWORD': ''}, clear=False):
            call_command(
                'seed_demo',
                users=6,
                threads=3,
                password='',
                stdout=StringIO(),
            )

        presenter = User.objects.get(username='demo_presentacion')
        studio_user = User.objects.get(username='demo_estudio')
        self.assertFalse(presenter.has_usable_password())
        self.assertFalse(studio_user.has_usable_password())

        with self.assertRaises(CommandError):
            call_command(
                'verify_demo_readiness',
                '--strict',
                stdout=StringIO(),
            )

        out = StringIO()
        call_command(
            'verify_demo_readiness',
            '--fix-passwords',
            '--password',
            'NuevaClave-2026!',
            '--strict',
            stdout=out,
        )

        presenter.refresh_from_db()
        studio_user.refresh_from_db()
        self.assertTrue(presenter.has_usable_password())
        self.assertTrue(studio_user.has_usable_password())
        self.assertTrue(presenter.check_password('NuevaClave-2026!'))
        self.assertTrue(studio_user.check_password('NuevaClave-2026!'))
        self.assertIn('ENTORNO 100% LISTO PARA PRESENTACIÓN', out.getvalue())
