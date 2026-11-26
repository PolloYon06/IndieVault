import json
import re
from collections import Counter
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from hashlib import sha256
from time import time
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib.auth.views import redirect_to_login
from django.contrib.sessions.models import Session
from django.core import signing
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Exists, OuterRef, Q
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import (
    AccountCreateForm,
    AppearanceForm,
    DiscussionForm,
    DiscussionReplyForm,
    EnterpriseSignupForm,
    GameForm,
    PrivacyForm,
    ProfileForm,
)
from .models import Discussion, DiscussionReply, Game, LibraryEntry, Profile
from .platform_views import get_game_rating_context
from .stats import user_stats


def index(request):
    context = {}
    if request.user.is_authenticated and not request.user.is_staff:
        entries = LibraryEntry.objects.filter(user=request.user)
        statuses = LibraryEntry.Status
        context.update(
            entries.aggregate(
                saved_count=Count('pk'),
                pending_count=Count('pk', filter=Q(status=statuses.WANT)),
                playing_count=Count('pk', filter=Q(status=statuses.PLAYING)),
                finished_count=Count('pk', filter=Q(status=statuses.DONE)),
            )
        )
        context['playing_entries'] = entries.filter(status=statuses.PLAYING).select_related(
            'game'
        ).order_by('game__title', 'pk')[:3]

    return render(request, 'index.html', context)


EXPLORE_PRICE_CHOICES = (
    ('free', 'Gratis'),
    ('5', 'Menos de $5'),
    ('5-15', 'Entre $5 y $15'),
    ('over-15', 'Más de $15'),
    ('10', 'Menos de $10'),
)
EXPLORE_PRICE_LABELS = dict(EXPLORE_PRICE_CHOICES)
RECOMMENDATION_LIMIT = 200
RECOMMENDATION_PAGE_SIZE = 16
RECOMMENDATION_CACHE_TIMEOUT = 120
RECOMMENDATION_VERSION_PARAM = 'version_recomendaciones'
RECOMMENDATION_LIBRARY_REVISION = 'explore_library_revision'


def _library_recommendations(user, library_revision):
    entries = LibraryEntry.objects.filter(user=user)
    saved_games = (
        Game.objects.filter(library_entries__user=user).only('genres').order_by('pk')
    )
    genre_counts = Counter()
    genre_labels = {}
    library_digest = sha256()
    for game in saved_games.iterator():
        library_digest.update(f'{game.pk},'.encode('ascii'))
        game_genres = set()
        for label in game.genre_list():
            genre = label.casefold()
            genre_labels.setdefault(genre, label)
            game_genres.add(genre)
        genre_counts.update(game_genres)

    top_genres = sorted(genre_counts, key=lambda genre: (-genre_counts[genre], genre))[:3]
    labels = [genre_labels[genre] for genre in top_genres]
    if not labels:
        return [], '', '', 0

    alternatives = '|'.join(re.escape(label) for label in labels)
    # Treat commas as label boundaries and allow whitespace around each label.
    pattern = rf'(?:^|,)\s*(?:{alternatives})\s*(?:,|$)'
    # Bind the cache to this account, its saved games, and its inferred preferences.
    library_digest.update(pattern.encode('utf-8'))
    library_digest.update(library_revision.encode('ascii'))
    cache_key = f'explore:recommendations:v2:{user.pk}:{library_digest.hexdigest()}'
    selection = cache.get(cache_key)
    if selection is None or selection[1] <= time():
        recommendations = list(
            Game.objects.filter(genres__iregex=pattern)
            .filter(~Exists(entries.filter(game_id=OuterRef('pk'))))
            .order_by('-pk')
            .values_list('pk', 'genres')[:RECOMMENDATION_LIMIT]
        )
        selection = recommendations, time() + RECOMMENDATION_CACHE_TIMEOUT
        cache.set(cache_key, selection, RECOMMENDATION_CACHE_TIMEOUT)
    recommendations, expires_at = selection
    # A different worker can accept the version only if it obtains the same ordered selection.
    fingerprint = sha256(json.dumps((cache_key, recommendations)).encode()).hexdigest()
    genre_summary = f"{', '.join(labels[:-1])} y {labels[-1]}" if len(labels) > 1 else labels[0]
    return recommendations, genre_summary, fingerprint, expires_at


def _restart_recommendations(params):
    params.pop('page', None)
    params.pop(RECOMMENDATION_VERSION_PARAM, None)
    return redirect(f"{reverse('explorar_catalogo')}?{params.urlencode()}")


def explorar(request):
    if request.GET:
        return redirect(f"{reverse('explorar_catalogo')}?{request.GET.urlencode()}")

    catalog_url = reverse('explorar_catalogo')
    recommendations_url = f'{catalog_url}?coleccion=para-ti'
    if not request.user.is_authenticated:
        recommendations_url = redirect_to_login(recommendations_url).url
    return render(request, 'explorar_descubrir.html', {
        'catalog_url': catalog_url,
        'recommendations_url': recommendations_url,
        'quick_prices': EXPLORE_PRICE_CHOICES[:4],
    })


