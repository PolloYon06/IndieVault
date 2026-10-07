from decimal import Decimal

from django.db.models import Q
from django.shortcuts import render

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

    return render(request, 'explorar.html', {
        'games': games,
        'genres': sorted(genre_set),
        'genre': genre,
        'q': query,
        'sort': sort,
        'price': price,
    })


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