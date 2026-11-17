"""Copia a la base las fotos de perfil antiguas que aún viven en media/."""

import mimetypes

from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

from IndieVault.appearance import normalize_avatar_bytes
from IndieVault.models import Profile


class Command(BaseCommand):
    help = 'Guarda en la base las fotos de perfil que todavía están en media/.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Cuenta las fotos pendientes sin guardar nada.',
        )

    def handle(self, *args, **options):
        pending = (
            Profile.objects.exclude(avatar='')
            .filter(avatar_data__isnull=True)
            .select_related('user')
        )
        imported = 0
        missing = 0

        for profile in pending:
            name = profile.avatar.name
            try:
                with default_storage.open(name, 'rb') as handle:
                    data = handle.read()
            except Exception:
                missing += 1
                self.stdout.write(
                    f'  Sin archivo local: {profile.user.username} ({name})'
                )
                continue

            if not data:
                missing += 1
                continue

            if options['dry_run']:
                imported += 1
                continue

            try:
                profile.avatar_data, profile.avatar_mime = normalize_avatar_bytes(data)
            except Exception:
                profile.avatar_data, profile.avatar_mime = data, (
                    mimetypes.guess_type(name)[0] or 'image/jpeg'
                )
            profile.avatar_version = (profile.avatar_version or 0) + 1
            profile.save(update_fields=['avatar_data', 'avatar_mime', 'avatar_version'])
            imported += 1

        if options['dry_run']:
            self.stdout.write(f'Fotos pendientes: {imported}; sin archivo local: {missing}')
        else:
            self.stdout.write(
                f'Fotos importadas: {imported}; sin archivo local: {missing}'
            )