def explorar_catalogo(request):
    catalog_params = request.GET.copy()
    version = catalog_params.pop(RECOMMENDATION_VERSION_PARAM, [None])[-1]
    personalized = request.GET.get('coleccion') == 'para-ti'
    if personalized and not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    if personalized and request.user.is_staff:
        catalog_params.pop('coleccion', None)
        url = reverse('explorar_catalogo')
        return redirect(f'{url}?{catalog_params.urlencode()}' if catalog_params else url)

    page = request.GET.get('page')
    try:
        page_number = max(1, int(page))
    except (TypeError, ValueError):
        page_number = 1

    games = Game.objects.all()
    recommendation_genres = ''
    has_recommendations = False
    if personalized:
        signer = signing.Signer(salt='explore.recommendations')
        if version is not None:
            try:
                requested_fingerprint, requested_expiry = signer.unsign_object(version)
            except signing.BadSignature:
                return _restart_recommendations(catalog_params)
            if requested_expiry <= time():
                return _restart_recommendations(catalog_params)
        elif page_number > 1:
            return _restart_recommendations(catalog_params)

        library_revision = request.session.get(RECOMMENDATION_LIBRARY_REVISION, '')
        recommendations, recommendation_genres, fingerprint, expires_at = _library_recommendations(
            request.user, library_revision,
        )
        has_recommendations = bool(recommendations)
        genre_values = [labels for _, labels in recommendations]
        saved = LibraryEntry.objects.filter(user=request.user, game_id=OuterRef('pk'))
        games = games.filter(pk__in=[pk for pk, _ in recommendations]).filter(~Exists(saved))
    else:
        catalog_params.pop('coleccion', None)
        genre_values = Game.objects.order_by().values_list('genres', flat=True).distinct()
    genre = request.GET.get('genre', '')
    if genre.casefold() in Game.IGNORED_GENRES:
        # "Indie" no se ofrece como filtro; si llega por URL, se ignora.
        genre = ''
    query = request.GET.get('q', '').strip()
    sort = request.GET.get('sort', '')
    price = request.GET.get('price', '')
    source = request.GET.get('source', '')

    if source == 'studios':
        games = games.filter(publisher__isnull=False)
    else:
        source = ''

    if genre:
        games = games.filter(genres__icontains=genre)
    if query:
        games = games.filter(Q(title__icontains=query) | Q(studio__icontains=query))
    if price == 'free':
        games = games.filter(price=0)
    elif price == '5-15':
        games = games.filter(price__range=(5, 15))
    elif price == 'over-15':
        games = games.filter(price__gt=15)
    elif price:
        try:
            cap = Decimal(price)
        except InvalidOperation:
            cap = None
        if cap is None or not cap.is_finite() or cap <= 0:
            price = ''
        elif cap > Decimal('999.99'):
            games = games.filter(price__gt=0)
        else:
            # Prices are stored in cents. Round up to preserve the strict upper bound.
            cap = cap.quantize(Decimal('0.01'), rounding=ROUND_CEILING)
            games = games.filter(price__gt=0, price__lt=cap)

    if sort == 'az':
        games = games.order_by('title', 'pk')
    elif sort == 'za':
        games = games.order_by('-title', 'pk')
    elif sort == 'price_asc':
        games = games.order_by('price', 'pk')
    elif sort == 'price_desc':
        games = games.order_by('-price', 'pk')
    elif sort == 'newest':
        games = games.order_by('-year', 'pk')
    elif sort == 'added':
        games = games.order_by('-pk')
    else:
        sort = ''
        games = games.order_by('-pk' if personalized else 'pk')

    genre_set = {
        genre.strip()
        for value in genre_values
        for genre in value.split(',')
        if genre.strip() and genre.strip().casefold() not in Game.IGNORED_GENRES
    }
    genres = sorted(genre_set)
    if personalized:
        # The bounded ID list replaces a COUNT and also detects changes in filtered order.
        ordered_ids = list(games.values_list('pk', flat=True))
        fingerprint = sha256(json.dumps((fingerprint, ordered_ids)).encode()).hexdigest()
        if version is None:
            version = signer.sign_object((fingerprint, expires_at))
        elif requested_fingerprint != fingerprint:
            return _restart_recommendations(catalog_params)

        paginator = Paginator(ordered_ids, RECOMMENDATION_PAGE_SIZE)
        page_obj = paginator.get_page(page_number)
        page_games = games.in_bulk(page_obj.object_list)
        page_obj.object_list = [page_games[pk] for pk in page_obj.object_list if pk in page_games]
    else:
        paginator = Paginator(games, 24)
        page_obj = paginator.get_page(page_number)
    page_range = [
        None if number == paginator.ELLIPSIS else number
        for number in paginator.get_elided_page_range(page_obj.number, on_each_side=1, on_ends=1)
    ]
    for name, value in {
        'q': query,
        'genre': genre,
        'sort': sort,
        'price': price,
        'source': source,
    }.items():
        if value:
            catalog_params[name] = value
        else:
            catalog_params.pop(name, None)
    catalog_params.pop('page', None)
    pagination_params = catalog_params.copy()
    if personalized:
        pagination_params[RECOMMENDATION_VERSION_PARAM] = version

    if not personalized and request.user.is_authenticated and not request.user.is_staff:
        page_obj.object_list = list(page_obj.object_list)
        visible_ids = [game.pk for game in page_obj.object_list]
        in_library = set(
            LibraryEntry.objects.filter(user=request.user, game_id__in=visible_ids)
            .values_list('game_id', flat=True)
        )
    else:
        in_library = set()

    custom_price_label = f'Menos de ${price}' if price and price not in EXPLORE_PRICE_LABELS else ''

    return render(request, 'explorar.html', {
        'games': page_obj,
        'page_range': page_range,
        'catalog_params': catalog_params,
        'pagination_params': pagination_params,
        'genres': genres,
        'personalized': personalized,
        'has_recommendations': has_recommendations,
        'recommendation_genres': recommendation_genres,
        'price_choices': EXPLORE_PRICE_CHOICES,
        'price_label': EXPLORE_PRICE_LABELS.get(price, custom_price_label),
        'custom_price_label': custom_price_label,
        'genre': genre,
        'q': query,
        'sort': sort,
        'price': price,
        'source': source,
        'in_library': in_library,
    })


