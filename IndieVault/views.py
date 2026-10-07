from django.shortcuts import render

GAMES = [
    {
        'title': 'Sendero de luciérnagas',
        'studio': 'Bruma Studio',
        'year': 2025,
        'genres': ['Aventura', 'Narrativa'],
        'price': 9.99,
        'symbol': '◈',
        'tint': 'rgba(214, 243, 106, 0.26)',
    },
    {
        'title': 'Cripta de vidrio',
        'studio': 'Nueve Lentes',
        'year': 2024,
        'genres': ['Puzle', 'Exploración'],
        'price': 0,
        'symbol': '◇',
        'tint': 'rgba(194, 168, 255, 0.26)',
    },
    {
        'title': 'Jardín de invierno',
        'studio': 'Marea Baja',
        'year': 2025,
        'genres': ['Exploración'],
        'price': 4.50,
        'symbol': '◉',
        'tint': 'rgba(126, 214, 223, 0.26)',
    },
    {
        'title': 'El último faro',
        'studio': 'Ala Rota',
        'year': 2023,
        'genres': ['Aventura', 'Narrativa'],
        'price': 19.99,
        'symbol': '◐',
        'tint': 'rgba(255, 176, 138, 0.24)',
    },
    {
        'title': 'Taller de engranajes',
        'studio': 'Cuarto Piso',
        'year': 2024,
        'genres': ['Estrategia', 'Puzle'],
        'price': 12.99,
        'symbol': '⬡',
        'tint': 'rgba(196, 168, 255, 0.24)',
    },
    {
        'title': 'Aurora fija',
        'studio': 'Senda Norte',
        'year': 2025,
        'genres': ['Exploración', 'Aventura'],
        'price': 0,
        'symbol': '✳',
        'tint': 'rgba(214, 243, 106, 0.2)',
    },
]

GENRES = ['Aventura', 'Puzle', 'Narrativa', 'Exploración', 'Estrategia']


def index(request):
    return render(request, 'index.html')


def explorar(request):
    games = GAMES
    genre = request.GET.get('genre', '')
    query = request.GET.get('q', '').strip()
    sort = request.GET.get('sort', '')
    price = request.GET.get('price', '')

    if genre:
        games = [g for g in games if genre in g['genres']]
    if query:
        needle = query.lower()
        games = [
            g for g in games
            if needle in g['title'].lower() or needle in g['studio'].lower()
        ]
    if price == 'free':
        games = [g for g in games if g['price'] == 0]
    elif price:
        cap = float(price)
        games = [g for g in games if 0 < g['price'] < cap]

    if sort == 'az':
        games = sorted(games, key=lambda g: g['title'].lower())
    elif sort == 'za':
        games = sorted(games, key=lambda g: g['title'].lower(), reverse=True)
    elif sort == 'price_asc':
        games = sorted(games, key=lambda g: g['price'])
    elif sort == 'price_desc':
        games = sorted(games, key=lambda g: g['price'], reverse=True)
    elif sort == 'newest':
        games = sorted(games, key=lambda g: g['year'], reverse=True)

    return render(request, 'explorar.html', {
        'games': games,
        'genres': GENRES,
        'genre': genre,
        'q': query,
        'sort': sort,
        'price': price,
    })


def biblioteca(request):
    return render(request, 'biblioteca.html')


def suscripcion(request):
    return render(request, 'suscripcion.html')