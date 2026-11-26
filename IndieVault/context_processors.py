from django.db import DatabaseError, transaction
from django.db.models import ObjectDoesNotExist

from .appearance import accent_style
from .models import Notification


def appearance(request):
    """Inyecta el color de acento del usuario en todas las plantillas."""
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {}

    try:
        profile = user.profile
    except ObjectDoesNotExist:
        return {}

    if not profile.accent:
        return {}

    return {'accent_style': accent_style(profile.accent)}


def notifications(request):
    """Inyecta el contador de notificaciones sin leer cuando hay sesión."""
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {}

    # Compatibilidad con SimpleTestCase y usuarios en memoria sin persistir.
    if user.pk is None:
        return {'unread_notifications_count': 0}

    try:
        with transaction.atomic():
            unread_count = Notification.objects.filter(
                recipient=user,
                is_read=False,
            ).count()
    except DatabaseError:
        # Si la tabla de notificaciones aún no se ha migrado en algún entorno,
        # evitamos romper cualquier página del sitio con error 500.
        unread_count = 0

    return {
        'unread_notifications_count': unread_count,
    }