def game_detail(request, slug):
    game = get_object_or_404(Game.objects.select_related('publisher'), slug=slug)
    first_genre = game.genre_list()[0] if game.genre_list() else None
    related = []
    if first_genre:
        related = (
            Game.objects.filter(genres__icontains=first_genre)
            .exclude(pk=game.pk)
            .order_by('?')[:4]
        )
    if request.user.is_authenticated:
        in_library = LibraryEntry.objects.filter(user=request.user, game=game).first()
        related_ids = [related_game.pk for related_game in related]
        related_in_library = set(
            LibraryEntry.objects.filter(user=request.user, game_id__in=related_ids)
            .values_list('game_id', flat=True)
        )
    else:
        in_library = None
        related_in_library = set()

    discussions = (
        Discussion.objects.filter(game=game)
        .select_related('author', 'author__profile')
        .annotate(reply_count=Count('replies'))
        .order_by('-is_pinned', '-last_activity_at')[:3]
    )
    recent_replies = (
        DiscussionReply.objects.filter(discussion__game=game)
        .select_related('author', 'author__profile', 'discussion')
        .order_by('-created_at')[:4]
    )

    rating_ctx = get_game_rating_context(game, None)
    rating_ctx['user_library_entry'] = in_library

    return render(request, 'game_detail.html', {
        'game': game,
        'related': related,
        'in_library': in_library,
        'related_in_library': related_in_library,
        'discussions': discussions,
        'recent_replies': recent_replies,
        'discussion_count': Discussion.objects.filter(game=game).count(),
        **rating_ctx,
    })


