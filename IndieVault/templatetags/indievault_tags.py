import hashlib
import re

from django import template
from django.urls import reverse

register = template.Library()

# Steam publica las mismas imágenes que usa su tienda en un CDN abierto. No
# descargamos nada: el navegador las pide directamente y, si un juego no tiene
# arte, la plantilla cae a una portada generada.
STEAM_CDN = 'https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/{asset}.jpg'

# Alias legibles para las plantillas: el tamaño vertical es el que mejor encaja
# en las tarjetas del catálogo y el horizontal en la cabecera de la ficha.
STEAM_ASSETS = {
    'portrait': 'library_600x900',
    'header': 'header',
    'capsule': 'capsule_616x353',
}


@register.filter
def steam_cover(game, asset='portrait'):
    """URL de la portada en el CDN de Steam, o cadena vacía si no hay app id."""
    app_id = getattr(game, 'steam_app_id', None)
    if not app_id:
        return ''
    return STEAM_CDN.format(app_id=app_id, asset=STEAM_ASSETS.get(asset, asset))


@register.filter
def cover_tint(game):
    """Degradado estable para la portada de respaldo.

    Respeta el color que haya elegido el equipo en el panel y, si no hay,
    deriva un tono del título para que cada juego tenga una portada distinta
    sin guardar nada en la base de datos.
    """
    tint = (getattr(game, 'tint', '') or '').strip()
    if tint:
        return tint

    title = (getattr(game, 'title', '') or '').strip() or 'IndieVault'
    digest = hashlib.sha1(title.encode('utf-8')).hexdigest()
    hue = int(digest[:4], 16) % 360
    return (
        f'linear-gradient(150deg, hsl({hue} 42% 26%) 0%, '
        f'hsl({(hue + 42) % 360} 48% 15%) 58%, #0b0b13 100%)'
    )


@register.filter
def cover_initials(game):
    """Dos iniciales para la portada de respaldo."""
    title = (getattr(game, 'title', '') or '').strip()
    if not title:
        return 'IV'

    words = [word for word in re.split(r'[\s:·–—-]+', title) if word]
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


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
    """URL del avatar o cadena vacía si la cuenta no tiene uno.

    Prioriza la foto guardada en la base; si es una cuenta antigua, cae al
    archivo que todavía esté en media/.
    """
    profile = getattr(user, 'profile', None)
    if profile is None:
        return ''

    if profile.avatar_data:
        url = reverse('profile_avatar', args=[profile.user_id])
        version = profile.avatar_version
        return f'{url}?v={version}' if version else url

    if not profile.avatar:
        return ''

    try:
        return profile.avatar.url
    except ValueError:
        return ''
