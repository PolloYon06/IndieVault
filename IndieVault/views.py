from decimal import Decimal

from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from .models import Game, LibraryEntry


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

    genre_set = {g for game in Game.objects.all() for g in game.genre_list()}

    in_library = set(LibraryEntry.objects.values_list('game_id', flat=True))

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
    in_library = LibraryEntry.objects.filter(game=game).first()
    return render(request, 'game_detail.html', {
        'game': game,
        'related': related,
        'in_library': in_library,
    })


def add_to_library(request, game_id):
    game = get_object_or_404(Game, pk=game_id)
    LibraryEntry.objects.get_or_create(game=game, defaults={'status': LibraryEntry.Status.WANT})
    return HttpResponseRedirect(request.META.get('HTTP_REFERER') or reverse('explorar'))


def remove_from_library(request, game_id):
    game = get_object_or_404(Game, pk=game_id)
    LibraryEntry.objects.filter(game=game).delete()
    return HttpResponseRedirect(request.META.get('HTTP_REFERER') or reverse('explorar'))


def custom_404(request, exception=None):
    return render(request, '404.html', status=404)


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
            'count': LibraryEntry.objects.filter(status=status).count(),
            'entries': LibraryEntry.objects.filter(status=status).select_related('game'),
        }
        for title, status in groups
    ]
    return render(request, 'biblioteca.html', {'groups': group_data})


def suscripcion(request):
    return render(request, 'suscripcion.html')