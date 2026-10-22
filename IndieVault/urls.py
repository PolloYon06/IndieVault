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
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('empresa/login/', views.enterprise_login_view, name='enterprise_login'),
    path('empresa/registro/', views.enterprise_register_view, name='enterprise_register'),
    path('empresa/', views.enterprise_dashboard, name='enterprise_dashboard'),
    path('empresa/publicar/', views.enterprise_publish, name='enterprise_publish'),
]