from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import DatabaseError, transaction
from django.db.models import Avg, Count, Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import (
    Discussion,
    Game,
    LibraryEntry,
    LibraryReview,
    Notification,
    Profile,
)

SEARCH_TYPES = (
    ('all', 'Todo'),
    ('games', 'Juegos'),
    ('community', 'Comunidad'),
    ('profiles', 'Perfiles'),
)
VALID_SEARCH_TYPES = {key for key, _ in SEARCH_TYPES}


def _safe_back_redirect(request, default_url_name='biblioteca'):
    """Redirige a `next` o `HTTP_REFERER` solo cuando pertenecen a este host."""
    for candidate in (request.POST.get('next'), request.META.get('HTTP_REFERER')):
        if candidate and url_has_allowed_host_and_scheme(
            candidate,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return HttpResponseRedirect(candidate)
    return HttpResponseRedirect(reverse(default_url_name))


def get_game_rating_context(game, user):
    """Contexto de valoraciones y micro-reseñas listo para la ficha de juego."""
    try:
        with transaction.atomic():
            rated_qs = LibraryReview.objects.filter(entry__game=game)
            stats = rated_qs.aggregate(avg=Avg('rating'), total=Count('pk'))
            rating_avg = (
                round(float(stats['avg']), 1) if stats['avg'] is not None else None
            )
            rating_count = stats['total'] or 0
            rated_entries = list(
                rated_qs.select_related(
                    'entry', 'entry__user', 'entry__user__profile'
                ).order_by('-updated_at', '-pk')[:5]
            )
    except DatabaseError:
        rating_avg = None
        rating_count = 0
        rated_entries = []

    if user is not None and user.is_authenticated and user.pk is not None:
        user_library_entry = LibraryEntry.objects.filter(user=user, game=game).first()
    else:
        user_library_entry = None

    return {
        'rating_avg': rating_avg,
        'rating_count': rating_count,
        'rated_entries': rated_entries,
        'user_library_entry': user_library_entry,
    }


@login_required
@require_POST
def rate_library_entry(request, entry_id):
    """Guarda o limpia la valoración (1-5 ★) y micro-reseña de un juego terminado."""
    if request.user.is_staff:
        return redirect('panel_dashboard')

    entry = get_object_or_404(
        LibraryEntry.objects.select_related('game'),
        pk=entry_id,
        user=request.user,
    )

    # Requisito del dominio: solo se pueden valorar juegos marcados como «Terminado».
    if entry.status != LibraryEntry.Status.DONE:
        messages.error(
            request,
            'Solo puedes valorar juegos que hayas marcado como Terminado.',
        )
        return _safe_back_redirect(request, 'biblioteca')

    raw_rating = request.POST.get('rating', '').strip()
    review = request.POST.get('review', '').strip()

    if len(review) > 280:
        messages.error(
            request,
            'La micro-reseña no puede superar los 280 caracteres.',
        )
        return _safe_back_redirect(request, 'biblioteca')

    if raw_rating == '':
        try:
            with transaction.atomic():
                LibraryReview.objects.filter(entry=entry).delete()
        except DatabaseError:
            messages.error(
                request,
                'Las valoraciones aún no están habilitadas en esta base de datos.',
            )
            return _safe_back_redirect(request, 'biblioteca')
        messages.success(
            request,
            f'Se eliminó tu valoración de «{entry.game.title}».',
        )
        return _safe_back_redirect(request, 'biblioteca')

    try:
        rating_value = int(raw_rating)
    except (TypeError, ValueError):
        rating_value = None

    if rating_value is None or not (1 <= rating_value <= 5):
        messages.error(
            request,
            'La valoración debe ser un número entero entre 1 y 5 estrellas.',
        )
        return _safe_back_redirect(request, 'biblioteca')

    try:
        with transaction.atomic():
            LibraryReview.objects.update_or_create(
                entry=entry,
                defaults={'rating': rating_value, 'review': review},
            )
    except DatabaseError:
        messages.error(
            request,
            'Las valoraciones aún no están habilitadas en esta base de datos.',
        )
        return _safe_back_redirect(request, 'biblioteca')

    messages.success(
        request,
        f'Guardaste {rating_value} ★ para «{entry.game.title}».',
    )
    return _safe_back_redirect(request, 'biblioteca')


def _visible_profiles_queryset(viewer, query):
    """Busca perfiles activos respetando la privacidad en SQL antes de paginar."""
    queryset = (
        Profile.objects.select_related('user')
        .filter(
            Q(user__username__icontains=query)
            | Q(user__first_name__icontains=query)
            | Q(user__last_name__icontains=query)
            | Q(bio__icontains=query)
        )
        .exclude(user__is_active=False)
    )

    if not viewer.is_authenticated:
        queryset = queryset.filter(visibility=Profile.Visibility.PUBLIC)
    elif not viewer.is_staff:
        visibility_filter = Q(
            visibility__in=[
                Profile.Visibility.PUBLIC,
                Profile.Visibility.MEMBERS,
            ]
        )
        if viewer.pk is not None:
            visibility_filter |= Q(user=viewer)
        queryset = queryset.filter(visibility_filter)

    return queryset.order_by('user__username', 'pk')


def search_global(request):
    """Buscador transversal de juegos, temas de comunidad y perfiles visibles."""
    query = request.GET.get('q', '').strip()
    search_type = request.GET.get('type', 'all').strip().lower()
    if search_type not in VALID_SEARCH_TYPES:
        search_type = 'all'
    page = request.GET.get('page')

    games_count = 0
    community_count = 0
    profiles_count = 0
    games_results = []
    community_results = []
    profiles_results = []
    page_obj = None
    in_library = set()

    if query:
        games_qs = Game.objects.filter(
            Q(title__icontains=query)
            | Q(studio__icontains=query)
            | Q(genres__icontains=query)
        ).order_by('title', 'pk')

        community_qs = (
            Discussion.objects.filter(
                Q(title__icontains=query)
                | Q(body__icontains=query)
                | Q(game__title__icontains=query)
            )
            .select_related('author', 'author__profile', 'game')
            .annotate(reply_count=Count('replies'))
            .order_by('-is_pinned', '-last_activity_at')
        )

        profiles_qs = _visible_profiles_queryset(request.user, query)

        games_count = games_qs.count()
        community_count = community_qs.count()
        profiles_count = profiles_qs.count()

        if search_type == 'all':
            games_results = list(games_qs[:6])
            community_results = list(community_qs[:6])
            profiles_results = [
                profile
                for profile in profiles_qs[:6]
                if profile.is_visible_to(request.user)
            ]
        elif search_type == 'games':
            page_obj = Paginator(games_qs, 12).get_page(page)
            page_obj.object_list = list(page_obj.object_list)
            games_results = page_obj.object_list
        elif search_type == 'community':
            page_obj = Paginator(community_qs, 12).get_page(page)
            page_obj.object_list = list(page_obj.object_list)
            community_results = page_obj.object_list
        elif search_type == 'profiles':
            page_obj = Paginator(profiles_qs, 12).get_page(page)
            page_obj.object_list = [
                profile
                for profile in page_obj.object_list
                if profile.is_visible_to(request.user)
            ]
            profiles_results = page_obj.object_list

        if (
            games_results
            and request.user.is_authenticated
            and not request.user.is_staff
            and request.user.pk is not None
        ):
            in_library = set(
                LibraryEntry.objects.filter(
                    user=request.user,
                    game_id__in=[game.pk for game in games_results],
                ).values_list('game_id', flat=True)
            )

    total_count = games_count + community_count + profiles_count
    counts_by_type = {
        'all': total_count,
        'games': games_count,
        'community': community_count,
        'profiles': profiles_count,
    }
    tabs = [
        {
            'key': key,
            'label': label,
            'count': counts_by_type[key],
            'active': search_type == key,
        }
        for key, label in SEARCH_TYPES
    ]

    return render(request, 'search_results.html', {
        'q': query,
        'search_type': search_type,
        'tabs': tabs,
        'total_count': total_count,
        'games_count': games_count,
        'community_count': community_count,
        'profiles_count': profiles_count,
        'games_results': games_results,
        'community_results': community_results,
        'profiles_results': profiles_results,
        'page_obj': page_obj,
        'in_library': in_library,
    })


@login_required
def notifications_view(request):
    """Bandeja de notificaciones internas de la cuenta."""
    try:
        with transaction.atomic():
            queryset = list(
                Notification.objects.filter(recipient=request.user).select_related(
                    'actor', 'actor__profile', 'discussion', 'reply'
                )
            )
            unread_count = Notification.objects.filter(
                recipient=request.user,
                is_read=False,
            ).count()
    except DatabaseError:
        queryset = []
        unread_count = 0

    page_obj = Paginator(queryset, 20).get_page(request.GET.get('page'))

    return render(request, 'notifications.html', {
        'notifications': page_obj,
        'page_obj': page_obj,
        'unread_count': unread_count,
    })


@login_required
@require_POST
def notification_mark_read(request, notification_id):
    """Marca una notificación propia como leída y opcionalmente abre su destino."""
    try:
        with transaction.atomic():
            notification = get_object_or_404(
                Notification,
                pk=notification_id,
                recipient=request.user,
            )
            if not notification.is_read:
                notification.is_read = True
                notification.save(update_fields=['is_read'])
    except DatabaseError:
        return redirect('notifications')

    if request.POST.get('go') and notification.target_url:
        if url_has_allowed_host_and_scheme(
            notification.target_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return HttpResponseRedirect(notification.target_url)

    return redirect('notifications')


@login_required
@require_POST
def notifications_mark_all_read(request):
    """Marca todas las notificaciones pendientes del usuario como leídas."""
    try:
        with transaction.atomic():
            updated = Notification.objects.filter(
                recipient=request.user,
                is_read=False,
            ).update(is_read=True)
    except DatabaseError:
        updated = 0
    if updated:
        messages.success(
            request,
            'Todas tus notificaciones quedaron marcadas como leídas.',
        )
    return redirect('notifications')
