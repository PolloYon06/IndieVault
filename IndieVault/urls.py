from django.urls import path

from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('explorar/', views.explorar, name='explorar'),
    path('biblioteca/', views.biblioteca, name='biblioteca'),
    path('biblioteca/agregar/<int:game_id>/', views.add_to_library, name='add_to_library'),
    path('biblioteca/quitar/<int:game_id>/', views.remove_from_library, name='remove_from_library'),
    path('juego/<slug:slug>/', views.game_detail, name='game_detail'),
    path('suscripcion/', views.suscripcion, name='suscripcion'),
]