def _back_redirect(request):
    """Vuelve a la página anterior solo si es del mismo sitio."""
    referer = request.META.get('HTTP_REFERER')
    if referer and url_has_allowed_host_and_scheme(
        referer,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return HttpResponseRedirect(referer)
    return HttpResponseRedirect(reverse('explorar'))


@login_required
@require_POST
def add_to_library(request, game_id):
    if request.user.is_staff:
        return redirect('panel_dashboard')

    game = get_object_or_404(Game, pk=game_id)
    _, created = LibraryEntry.objects.get_or_create(
        user=request.user,
        game=game,
        defaults={'status': LibraryEntry.Status.WANT},
    )
    if created:
        request.session[RECOMMENDATION_LIBRARY_REVISION] = uuid4().hex
    return _back_redirect(request)


@login_required
@require_POST
def remove_from_library(request, game_id):
    if request.user.is_staff:
        return redirect('panel_dashboard')

    game = get_object_or_404(Game, pk=game_id)
    deleted, _ = LibraryEntry.objects.filter(user=request.user, game=game).delete()
    if deleted:
        request.session[RECOMMENDATION_LIBRARY_REVISION] = uuid4().hex
    return _back_redirect(request)


@login_required
@require_POST
def update_library_status(request, entry_id):
    if request.user.is_staff:
        return redirect('panel_dashboard')

    entry = get_object_or_404(LibraryEntry, pk=entry_id, user=request.user)
    status = request.POST.get('status')

    if status not in LibraryEntry.Status.values:
        messages.error(request, 'El estado indicado no es válido.')
    elif entry.status != status:
        entry.status = status
        entry.save(update_fields=['status'])
        messages.success(
            request,
            f'“{entry.game.title}” ahora está en {entry.status}.',
        )

    return redirect('biblioteca')


def custom_404(request, exception=None):
    return render(request, '404.html', status=404)


@login_required
def biblioteca(request):
    if request.user.is_staff:
        return redirect('panel_dashboard')

    groups = [
        ('Quiero jugar', 'Pendiente'),
        ('Jugando', 'En curso'),
        ('Terminados', 'Terminado'),
    ]
    group_data = [
        {
            'title': title,
            'status': status,
            'count': LibraryEntry.objects.filter(user=request.user, status=status).count(),
            'entries': LibraryEntry.objects.filter(
                user=request.user, status=status
            ).select_related('game'),
        }
        for title, status in groups
    ]
    return render(request, 'biblioteca.html', {
        'groups': group_data,
        'statuses': LibraryEntry.Status.choices,
    })


def suscripcion(request):
    return render(request, 'suscripcion.html')


@login_required
def estadisticas(request):
    """Panel personal con cuatro gráficos de la biblioteca del usuario."""
    if request.user.is_staff:
        return redirect('panel_stats')
    return render(request, 'estadisticas.html', user_stats(request.user))


@login_required
def perfil(request):
    """Permite personalizar la cuenta y subir una foto de perfil."""
    profile, _ = Profile.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        form = ProfileForm(
            request.POST,
            request.FILES,
            instance=profile,
            user=request.user,
        )
        if form.is_valid():
            form.save()
            messages.success(request, 'Tu perfil se actualizó correctamente.')
            return redirect('perfil')
    else:
        form = ProfileForm(instance=profile, user=request.user)

    return render(request, 'perfil.html', {
        'form': form,
        'profile': profile,
    })


def profile_avatar(request, user_id):
    """Entrega la foto de perfil que vive en la base de datos."""
    row = (
        Profile.objects.filter(user_id=user_id)
        .values_list('avatar_data', 'avatar_mime')
        .first()
    )
    if not row or not row[0]:
        raise Http404('Este perfil no tiene foto.')

    payload = bytes(row[0])
    response = HttpResponse(payload, content_type=row[1] or 'image/jpeg')
    # La URL lleva la versión de la foto, así que se puede cachear sin miedo.
    response['Cache-Control'] = 'public, max-age=604800, immutable'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


# Panel de comunidad

def _discussion_queryset():
    return (
        Discussion.objects
        .select_related('author', 'author__profile', 'game')
        .annotate(reply_count=Count('replies'))
        .order_by('-is_pinned', '-last_activity_at')
    )


def _discussion_categories(queryset=None):
    """Categorías con su número de temas para el filtro lateral."""
    base = queryset if queryset is not None else Discussion.objects.all()
    counts = {
        row['category']: row['total']
        for row in base.values('category').annotate(total=Count('id'))
    }
    return [
        {
            'value': value,
            'label': label,
            'count': counts.get(value, 0),
        }
        for value, label in Discussion.Category.choices
    ]


def _filter_discussions(request, queryset):
    """Aplica búsqueda, categoría y alcance a una lista de temas."""
    category = request.GET.get('category', '')
    if category in Discussion.Category.values:
        queryset = queryset.filter(category=category)
    else:
        category = ''

    query = request.GET.get('q', '').strip()
    if query:
        queryset = queryset.filter(
            Q(title__icontains=query)
            | Q(body__icontains=query)
            | Q(game__title__icontains=query)
            | Q(author__username__icontains=query)
        )

    scope = request.GET.get('scope', '')
    if scope == 'general':
        queryset = queryset.filter(game__isnull=True)
    elif scope == 'games':
        queryset = queryset.filter(game__isnull=False)
    else:
        scope = ''

    return queryset, {
        'category': category,
        'q': query,
        'scope': scope,
    }


def community(request):
    """Panel general de discusión, con temas de juegos y temas libres."""
    queryset, filters = _filter_discussions(request, _discussion_queryset())
    page_obj = Paginator(queryset, 15).get_page(request.GET.get('page'))

    return render(request, 'community.html', {
        **filters,
        'page_obj': page_obj,
        'categories': _discussion_categories(),
        'total_threads': Discussion.objects.count(),
        'total_replies': DiscussionReply.objects.count(),
        'total_games': (
            Discussion.objects.filter(game__isnull=False)
            .values('game')
            .distinct()
            .count()
        ),
    })


def game_community(request, slug):
    """Panel de discusión de un juego concreto."""
    game = get_object_or_404(Game, slug=slug)
    queryset, filters = _filter_discussions(
        request,
        _discussion_queryset().filter(game=game),
    )
    page_obj = Paginator(queryset, 15).get_page(request.GET.get('page'))

    return render(request, 'game_community.html', {
        **filters,
        'game': game,
        'page_obj': page_obj,
        'categories': _discussion_categories(
            Discussion.objects.filter(game=game)
        ),
        'total_threads': Discussion.objects.filter(game=game).count(),
        'total_replies': DiscussionReply.objects.filter(
            discussion__game=game
        ).count(),
    })


@login_required
def discussion_create(request, slug=None):
    """Crea un tema general o dentro de la comunidad de un juego."""
    game = get_object_or_404(Game, slug=slug) if slug else None

    if request.method == 'POST':
        form = DiscussionForm(request.POST)
        if form.is_valid():
            discussion = form.save(commit=False)
            discussion.author = request.user
            discussion.game = game
            discussion.last_activity_at = timezone.now()
            discussion.save()
            messages.success(request, 'Tu tema se publicó en la comunidad.')
            return redirect('discussion_detail', discussion.pk)
    else:
        form = DiscussionForm()

    return render(request, 'discussion_form.html', {
        'form': form,
        'game': game,
    })


def discussion_detail(request, discussion_id):
    """Tema con sus comentarios y el formulario para responder."""
    discussion = get_object_or_404(
        Discussion.objects.select_related(
            'author', 'author__profile', 'game', 'game__publisher'
        ),
        pk=discussion_id,
    )
    replies = discussion.replies.select_related(
        'author', 'author__profile'
    )
    reply_form = DiscussionReplyForm()

    return render(request, 'discussion_detail.html', {
        'discussion': discussion,
        'replies': replies,
        'reply_form': reply_form,
        'can_moderate': request.user.is_staff,
    })


@login_required
@require_POST
def discussion_reply(request, discussion_id):
    discussion = get_object_or_404(Discussion, pk=discussion_id)

    if discussion.is_locked:
        messages.error(request, 'Este tema está cerrado; no admite comentarios.')
        return redirect('discussion_detail', discussion.pk)

    form = DiscussionReplyForm(request.POST)
    if form.is_valid():
        reply = form.save(commit=False)
        reply.discussion = discussion
        reply.author = request.user
        reply.save()
        Discussion.objects.filter(pk=discussion.pk).update(
            last_activity_at=timezone.now()
        )
        messages.success(request, 'Tu comentario se publicó.')
        return redirect(
            f'{reverse("discussion_detail", args=[discussion.pk])}#reply-{reply.pk}'
        )

    first_error = next(iter(form.errors.values()), None)
    messages.error(
        request,
        first_error[0] if first_error else 'No pudimos publicar el comentario.',
    )
    return redirect('discussion_detail', discussion.pk)


@login_required
@require_POST
def discussion_delete(request, discussion_id):
    discussion = get_object_or_404(
        Discussion.objects.select_related('game'),
        pk=discussion_id,
    )
    if request.user != discussion.author and not request.user.is_staff:
        raise PermissionDenied

    title = discussion.title
    game_slug = discussion.game.slug if discussion.game else None
    discussion.delete()
    messages.success(request, f'Se eliminó el tema «{title}».')

    if game_slug:
        return redirect('game_community', slug=game_slug)
    return redirect('community')


@login_required
@require_POST
def reply_delete(request, reply_id):
    reply = get_object_or_404(
        DiscussionReply.objects.select_related('discussion'),
        pk=reply_id,
    )
    if request.user != reply.author and not request.user.is_staff:
        raise PermissionDenied

    discussion_id = reply.discussion_id
    reply.delete()
    messages.success(request, 'Se eliminó el comentario.')
    return redirect('discussion_detail', discussion_id)


@login_required
@require_POST
def discussion_moderate(request, discussion_id):
    if not request.user.is_staff:
        raise PermissionDenied

    discussion = get_object_or_404(Discussion, pk=discussion_id)
    action = request.POST.get('action')

    if action == 'pin':
        discussion.is_pinned = True
    elif action == 'unpin':
        discussion.is_pinned = False
    elif action == 'lock':
        discussion.is_locked = True
    elif action == 'unlock':
        discussion.is_locked = False
    else:
        messages.error(request, 'La acción de moderación no es válida.')
        return redirect('discussion_detail', discussion.pk)

    discussion.save(update_fields=['is_pinned', 'is_locked'])
    messages.success(request, 'El tema se actualizó.')
    return redirect('discussion_detail', discussion.pk)


# Perfil público, privacidad y seguridad

def public_profile(request, username):
    """Perfil que ve el resto de la comunidad, según sus ajustes de privacidad."""
    target = get_object_or_404(get_user_model(), username=username)
    profile, _ = Profile.objects.get_or_create(user=target)
    visible = profile.is_visible_to(request.user)

    context = {
        'profile_user': target,
        'profile': profile,
        'is_private': not visible,
        'is_self': request.user == target,
    }

    if visible:
        if profile.show_stats:
            stats = user_stats(target)
            status_chart = stats['charts'][0]
            genre_chart = stats['charts'][1]
            values = status_chart['values']
            context['summary'] = {
                'total': sum(values),
                'want': values[0],
                'playing': values[1],
                'done': values[2],
                'coverage': stats['coverage'],
                'genres': list(zip(
                    genre_chart['labels'][:4],
                    genre_chart['values'][:4],
                )),
            }

        if profile.show_library:
            context['library_entries'] = (
                LibraryEntry.objects.filter(user=target)
                .select_related('game')
                .order_by('status', 'game__title')[:12]
            )

        if profile.show_discussions:
            context['recent_discussions'] = (
                Discussion.objects.filter(author=target)
                .select_related('game')
                .annotate(reply_count=Count('replies'))
                .order_by('-last_activity_at')[:5]
            )

    return render(request, 'public_profile.html', context)


@login_required
def privacy(request):
    """Ajustes de visibilidad del perfil público."""
    profile, _ = Profile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        form = PrivacyForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, 'Tus ajustes de privacidad se guardaron.')
            return redirect('privacy')
    else:
        form = PrivacyForm(instance=profile)

    return render(request, 'privacy.html', {
        'form': form,
        'profile': profile,
    })


