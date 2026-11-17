"""Foto de perfil y color de acento derivado de ella."""

import colorsys
import io
import re

from PIL import Image, ImageOps

DEFAULT_ACCENT = '#d6f36a'
HEX_RE = re.compile(r'^#[0-9a-fA-F]{6}$')

# Las fotos se guardan en la base para que se vean igual en todos los equipos,
# así que se normalizan antes de guardarlas y ocupan poco.
AVATAR_MAX_BYTES = 4 * 1024 * 1024
AVATAR_MAX_SIDE = 512
AVATAR_QUALITY = 85
AVATAR_MIME = 'image/jpeg'


def _to_hex(red, green, blue):
    components = (max(0, min(255, round(value * 255))) for value in (red, green, blue))
    return '#{:02x}{:02x}{:02x}'.format(*components)


def _open_image(source):
    """Abre una imagen desde bytes o desde un archivo de Django."""
    if isinstance(source, (bytes, bytearray, memoryview)):
        return Image.open(io.BytesIO(bytes(source)))
    return Image.open(source.open('rb'))


def prepare_avatar(uploaded_file):
    """Valida la foto y la devuelve como JPEG pequeño, listo para la base."""
    if getattr(uploaded_file, 'size', 0) > AVATAR_MAX_BYTES:
        raise ValueError('La foto supera los 4 MB.')

    uploaded_file.seek(0)
    image = Image.open(uploaded_file)
    image.load()
    image = ImageOps.exif_transpose(image).convert('RGB')
    image.thumbnail((AVATAR_MAX_SIDE, AVATAR_MAX_SIDE))

    buffer = io.BytesIO()
    image.save(
        buffer,
        format='JPEG',
        quality=AVATAR_QUALITY,
        optimize=True,
        progressive=True,
    )
    uploaded_file.seek(0)
    return buffer.getvalue(), AVATAR_MIME


def normalize_avatar_bytes(data):
    """Misma normalización, para fotos antiguas que viven en disco."""
    return prepare_avatar(io.BytesIO(data))


def dominant_accent(source, default=DEFAULT_ACCENT):
    """Color más representativo de una imagen, evitando grises y extremos."""
    if not source:
        return default

    try:
        with _open_image(source) as image:
            image = image.convert('RGB')
            image.thumbnail((80, 80))
            quantized = image.quantize(colors=8)
            palette = quantized.getpalette() or []
            colors = quantized.getcolors() or []
    except Exception:
        return default

    best = None
    best_score = 0.0
    for count, index in colors:
        offset = index * 3
        if offset + 2 >= len(palette):
            continue
        red, green, blue = palette[offset:offset + 3]
        hue, lightness, saturation = colorsys.rgb_to_hls(
            red / 255, green / 255, blue / 255
        )
        if lightness < 0.12 or lightness > 0.9:
            continue
        if saturation < 0.12:
            continue
        score = count * (0.35 + saturation)
        if score > best_score:
            best_score = score
            best = (hue, lightness, saturation)

    if best is None:
        return default

    hue, _, saturation = best
    saturation = max(saturation, 0.5)
    red, green, blue = colorsys.hls_to_rgb(hue, 0.62, saturation)
    return _to_hex(red, green, blue)


def accent_vars(color):
    """Variables CSS con la variante clara y oscura de un mismo tono."""
    if not color or not HEX_RE.match(color):
        color = DEFAULT_ACCENT

    red, green, blue = (int(color[index:index + 2], 16) / 255 for index in (1, 3, 5))
    hue, _, saturation = colorsys.rgb_to_hls(red, green, blue)
    saturation = max(saturation, 0.5)

    dark = _to_hex(*colorsys.hls_to_rgb(hue, 0.68, saturation))
    light = _to_hex(*colorsys.hls_to_rgb(hue, 0.32, saturation))
    channels = ', '.join(str(int(dark[index:index + 2], 16)) for index in (1, 3, 5))
    return {
        '--accent-dark': dark,
        '--accent-light': light,
        '--accent-rgb': channels,
    }


def accent_style(color):
    """Cadena lista para el atributo style del elemento html."""
    return ';'.join(f'{name}:{value}' for name, value in accent_vars(color).items())
