import csv
from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import AdminEnterpriseForm, AdminGameForm
from .models import Enterprise, Game, LibraryEntry
from .stats import admin_stats


def staff_required(view_func):
    """Deja pasar solo al personal; a los jugadores les devuelve un 403."""

    @login_required
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_staff:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return wrapped


def _paginate(request, queryset, per_page=12):
    return Paginator(queryset, per_page).get_page(request.GET.get('page'))


def _safe_next(request, fallback):
    next_url = request.POST.get('next') or ''
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect(fallback)


def _csv_response(filename, header, rows):
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(header)
    writer.writerows(rows)
    return response


def _filtered_games(request):
    queryset = Game.objects.select_related('publisher')
    query = request.GET.get('q', '').strip()
    price = request.GET.get('price', '')
    publisher = None

    publisher_id = request.GET.get('publisher', '')
    if publisher_id.isdigit():
        publisher = Enterprise.objects.filter(pk=publisher_id).first()
        if publisher:
            queryset = queryset.filter(publisher=publisher)

    if query:
        queryset = queryset.filter(
            Q(title__icontains=query)
            | Q(studio__icontains=query)
            | Q(genres__icontains=query)
        )
    if price == 'free':
        queryset = queryset.filter(price=0)
    elif price == 'paid':
        queryset = queryset.filter(price__gt=0)

    return queryset.order_by('-id'), {
        'q': query,
        'price': price,
        'publisher': publisher,
    }


def _filtered_enterprises(request):
    queryset = Enterprise.objects.select_related('user').annotate(
        game_count=Count('games')
    )
    query = request.GET.get('q', '').strip()
    verified = request.GET.get('verified', '')

    if query:
        queryset = queryset.filter(
            Q(studio_name__icontains=query)
            | Q(user__username__icontains=query)
            | Q(user__email__icontains=query)
        )
    if verified == 'yes':
        queryset = queryset.filter(is_verified=True)
    elif verified == 'no':
        queryset = queryset.filter(is_verified=False)

    return queryset.order_by('-created_at'), {
        'q': query,
        'verified': verified,
    }


