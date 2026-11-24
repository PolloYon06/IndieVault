from collections import Counter

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from .models import Discussion, DiscussionReply, Game, LibraryEntry

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


def _level(title, labels, values, colors='lilac', horizontal=True,
           empty_text='Sin datos para este desglose.'):
    """Sub-gráfico que se abre al pulsar un elemento del gráfico padre."""
    return {
        'title': title,
        'type': 'bar',
        'horizontal': horizontal,
        'labels': labels,
        'values': values,
        'colors': colors,
        'empty': not labels or not any(values),
        'empty_text': empty_text,
    }


def _top_genre_level(games, title, limit=6):
    """Desglose de géneros para un subconjunto de juegos."""
    genres = _genres_counter(games).most_common(limit)
    return _level(
        title,
        [genre for genre, _ in genres],
        [count for _, count in genres],
        empty_text='Sin géneros registrados en este grupo.',
    )


def user_stats(user):
    entries = list(LibraryEntry.objects.filter(user=user).select_related('game'))
    total_entries = len(entries)
    status_counts = Counter(entry.status for entry in entries)

    genre_counts = Counter()
    for entry in entries:
        for genre in entry.game.genre_list():
            genre_counts[genre] += 1
    top_genres = genre_counts.most_common(8)

    # Segundo nivel del gráfico por estado: qué géneros hay dentro de cada uno.
    status_games = {status: [] for status in STATUS_VALUES}
    for entry in entries:
        status_games.setdefault(entry.status, []).append(entry.game)
    status_levels = {}
    for status in STATUS_VALUES:
        games_in_status = status_games.get(status, [])
        if not games_in_status:
            continue
        status_levels[status] = _top_genre_level(
            games_in_status,
            f'Géneros en «{status.lower()}»',
        )

    # Cada género se abre en un desglose por estado de lectura.
    genre_entries = {}
    for entry in entries:
        for genre in entry.game.genre_list():
            genre_entries.setdefault(genre, []).append(entry)
    genre_levels = {}
    for genre, _ in top_genres:
        subset = genre_entries[genre]
        counts = Counter(entry.status for entry in subset)
        genre_levels[genre] = _level(
            f'Estados en {genre}',
            STATUS_VALUES,
            [counts.get(status, 0) for status in STATUS_VALUES],
            colors=['muted', 'lime', 'lilac'],
            horizontal=False,
            empty_text='Sin juegos en este género.',
        )

    # El progreso separa lo terminado de lo que sigue pendiente.
    done_games = [
        entry.game for entry in entries
        if entry.status == LibraryEntry.Status.DONE.value
    ]
    pending_games = [
        entry.game for entry in entries
        if entry.status != LibraryEntry.Status.DONE.value
    ]
    progress_levels = {
        'Terminados': _top_genre_level(
            done_games, 'Géneros que ya terminaste'
        ),
        'Pendientes': _top_genre_level(
            pending_games, 'Géneros que te quedan por terminar'
        ),
    }

    done = status_counts.get(LibraryEntry.Status.DONE.value, 0)
    playing_count = status_counts.get(LibraryEntry.Status.PLAYING.value, 0)
    want_count = status_counts.get(LibraryEntry.Status.WANT.value, 0)
    progress = round(done * 100 / total_entries) if total_entries else 0

    saved_ids = {entry.game_id for entry in entries}
    total_games = Game.objects.count()
    saved = len(saved_ids)
    coverage = round(saved * 100 / total_games) if total_games else 0

    discussions_count = Discussion.objects.filter(author=user).count()
    replies_count = DiscussionReply.objects.filter(author=user).count()
    community_total = discussions_count + replies_count

    kpis = [
        {
            'label': 'En mi biblioteca',
            'value': total_entries,
            'note': f'{coverage}% del catálogo',
            'href': reverse('biblioteca'),
        },
        {
            'label': 'En curso',
            'value': playing_count,
            'note': f'{want_count} pendiente{"" if want_count == 1 else "s"} por empezar',
            'href': reverse('biblioteca'),
        },
        {
            'label': 'Terminados',
            'value': done,
            'note': f'{progress}% de finalización',
            'href': reverse('biblioteca'),
        },
        {
            'label': 'Comunidad',
            'value': community_total,
            'note': f'{discussions_count} tema{"" if discussions_count == 1 else "s"} · {replies_count} comentario{"" if replies_count == 1 else "s"}',
            'href': reverse('community'),
        },
    ]

    playing_entries = [
        entry for entry in entries
        if entry.status == LibraryEntry.Status.PLAYING.value
    ][:6]

    recent_threads = list(
        Discussion.objects.filter(Q(author=user) | Q(replies__author=user))
        .select_related('game', 'author')
        .annotate(reply_count=Count('replies', distinct=True))
        .distinct()
        .order_by('-last_activity_at')[:5]
    )

    charts = [
        {
            'id': 'user-status',
            'title': 'Mi biblioteca por estado',
            'note': _plural(total_entries, 'juego guardado', 'juegos guardados'),
            'type': 'doughnut',
            'labels': STATUS_VALUES,
            'values': [status_counts.get(status, 0) for status in STATUS_VALUES],
            'colors': ['muted', 'lime', 'lilac'],
            'levels': status_levels,
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
            'levels': genre_levels,
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
            'levels': progress_levels,
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
        'kicker_class': '',
        'page_kicker': 'Tu actividad',
        'page_title': 'Tus estadísticas',
        'page_note': 'Un resumen de lo que has guardado y avanzado en IndieVault.',
        'kpis': kpis,
        'playing_entries': playing_entries,
        'recent_threads': recent_threads,
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
    by_weekday = {key: Counter() for key in keys}
    for joined in User.objects.values_list('date_joined', flat=True):
        joined = timezone.localtime(joined)
        key = (joined.year, joined.month)
        counts[key] += 1
        if key in by_weekday:
            by_weekday[key][joined.weekday()] += 1

    labels = [f'{MONTH_ABBR[m - 1]} {y}' for y, m in keys]
    values = [counts.get((y, m), 0) for y, m in keys]

    # Cada mes se abre en un sub-gráfico con las altas por día de la semana.
    weekday_labels = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
    levels = {}
    for key, label in zip(keys, labels):
        weekday_counts = by_weekday[key]
        levels[label] = _level(
            f'Altas por día · {label}',
            weekday_labels,
            [weekday_counts.get(index, 0) for index in range(7)],
            horizontal=False,
            empty_text='Sin registros ese mes.',
        )

    return labels, values, levels


def admin_stats():
    games = list(Game.objects.all())

    genre_games = {}
    for game in games:
        for genre in game.genre_list():
            genre_games.setdefault(genre, []).append(game)
    top_genres = Counter(
        {genre: len(items) for genre, items in genre_games.items()}
    ).most_common(10)

    free = sum(1 for game in games if game.is_free())
    paid = len(games) - free
    free_games = [game for game in games if game.is_free()]
    paid_games = [game for game in games if not game.is_free()]

    # Desglose por estudio dentro de cada género.
    genre_levels = {}
    for genre, _ in top_genres:
        studios = Counter(
            game.studio for game in genre_games[genre] if game.studio
        ).most_common(6)
        genre_levels[genre] = _level(
            f'Estudios en {genre}',
            [studio for studio, _ in studios],
            [count for _, count in studios],
            empty_text='Sin estudios registrados en este género.',
        )

    price_levels = {
        'Gratis': _top_genre_level(
            free_games, 'Géneros entre los juegos gratis'
        ),
        'Pagos': _top_genre_level(
            paid_games, 'Géneros entre los juegos pagos'
        ),
    }

    status_counts = Counter(
        LibraryEntry.objects.values_list('status', flat=True)
    )
    total_entries = sum(status_counts.values())

    user_labels, user_values, user_levels = _users_last_months(6)

    # --- Datos para los gráficos atípicos del panel -------------------------

    year_buckets = {}
    for game in games:
        if not game.year:
            continue
        bucket = year_buckets.setdefault(game.year, {'count': 0, 'total': 0.0})
        bucket['count'] += 1
        bucket['total'] += float(game.price)

    bubble_points = []
    for year in sorted(year_buckets):
        bucket = year_buckets[year]
        average = bucket['total'] / bucket['count']
        bubble_points.append({
            'x': year,
            'y': round(average, 2),
            'r': round(min(6 + bucket['count'] ** 0.5, 22), 1),
            'label': (
                f'{year}: {_plural(bucket["count"], "juego", "juegos")} '
                f'· ${average:.2f} de precio medio'
            ),
        })

    year_counts = Counter(game.year for game in games if game.year)
    decade_counts = Counter()
    for year, count in year_counts.items():
        decade_counts[f'{year // 10 * 10}s'] += count
    decade_labels = sorted(decade_counts)
    decade_values = [decade_counts[label] for label in decade_labels]

    # Cada década se abre en un sub-gráfico con sus años.
    decade_levels = {}
    for label in decade_labels:
        start = int(label[:-1])
        years = sorted(year for year in year_counts if start <= year < start + 10)
        decade_levels[label] = _level(
            f'Juegos por año en los {label}',
            [str(year) for year in years],
            [year_counts[year] for year in years],
            colors='lime',
            horizontal=False,
            empty_text='Sin años registrados en esta década.',
        )

    studio_counts = Counter(game.studio for game in games if game.studio)
    top_studios = studio_counts.most_common(6)
    studio_total = sum(count for _, count in top_studios) or 1
    tones = ['lime', 'lilac']
    mosaic_blocks = [
        {
            'label': studio,
            'value': count,
            'percent': round(count * 100 / studio_total, 1),
            'tone': tones[index % len(tones)],
        }
        for index, (studio, count) in enumerate(top_studios)
    ]

    registration_heatmap = _registration_heatmap()

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
            'levels': genre_levels,
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
            'levels': price_levels,
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
            'levels': user_levels,
            'empty': sum(user_values) == 0,
            'empty_text': 'Sin registros en los últimos 6 meses.',
        },
        {
            'id': 'admin-radar',
            'title': 'ADN del catálogo',
            'note': 'Los 8 géneros con más títulos',
            'type': 'radar',
            'labels': [genre for genre, _ in top_genres[:8]],
            'values': [count for _, count in top_genres[:8]],
            'colors': 'lime',
            'empty': not top_genres,
            'empty_text': 'No hay géneros que dibujar.',
        },
        {
            'id': 'admin-decades',
            'title': 'Juegos por década',
            'note': 'La línea temporal del catálogo',
            'type': 'polarArea',
            'labels': decade_labels,
            'values': decade_values,
            'colors': ['lime', 'lilac', 'muted', 'lime', 'lilac', 'muted'],
            'levels': decade_levels,
            'empty': not decade_labels,
            'empty_text': 'No hay años registrados.',
        },
        {
            'id': 'admin-bubble',
            'title': 'Precio medio por año',
            'note': 'Cada burbuja es un año; su tamaño, el volumen de juegos',
            'type': 'bubble',
            'points': bubble_points,
            'colors': 'lilac',
            'empty': not bubble_points,
            'empty_text': 'No hay precios y años suficientes.',
        },
        {
            'id': 'admin-heatmap',
            'title': 'Altas por día y mes',
            'note': f'{_plural(registration_heatmap["total"], "registro", "registros")} en los últimos 12 meses',
            'type': 'heatmap',
            'x_labels': registration_heatmap['x_labels'],
            'rows': registration_heatmap['rows'],
            'wide': True,
            'empty': registration_heatmap['total'] == 0,
            'empty_text': 'Sin registros en el último año.',
        },
        {
            'id': 'admin-mosaic',
            'title': 'Estudios líderes',
            'note': 'Cuota de títulos entre los 6 estudios con más presencia',
            'type': 'mosaic',
            'blocks': mosaic_blocks,
            'wide': True,
            'empty': not mosaic_blocks,
            'empty_text': 'No hay estudios registrados.',
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


DASHBOARD_CHART_IDS = (
    'admin-radar',
    'admin-bubble',
    'admin-heatmap',
    'admin-mosaic',
)


def dashboard_charts():
    """Selección de gráficos atípicos para el resumen del panel."""
    charts = {chart['id']: chart for chart in admin_stats()['charts']}
    return [
        charts[chart_id]
        for chart_id in DASHBOARD_CHART_IDS
        if chart_id in charts
    ]


def _month_keys(months=12):
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
    return keys


def _registration_heatmap(months=12):
    """Registros agrupados por mes y día de la semana."""
    User = get_user_model()
    keys = _month_keys(months)
    month_index = {key: index for index, key in enumerate(keys)}
    counts = Counter()

    for joined in User.objects.values_list('date_joined', flat=True):
        local = timezone.localtime(joined)
        index = month_index.get((local.year, local.month))
        if index is not None:
            counts[(index, local.weekday())] += 1

    weekday_labels = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
    max_value = max(counts.values(), default=0)
    rows = []

    for weekday, label in enumerate(weekday_labels):
        cells = []
        for index, (year, month) in enumerate(keys):
            value = counts.get((index, weekday), 0)
            if value == 0 or max_value == 0:
                level = 0
            else:
                level = max(1, round(value * 4 / max_value))
            cells.append({
                'value': value,
                'level': level,
                'label': (
                    f'{label} {MONTH_ABBR[month - 1]} {year}: '
                    f'{_plural(value, "registro", "registros")}'
                ),
            })
        rows.append({'label': label, 'cells': cells})

    return {
        'x_labels': [
            f'{MONTH_ABBR[month - 1]} {str(year)[2:]}' for year, month in keys
        ],
        'rows': rows,
        'total': sum(counts.values()),
    }
