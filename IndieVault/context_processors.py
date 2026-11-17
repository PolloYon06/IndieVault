from django.db.models import ObjectDoesNotExist

from .appearance import accent_style


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
