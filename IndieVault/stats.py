from collections import Counter

from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import Game, LibraryEntry

MONTH_ABBR = ['ene', 'feb', 'mar', 'abr', 'may', 'jun',
              'jul', 'ago', 'sep', 'oct', 'nov', 'dic']

STATUS_VALUES = [
    LibraryEntry.Status.WANT.value,
    LibraryEntry.Status.PLAYING.value,
    LibraryEntry.Status.DONE.value,
]


def _plural(count, singular, plural):
    return f'{count} {singular if count == 1 else plural}'


def _genres_counter(games):
    counter = Counter()
    for game in games:
        for genre in game.genre_list():
            counter[genre] += 1
    return counter


def user_stats(user):
    entries = list(LibraryEntry.objects.filter(user=user).select_related('game'))
    total_entries = len(entries)
    status_counts = Counter(entry.status for entry in entries)

    genre_counts = Counter()
    for entry in entries:
        for genre in entry.game.genre_list():
            genre_counts[genre] += 1
    top_genres = genre_counts.most_common(8)

    done = status_counts.get(LibraryEntry.Status.DONE.value, 0)
    progress = round(done * 100 / total_entries) if total_entries else 0

    saved_ids = {entry.game_id for entry in entries}
    total_games = Game.objects.count()
    saved = len(saved_ids)
    coverage = round(saved * 100 / total_games) if total_games else 0

    charts = [
        {
            'id': 'user-status',
            'title': 'Mi biblioteca por estado',
            'note': _plural(total_entries, 'juego guardado', 'juegos guardados'),
            'type': 'doughnut',
            'labels': STATUS_VALUES,
            'values': [status_counts.get(status, 0) for status in STATUS_VALUES],
            'colors': ['muted', 'lime', 'lilac'],
            'empty': total_entries == 0,
            'empty_text': 'Aún no has guardado ningún juego.',
        },
        {
            'id': 'user-genres',
            'title': 'Mis géneros más guardados',
            'note': 'Según los juegos de tu biblioteca',
            'type': 'bar',
            'horizontal': True,
            'labels': [genre for genre, _ in top_genres],
            'values': [count for _, count in top_genres],
            'colors': 'lime',
            'empty': not top_genres,
            'empty_text': 'Guarda juegos para ver tus géneros favoritos.',
        },
        {
            'id': 'user-progress',
            'title': 'Mi progreso',
            'note': f'{done} de {total_entries} terminados',
            'type': 'doughnut',
            'labels': ['Terminados', 'Pendientes'],
            'values': [done, total_entries - done],
            'colors': ['lime', 'line'],
            'gauge': True,
            'percentage': progress,
            'empty': total_entries == 0,
            'empty_text': 'Todavía no hay progreso que mostrar.',
        },
        {
            'id': 'user-coverage',
            'title': 'Mi cobertura del catálogo',
            'note': f'{saved} de {total_games} juegos',
            'type': 'doughnut',
            'labels': ['En mi biblioteca', 'Fuera'],
            'values': [saved, max(total_games - saved, 0)],
            'colors': ['lilac', 'line'],
            'empty': total_games == 0,
            'empty_text': 'El catálogo está vacío.',
        },
    ]

    return {
        'admin': False,
        'kicker_class': 'library',
        'page_kicker': 'Tu actividad',
        'page_title': 'Tus estadísticas',
        'page_note': 'Un resumen de lo que has guardado y avanzado en IndieVault.',
        'charts': charts,
        'coverage': coverage,
    }


def _users_last_months(months=6):
    User = get_user_model()
    today = timezone.localdate()
    year, month = today.year, today.month

    keys = []
    for _ in range(months):
        keys.append((year, month))
        if month == 1:
            year, month = year - 1, 12
        else:
            month -= 1
    keys.reverse()

    counts = Counter()
    for joined in User.objects.values_list('date_joined', flat=True):
        joined = timezone.localtime(joined)
        counts[(joined.year, joined.month)] += 1

    labels = [f'{MONTH_ABBR[m - 1]} {y}' for y, m in keys]
    values = [counts.get((y, m), 0) for y, m in keys]
    return labels, values


def admin_stats():
    games = list(Game.objects.all())
    top_genres = _genres_counter(games).most_common(10)

    free = sum(1 for game in games if game.is_free())
    paid = len(games) - free

    status_counts = Counter(
        LibraryEntry.objects.values_list('status', flat=True)
    )
    total_entries = sum(status_counts.values())

    user_labels, user_values = _users_last_months(6)

    charts = [
        {
            'id': 'admin-genres',
            'title': 'Juegos por género',
            'note': f'{_plural(len(games), "juego", "juegos")} en el catálogo',
            'type': 'bar',
            'horizontal': True,
            'labels': [genre for genre, _ in top_genres],
            'values': [count for _, count in top_genres],
            'colors': 'lime',
            'empty': not top_genres,
            'empty_text': 'No hay juegos en el catálogo.',
        },
        {
            'id': 'admin-price',
            'title': 'Gratis vs pagos',
            'note': f'{free} gratis · {paid} pagos',
            'type': 'doughnut',
            'labels': ['Gratis', 'Pagos'],
            'values': [free, paid],
            'colors': ['lime', 'lilac'],
            'empty': not games,
            'empty_text': 'No hay juegos en el catálogo.',
        },
        {
            'id': 'admin-library',
            'title': 'Biblioteca global por estado',
            'note': f'{total_entries} entradas en total',
            'type': 'doughnut',
            'labels': STATUS_VALUES,
            'values': [status_counts.get(status, 0) for status in STATUS_VALUES],
            'colors': ['muted', 'lime', 'lilac'],
            'empty': total_entries == 0,
            'empty_text': 'Todavía no hay juegos guardados.',
        },
        {
            'id': 'admin-users',
            'title': 'Nuevos usuarios por mes',
            'note': 'Últimos 6 meses',
            'type': 'line',
            'labels': user_labels,
            'values': user_values,
            'colors': 'lime',
            'empty': sum(user_values) == 0,
            'empty_text': 'Sin registros en los últimos 6 meses.',
        },
    ]

    return {
        'admin': True,
        'kicker_class': '',
        'page_kicker': 'Administración',
        'page_title': 'Métricas de IndieVault',
        'page_note': 'Una vista rápida del catálogo, la biblioteca y el crecimiento.',
        'charts': charts,
    }
