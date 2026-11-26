from django.conf import settings
from django.db import DatabaseError, transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.urls import reverse

from .models import DiscussionReply, Enterprise, Notification, Profile


def _safe_create_notification(**kwargs):
    """Crea la notificación ignorando el fallo si la tabla aún no fue migrada."""
    try:
        with transaction.atomic():
            Notification.objects.create(**kwargs)
    except DatabaseError:
        pass


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, **kwargs):
    """Toda cuenta nueva recibe un perfil listo para personalizar."""
    if kwargs.get('raw'):
        return
    if created:
        Profile.objects.get_or_create(user=instance)


@receiver(post_save, sender=DiscussionReply)
def notify_discussion_reply(sender, instance, created, **kwargs):
    """Notifica al autor del tema cuando otra persona responde."""
    if kwargs.get('raw') or not created:
        return
    discussion = instance.discussion
    if instance.author_id != discussion.author_id:
        _safe_create_notification(
            recipient=discussion.author,
            actor=instance.author,
            discussion=discussion,
            reply=instance,
            verb=f'respondió en tu tema «{discussion.title}»',
            target_url=f'{discussion.get_absolute_url()}#reply-{instance.pk}',
        )


@receiver(pre_save, sender=Enterprise)
def capture_enterprise_verification_state(sender, instance, **kwargs):
    """Guarda el estado previo de verificación antes de guardar la empresa."""
    if kwargs.get('raw') or instance.pk is None:
        instance._was_verified = None
    else:
        instance._was_verified = (
            Enterprise.objects.filter(pk=instance.pk)
            .values_list('is_verified', flat=True)
            .first()
        )


@receiver(post_save, sender=Enterprise)
def notify_enterprise_verified(sender, instance, created, **kwargs):
    """Notifica a la cuenta de empresa cuando el equipo verifica su estudio."""
    if kwargs.get('raw') or created:
        return
    was_verified = getattr(instance, '_was_verified', None)
    if was_verified is False and instance.is_verified:
        _safe_create_notification(
            recipient=instance.user,
            verb=f'Tu estudio «{instance.studio_name}» fue verificado por el equipo de IndieVault.',
            target_url=reverse('enterprise_dashboard'),
        )
