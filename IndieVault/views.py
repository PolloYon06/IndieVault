from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import EnterpriseSignupForm, GameForm
from .models import Game, LibraryEntry
from .stats import user_stats


def index(request):
    return render(request, 'index.html')


def explorar(request):
    games = Game.objects.all()
    genre = request.GET.get('genre', '')
    query = request.GET.get('q', '').strip()
    sort = request.GET.get('sort', '')
    price = request.GET.get('price', '')

    if genre:
        games = games.filter(genres__icontains=genre)
    if query:
        games = games.filter(Q(title__icontains=query) | Q(studio__icontains=query))
    if price == 'free':
        games = games.filter(price=0)
    elif price:
        cap = Decimal(price)
        games = games.filter(price__gt=0, price__lt=cap)

    if sort == 'az':
        games = games.order_by('title')
    elif sort == 'za':
        games = games.order_by('-title')
    elif sort == 'price_asc':
        games = games.order_by('price')
    elif sort == 'price_desc':
        games = games.order_by('-price')
    elif sort == 'newest':
        games = games.order_by('-year')
    else:
        games = games.order_by('id')

    genre_set = {
        genre.strip()
        for value in Game.objects.values_list('genres', flat=True).distinct()
        for genre in value.split(',')
        if genre.strip()
    }
    games = Paginator(games, 24).get_page(request.GET.get('page'))

    if request.user.is_authenticated:
        in_library = set(
            LibraryEntry.objects.filter(user=request.user).values_list('game_id', flat=True)
        )
    else:
        in_library = set()

    return render(request, 'explorar.html', {
        'games': games,
        'genres': sorted(genre_set),
        'genre': genre,
        'q': query,
        'sort': sort,
        'price': price,
        'in_library': in_library,
    })


def game_detail(request, slug):
    game = get_object_or_404(Game, slug=slug)
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
    else:
        in_library = None
    return render(request, 'game_detail.html', {
        'game': game,
        'related': related,
        'in_library': in_library,
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
    game = get_object_or_404(Game, pk=game_id)
    LibraryEntry.objects.get_or_create(
        user=request.user,
        game=game,
        defaults={'status': LibraryEntry.Status.WANT},
    )
    return _back_redirect(request)


@login_required
@require_POST
def remove_from_library(request, game_id):
    game = get_object_or_404(Game, pk=game_id)
    LibraryEntry.objects.filter(user=request.user, game=game).delete()
    return _back_redirect(request)


@login_required
@require_POST
def update_library_status(request, entry_id):
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
    return render(request, 'estadisticas.html', user_stats(request.user))


def _has_enterprise(user):
    return getattr(user, 'enterprise', None) is not None


def _redirect_after_login(request, user, next_url=''):
    """Un solo login: el tipo de cuenta decide el destino."""
    if user.is_staff:
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(next_url)
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
            auth_login(request, user)
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
                auth_login(request, user)
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
            auth_login(request, enterprise.user)
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

    games = enterprise.games.all()
    return render(request, 'enterprise_dashboard.html', {
        'enterprise': enterprise,
        'games': games,
        'published_count': games.count(),
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


@require_POST
def logout_view(request):
    auth_logout(request)
    return redirect('index')