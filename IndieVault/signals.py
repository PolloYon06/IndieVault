from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, **kwargs):
    """Toda cuenta nueva recibe un perfil listo para personalizar."""
    if created:
        Profile.objects.get_or_create(user=instance)
