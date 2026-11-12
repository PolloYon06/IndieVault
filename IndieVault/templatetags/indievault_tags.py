from django import template

register = template.Library()


@register.filter
def display_name(user):
    """Nombre completo si existe; si no, el usuario."""
    if not user:
        return ''
    return user.get_full_name().strip() or user.username


@register.filter
def initials(user):
    """Dos iniciales para el avatar de respaldo."""
    if not user:
        return '?'

    full_name = user.get_full_name().strip()
    if full_name:
        parts = full_name.split()
        return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else '')).upper()

    return user.username[:2].upper()


@register.filter
def avatar_url(user):
    """URL del avatar o cadena vacía si la cuenta no tiene uno."""
    profile = getattr(user, 'profile', None)
    if profile is None or not profile.avatar:
        return ''

    try:
        return profile.avatar.url
    except ValueError:
        return ''
