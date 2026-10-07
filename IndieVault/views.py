from django.shortcuts import render


def index(request):
    return render(request, 'index.html')


def explorar(request):
    return render(request, 'explorar.html')


def biblioteca(request):
    return render(request, 'biblioteca.html')


def suscripcion(request):
    return render(request, 'suscripcion.html')