@login_required
def account_export(request):
    """Descarga en JSON los datos que la cuenta tiene en IndieVault."""
    user = request.user
    profile, _ = Profile.objects.get_or_create(user=user)

    entries = (
        LibraryEntry.objects.filter(user=user)
        .select_related('game')
        .order_by('status', 'game__title')
    )
    discussions = (
        Discussion.objects.filter(author=user)
        .select_related('game')
        .annotate(reply_count=Count('replies'))
        .order_by('-created_at')
    )
    replies = (
        DiscussionReply.objects.filter(author=user)
        .select_related('discussion')
        .order_by('-created_at')
    )

    payload = {
        'cuenta': {
            'usuario': user.username,
            'nombre': user.get_full_name(),
            'correo': user.email,
            'registrado': user.date_joined.isoformat(),
            'ultimo_acceso': user.last_login.isoformat() if user.last_login else None,
        },
        'perfil': {
            'biografia': profile.bio,
            'visibilidad': profile.get_visibility_display(),
            'mostrar_biblioteca': profile.show_library,
            'mostrar_estadisticas': profile.show_stats,
            'mostrar_comunidad': profile.show_discussions,
            'tiene_foto': bool(profile.avatar_data),
        },
        'biblioteca': [
            {
                'juego': entry.game.title,
                'estudio': entry.game.studio,
                'estado': entry.status,
            }
            for entry in entries
        ],
        'temas': [
            {
                'titulo': discussion.title,
                'juego': discussion.game.title if discussion.game else None,
                'categoria': discussion.category,
                'creado': discussion.created_at.isoformat(),
                'comentarios': discussion.reply_count,
            }
            for discussion in discussions
        ],
        'comentarios': [
            {
                'tema': reply.discussion.title,
                'texto': reply.body,
                'creado': reply.created_at.isoformat(),
            }
            for reply in replies
        ],
    }

    response = HttpResponse(
        json.dumps(payload, ensure_ascii=False, indent=2),
        content_type='application/json; charset=utf-8',
    )
    response['Content-Disposition'] = (
        f'attachment; filename="indievault-{user.username}.json"'
    )
    return response