def _filtered_users(request):
    User = get_user_model()
    queryset = User.objects.annotate(entry_count=Count('library_entries'))
    query = request.GET.get('q', '').strip()
    role = request.GET.get('role', '')

    if query:
        queryset = queryset.filter(
            Q(username__icontains=query)
            | Q(email__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
        )
    if role == 'staff':
        queryset = queryset.filter(is_staff=True)
    elif role == 'enterprise':
        queryset = queryset.filter(enterprise__isnull=False)
    elif role == 'player':
        queryset = queryset.filter(is_staff=False, enterprise__isnull=True)

    return queryset.order_by('-date_joined'), {
        'q': query,
        'role': role,
    }


def _filtered_library(request):
    queryset = LibraryEntry.objects.select_related('user', 'game')
    query = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')

    if query:
        queryset = queryset.filter(
            Q(user__username__icontains=query)
            | Q(game__title__icontains=query)
        )
    if status not in LibraryEntry.Status.values:
        status = ''
    if status:
        queryset = queryset.filter(status=status)

    return queryset.order_by('-id'), {
        'q': query,
        'status': status,
    }


@staff_required
def panel_dashboard(request):
    User = get_user_model()
    month_start = timezone.localdate().replace(day=1)

    total_games = Game.objects.count()
    free_games = Game.objects.filter(price=0).count()
    total_users = User.objects.count()
    new_users = User.objects.filter(date_joined__date__gte=month_start).count()
    total_enterprises = Enterprise.objects.count()
    pending_count = Enterprise.objects.filter(is_verified=False).count()
    total_entries = LibraryEntry.objects.count()
    done_entries = LibraryEntry.objects.filter(
        status=LibraryEntry.Status.DONE
    ).count()

    kpis = [
        {
            'label': 'Juegos',
            'value': total_games,
            'note': f'{free_games} gratis · {total_games - free_games} pagos',
            'href': reverse('panel_games'),
        },
        {
            'label': 'Usuarios',
            'value': total_users,
            'note': f'{new_users} nuevos este mes',
            'href': reverse('panel_users'),
        },
        {
            'label': 'Empresas',
            'value': total_enterprises,
            'note': f'{pending_count} sin verificar' if pending_count else 'Todas verificadas',
            'href': reverse('panel_enterprises'),
        },
        {
            'label': 'Biblioteca',
            'value': total_entries,
            'note': f'{done_entries} terminados',
            'href': reverse('panel_library'),
        },
    ]

    return render(request, 'panel/dashboard.html', {
        'panel_section': 'dashboard',
        'panel_title': 'Panel de control',
        'panel_note': 'Gestiona el catálogo, las cuentas y la actividad de IndieVault.',
        'kpis': kpis,
        'pending_count': pending_count,
        'recent_games': Game.objects.select_related('publisher').order_by('-id')[:6],
        'recent_users': User.objects.order_by('-date_joined')[:6],
        'pending_enterprises': (
            Enterprise.objects.filter(is_verified=False)
            .select_related('user')
            .order_by('-created_at')[:5]
        ),
    })


@staff_required
def panel_stats(request):
    context = admin_stats()
    context.update({
        'panel_section': 'stats',
        'panel_title': 'Estadísticas',
        'panel_note': 'Métricas del catálogo, la biblioteca y el crecimiento de la plataforma.',
    })
    return render(request, 'panel/estadisticas.html', context)


@staff_required
def panel_games(request):
    queryset, filters = _filtered_games(request)
    page_obj = _paginate(request, queryset)
    return render(request, 'panel/games.html', {
        **filters,
        'panel_section': 'games',
        'panel_title': 'Juegos',
        'panel_note': 'Crea, edita y elimina títulos del catálogo.',
        'page_obj': page_obj,
        'total': page_obj.paginator.count,
    })


@staff_required
def panel_game_create(request):
    if request.method == 'POST':
        form = AdminGameForm(request.POST)
        if form.is_valid():
            game = form.save()
            messages.success(request, f'“{game.title}” se guardó en el catálogo.')
            return redirect('panel_games')
    else:
        form = AdminGameForm()

    return render(request, 'panel/game_form.html', {
        'panel_section': 'games',
        'panel_title': 'Nuevo juego',
        'panel_note': 'Añade un título al catálogo y asígnalo a una empresa si corresponde.',
        'form': form,
        'cancel_url': reverse('panel_games'),
    })


@staff_required
def panel_game_edit(request, game_id):
    game = get_object_or_404(Game, pk=game_id)

    if request.method == 'POST':
        form = AdminGameForm(request.POST, instance=game)
        if form.is_valid():
            game = form.save()
            messages.success(request, f'“{game.title}” se actualizó correctamente.')
            return redirect('panel_games')
    else:
        form = AdminGameForm(instance=game)

    return render(request, 'panel/game_form.html', {
        'panel_section': 'games',
        'panel_title': 'Editar juego',
        'panel_note': f'Actualiza la ficha de “{game.title}”.',
        'form': form,
        'cancel_url': reverse('panel_games'),
    })


@staff_required
@require_POST
def panel_game_delete(request, game_id):
    game = get_object_or_404(Game, pk=game_id)
    title = game.title
    entries = game.library_entries.count()
    game.delete()

    message = f'“{title}” se eliminó del catálogo.'
    if entries:
        message += f' También se borraron {entries} entradas de biblioteca.'
    messages.success(request, message)
    return _safe_next(request, 'panel_games')


@staff_required
def panel_games_export(request):
    queryset, _ = _filtered_games(request)
    rows = [
        [
            game.title,
            game.studio,
            game.publisher.studio_name if game.publisher else '',
            game.genres,
            game.year,
            game.price,
            'Sí' if game.is_free else 'No',
        ]
        for game in queryset
    ]
    return _csv_response(
        'indievault-juegos.csv',
        ['Título', 'Estudio', 'Empresa', 'Géneros', 'Año', 'Precio', 'Gratis'],
        rows,
    )


@staff_required
def panel_enterprises(request):
    queryset, filters = _filtered_enterprises(request)
    page_obj = _paginate(request, queryset)
    return render(request, 'panel/enterprises.html', {
        **filters,
        'panel_section': 'enterprises',
        'panel_title': 'Empresas',
        'panel_note': 'Revisa los estudios, verifica sus cuentas y consulta su catálogo.',
        'page_obj': page_obj,
        'total': page_obj.paginator.count,
    })


@staff_required
def panel_enterprise_edit(request, enterprise_id):
    enterprise = get_object_or_404(
        Enterprise.objects.select_related('user'), pk=enterprise_id
    )

    if request.method == 'POST':
        form = AdminEnterpriseForm(request.POST, instance=enterprise)
        if form.is_valid():
            enterprise = form.save()
            messages.success(
                request,
                f'La empresa “{enterprise.studio_name}” se actualizó correctamente.',
            )
            return redirect('panel_enterprises')
    else:
        form = AdminEnterpriseForm(instance=enterprise)

    return render(request, 'panel/enterprise_form.html', {
        'panel_section': 'enterprises',
        'panel_title': 'Editar empresa',
        'panel_note': f'Datos públicos de “{enterprise.studio_name}”.',
        'form': form,
        'enterprise': enterprise,
        'cancel_url': reverse('panel_enterprises'),
    })


@staff_required
@require_POST
def panel_enterprise_verify(request, enterprise_id):
    enterprise = get_object_or_404(Enterprise, pk=enterprise_id)
    enterprise.is_verified = not enterprise.is_verified
    enterprise.save(update_fields=['is_verified'])

    state = 'verificada' if enterprise.is_verified else 'pendiente de verificación'
    messages.success(
        request,
        f'“{enterprise.studio_name}” quedó {state}.',
    )
    return _safe_next(request, 'panel_enterprises')


@staff_required
def panel_enterprises_export(request):
    queryset, _ = _filtered_enterprises(request)
    rows = [
        [
            enterprise.studio_name,
            enterprise.user.username,
            enterprise.user.email,
            enterprise.website,
            'Sí' if enterprise.is_verified else 'No',
            enterprise.game_count,
            timezone.localtime(enterprise.created_at).strftime('%Y-%m-%d %H:%M'),
        ]
        for enterprise in queryset
    ]
    return _csv_response(
        'indievault-empresas.csv',
        ['Estudio', 'Usuario', 'Correo', 'Web', 'Verificada', 'Juegos', 'Creada'],
        rows,
    )


@staff_required
def panel_users(request):
    queryset, filters = _filtered_users(request)
    page_obj = _paginate(request, queryset)
    return render(request, 'panel/users.html', {
        **filters,
        'panel_section': 'users',
        'panel_title': 'Usuarios',
        'panel_note': 'Consulta las cuentas, activa o desactiva accesos y gestiona el personal.',
        'page_obj': page_obj,
        'total': page_obj.paginator.count,
    })


@staff_required
@require_POST
def panel_user_toggle_active(request, user_id):
    User = get_user_model()
    account = get_object_or_404(User, pk=user_id)

    if account == request.user:
        messages.error(request, 'No puedes desactivar tu propia cuenta.')
    elif account.is_superuser and not request.user.is_superuser:
        messages.error(request, 'Solo un superusuario puede modificar a otro superusuario.')
    else:
        account.is_active = not account.is_active
        account.save(update_fields=['is_active'])
        state = 'activada' if account.is_active else 'desactivada'
        messages.success(request, f'La cuenta de {account.username} quedó {state}.')

    return _safe_next(request, 'panel_users')


@staff_required
@require_POST
def panel_user_toggle_staff(request, user_id):
    if not request.user.is_superuser:
        raise PermissionDenied

    User = get_user_model()
    account = get_object_or_404(User, pk=user_id)

    if account == request.user:
        messages.error(request, 'No puedes cambiar tu propio rol.')
    elif account.is_superuser:
        messages.error(request, 'No puedes cambiar el rol de un superusuario.')
    else:
        account.is_staff = not account.is_staff
        account.save(update_fields=['is_staff'])
        state = 'personal' if account.is_staff else 'jugador'
        messages.success(request, f'{account.username} ahora es {state}.')

    return _safe_next(request, 'panel_users')


@staff_required
def panel_users_export(request):
    queryset, _ = _filtered_users(request)
    rows = [
        [
            account.username,
            account.email,
            account.first_name,
            account.last_name,
            timezone.localtime(account.date_joined).strftime('%Y-%m-%d %H:%M'),
            'Sí' if account.is_staff else 'No',
            'Sí' if account.is_active else 'No',
            account.entry_count,
        ]
        for account in queryset
    ]
    return _csv_response(
        'indievault-usuarios.csv',
        ['Usuario', 'Correo', 'Nombre', 'Apellidos', 'Registrado', 'Staff', 'Activo', 'Entradas'],
        rows,
    )


@staff_required
def panel_library(request):
    queryset, filters = _filtered_library(request)
    page_obj = _paginate(request, queryset)
    return render(request, 'panel/library.html', {
        **filters,
        'panel_section': 'library',
        'panel_title': 'Biblioteca',
        'panel_note': 'Revisa qué juegos guarda cada cuenta y corrige sus estados.',
        'page_obj': page_obj,
        'total': page_obj.paginator.count,
        'statuses': LibraryEntry.Status.choices,
    })


@staff_required
@require_POST
def panel_library_status(request, entry_id):
    entry = get_object_or_404(LibraryEntry, pk=entry_id)
    status = request.POST.get('status')

    if status in LibraryEntry.Status.values:
        entry.status = status
        entry.save(update_fields=['status'])
        messages.success(
            request,
            f'“{entry.game.title}” de {entry.user.username} quedó en {entry.status}.',
        )
    else:
        messages.error(request, 'El estado indicado no es válido.')

    return _safe_next(request, 'panel_library')


@staff_required
@require_POST
def panel_library_delete(request, entry_id):
    entry = get_object_or_404(LibraryEntry, pk=entry_id)
    title = entry.game.title
    username = entry.user.username
    entry.delete()
    messages.success(
        request,
        f'Se quitó “{title}” de la biblioteca de {username}.',
    )
    return _safe_next(request, 'panel_library')


@staff_required
def panel_library_export(request):
    queryset, _ = _filtered_library(request)
    rows = [
        [entry.user.username, entry.game.title, entry.status]
        for entry in queryset
    ]
    return _csv_response(
        'indievault-biblioteca.csv',
        ['Usuario', 'Juego', 'Estado'],
        rows,
    )
