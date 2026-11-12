from django.apps import AppConfig


class IndievaultConfig(AppConfig):
    name = 'IndieVault'

    def ready(self):
        from . import signals  # noqa: F401