def _device_label(user_agent):
    """Etiqueta legible para la lista de sesiones activas."""
    if not user_agent:
        return 'Dispositivo sin identificar'

    ua = user_agent.lower()
    browser = 'Navegador'
    for token, name in (
        ('edg/', 'Edge'),
        ('firefox', 'Firefox'),
        ('chrome', 'Chrome'),
        ('safari', 'Safari'),
        ('opera', 'Opera'),
    ):
        if token in ua:
            browser = name
            break

    system = ''
    for token, name in (
        ('windows', 'Windows'),
        ('android', 'Android'),
        ('iphone', 'iPhone'),
        ('ipad', 'iPad'),
        ('mac os', 'macOS'),
        ('linux', 'Linux'),
    ):
        if token in ua:
            system = name
            break

    return f'{browser} · {system}' if system else browser


def _user_sessions(request):
    """Sesiones abiertas de la cuenta, marcando la actual."""
    current_key = request.session.session_key
    rows = []
    now = timezone.now()

    for session in Session.objects.filter(expire_date__gte=now).order_by('-expire_date'):
        try:
            data = session.get_decoded()
        except Exception:
            continue
        if data.get('_auth_user_id') != str(request.user.pk):
            continue
        rows.append({
            'key': session.session_key,
            'current': session.session_key == current_key,
            'device': _device_label(data.get('iv_ua', '')),
            'ip': data.get('iv_ip') or 'No registrada',
            'expires': session.expire_date,
        })

    rows.sort(key=lambda row: not row['current'])
    return rows


@login_required
def security(request):
    """Cambio de contraseña y control de las sesiones abiertas."""
    profile, _ = Profile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(
                request,
                'Tu contraseña se actualizó. Las demás sesiones se cerraron.',
            )
            return redirect('security')
    else:
        form = PasswordChangeForm(request.user)

    previous_login = parse_datetime(
        request.session.get('iv_previous_login', '')
    )

    return render(request, 'security.html', {
        'form': form,
        'profile': profile,
        'sessions': _user_sessions(request),
        'previous_login': previous_login,
    })


@login_required
@require_POST
def close_other_sessions(request):
    current_key = request.session.session_key
    removed = 0

    for session in Session.objects.filter(expire_date__gte=timezone.now()):
        try:
            data = session.get_decoded()
        except Exception:
            continue
        if (
            data.get('_auth_user_id') == str(request.user.pk)
            and session.session_key != current_key
        ):
            session.delete()
            removed += 1

    if removed:
        messages.success(request, f'Cerramos {removed} sesión(es) en otros dispositivos.')
    else:
        messages.info(request, 'No había otras sesiones abiertas.')
    return redirect('security')


@login_required
@require_POST
def close_all_sessions(request):
    for session in Session.objects.filter(expire_date__gte=timezone.now()):
        try:
            data = session.get_decoded()
        except Exception:
            continue
        if data.get('_auth_user_id') == str(request.user.pk):
            session.delete()

    auth_logout(request)
    return redirect('index')



ACCENT_PRESETS = [
    ('#d6f36a', 'Lima'),
    ('#c2a8ff', 'Lila'),
    ('#7dd3fc', 'Cielo'),
    ('#fbbf24', 'Ámbar'),
    ('#fb7185', 'Coral'),
    ('#4ade80', 'Menta'),
]


@login_required
def apariencia(request):
    """Pantalla para elegir la paleta personal del usuario."""
    profile, _ = Profile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        form = AppearanceForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, 'Tu paleta se actualizó correctamente.')
            return redirect('apariencia')
    else:
        form = AppearanceForm(instance=profile)

    return render(request, 'apariencia.html', {
        'form': form,
        'profile': profile,
        'presets': ACCENT_PRESETS,
    })


def _mark_session(request):
    """Guarda datos mínimos para mostrar las sesiones activas al usuario."""
    request.session['iv_ip'] = request.META.get('REMOTE_ADDR', '')
    request.session['iv_ua'] = (request.META.get('HTTP_USER_AGENT') or '')[:300]


def _finish_login(request, user):
    """Inicia sesión y registra el acceso anterior para la pantalla de seguridad."""
    previous = user.last_login
    auth_login(request, user)
    _mark_session(request)
    if previous:
        request.session['iv_previous_login'] = previous.isoformat()


def _has_enterprise(user):
    return getattr(user, 'enterprise', None) is not None


def _redirect_after_login(request, user, next_url=''):
    """Un solo login: el tipo de cuenta decide el destino."""
    if user.is_staff:
        # El personal siempre aterriza en su panel, aunque llegue con ?next=.
        return redirect('panel_dashboard')
    if _has_enterprise(user):
        return redirect('enterprise_dashboard')
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect('index')


def register_view(request):
    """Registro de jugador con usuario y contraseña; no pide correo."""
    if request.user.is_authenticated:
        return redirect('index')

    next_url = request.POST.get('next') or request.GET.get('next') or ''

    if request.method == 'POST':
        form = AccountCreateForm(request.POST)
        if form.is_valid():
            user = form.save()
            _finish_login(request, user)
            messages.success(
                request,
                f'Bienvenido, {user.username}. Tu cuenta está lista.',
            )
            if next_url and url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                return redirect(next_url)
            return redirect('index')
    else:
        form = AccountCreateForm()

    return render(request, 'register.html', {
        'form': form,
        'next': next_url,
    })


def login_view(request):
    """Login único para jugadores, empresas y administradores.

    No hay pestaña de administrador: si la cuenta tiene is_staff,
    se redirige al panel de gestión propio de IndieVault.
    """
    if request.user.is_authenticated:
        return _redirect_after_login(request, request.user)

    next_url = request.POST.get('next') or request.GET.get('next') or ''

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            _finish_login(request, user)
            return _redirect_after_login(request, user, next_url)
    else:
        form = AuthenticationForm(request)

    return render(request, 'login.html', {
        'form': form,
        'next': next_url,
    })


def enterprise_login_view(request):
    """Acceso exclusivo para cuentas de empresa."""
    if request.user.is_authenticated:
        if _has_enterprise(request.user):
            return redirect('enterprise_dashboard')
        return redirect('index')

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            if not _has_enterprise(user):
                form.add_error(None, 'Esta cuenta no es de empresa. Usa el acceso normal.')
            else:
                _finish_login(request, user)
                return redirect('enterprise_dashboard')
    else:
        form = AuthenticationForm(request)

    return render(request, 'enterprise_login.html', {'form': form})


def enterprise_register_view(request):
    """Registro de una cuenta de empresa y acceso automático."""
    if request.user.is_authenticated:
        return redirect('index')

    if request.method == 'POST':
        form = EnterpriseSignupForm(request.POST)
        if form.is_valid():
            enterprise = form.save()
            _finish_login(request, enterprise.user)
            messages.success(request, 'Cuenta de empresa creada. Ya puedes publicar tus juegos.')
            return redirect('enterprise_dashboard')
    else:
        form = EnterpriseSignupForm()

    return render(request, 'enterprise_register.html', {'form': form})


@login_required(login_url='enterprise_login')
def enterprise_dashboard(request):
    enterprise = getattr(request.user, 'enterprise', None)
    if enterprise is None:
        return redirect('enterprise_login')

    games = list(
        enterprise.games.annotate(
            library_total=Count('library_entries', distinct=True),
            playing_total=Count(
                'library_entries',
                filter=Q(library_entries__status=LibraryEntry.Status.PLAYING),
                distinct=True,
            ),
            done_total=Count(
                'library_entries',
                filter=Q(library_entries__status=LibraryEntry.Status.DONE),
                distinct=True,
            ),
            discussion_total=Count('discussions', distinct=True),
        ).order_by('-id')
    )
    published_count = len(games)
    total_saves = sum(game.library_total for game in games)
    playing_count = sum(game.playing_total for game in games)
    done_count = sum(game.done_total for game in games)
    pending_count = max(total_saves - playing_count - done_count, 0)
    threads_count = sum(game.discussion_total for game in games)
    replies_count = DiscussionReply.objects.filter(
        discussion__game__publisher=enterprise
    ).count()
    completion_rate = round(done_count * 100 / total_saves) if total_saves else 0

    kpis = [
        {
            'label': 'Juegos publicados',
            'value': published_count,
            'note': 'En el catálogo de IndieVault',
        },
        {
            'label': 'En bibliotecas',
            'value': total_saves,
            'note': f'{pending_count} pendientes · {playing_count} en curso',
        },
        {
            'label': 'Terminados',
            'value': done_count,
            'note': (
                f'{completion_rate}% de tasa de finalización'
                if total_saves
                else 'Sin partidas registradas'
            ),
        },
        {
            'label': 'Comunidad',
            'value': threads_count,
            'note': f'{replies_count} comentario{"" if replies_count == 1 else "s"} en tus juegos',
        },
    ]

    recent_discussions = list(
        Discussion.objects.filter(game__publisher=enterprise)
        .select_related('author', 'game')
        .annotate(reply_count=Count('replies'))
        .order_by('-last_activity_at')[:5]
    )

    return render(request, 'enterprise_dashboard.html', {
        'enterprise': enterprise,
        'games': games,
        'published_count': published_count,
        'kpis': kpis,
        'recent_discussions': recent_discussions,
    })


@login_required(login_url='enterprise_login')
def enterprise_publish(request):
    enterprise = getattr(request.user, 'enterprise', None)
    if enterprise is None:
        return redirect('enterprise_login')

    if request.method == 'POST':
        form = GameForm(request.POST)
        if form.is_valid():
            game = form.save(commit=False)
            game.publisher = enterprise
            game.studio = enterprise.studio_name
            game.save()
            messages.success(request, f'“{game.title}” se publicó correctamente.')
            return redirect('enterprise_dashboard')
    else:
        form = GameForm()

    return render(request, 'enterprise_publish.html', {
        'enterprise': enterprise,
        'form': form,
    })


@login_required(login_url='enterprise_login')
def enterprise_game_edit(request, game_id):
    enterprise = getattr(request.user, 'enterprise', None)
    if enterprise is None:
        return redirect('enterprise_login')

    game = get_object_or_404(Game, pk=game_id, publisher=enterprise)

    if request.method == 'POST':
        form = GameForm(request.POST, instance=game)
        if form.is_valid():
            updated = form.save(commit=False)
            updated.publisher = enterprise
            updated.studio = enterprise.studio_name
            updated.save()
            messages.success(request, f'“{updated.title}” se actualizó correctamente.')
            return redirect('enterprise_dashboard')
    else:
        form = GameForm(instance=game)

    return render(request, 'enterprise_publish.html', {
        'enterprise': enterprise,
        'form': form,
        'game': game,
        'is_edit': True,
    })


@require_POST
def logout_view(request):
    auth_logout(request)
    return redirect('index')
