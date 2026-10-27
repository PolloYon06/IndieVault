from django.urls import path

from . import panel_views, views

urlpatterns = [
    path('', views.index, name='index'),
    path('explorar/', views.explorar, name='explorar'),
    path('biblioteca/', views.biblioteca, name='biblioteca'),
    path('estadisticas/', views.estadisticas, name='estadisticas'),
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

    # Panel de administración propio, con la estética del sitio.
    path('panel/', panel_views.panel_dashboard, name='panel_dashboard'),
    path('panel/estadisticas/', panel_views.panel_stats, name='panel_stats'),
    path('panel/juegos/', panel_views.panel_games, name='panel_games'),
    path('panel/juegos/nuevo/', panel_views.panel_game_create, name='panel_game_create'),
    path('panel/juegos/<int:game_id>/editar/', panel_views.panel_game_edit, name='panel_game_edit'),
    path('panel/juegos/<int:game_id>/eliminar/', panel_views.panel_game_delete, name='panel_game_delete'),
    path('panel/juegos/exportar/', panel_views.panel_games_export, name='panel_games_export'),
    path('panel/empresas/', panel_views.panel_enterprises, name='panel_enterprises'),
    path('panel/empresas/<int:enterprise_id>/editar/', panel_views.panel_enterprise_edit, name='panel_enterprise_edit'),
    path('panel/empresas/<int:enterprise_id>/verificar/', panel_views.panel_enterprise_verify, name='panel_enterprise_verify'),
    path('panel/empresas/exportar/', panel_views.panel_enterprises_export, name='panel_enterprises_export'),
    path('panel/usuarios/', panel_views.panel_users, name='panel_users'),
    path('panel/usuarios/<int:user_id>/activo/', panel_views.panel_user_toggle_active, name='panel_user_toggle_active'),
    path('panel/usuarios/<int:user_id>/staff/', panel_views.panel_user_toggle_staff, name='panel_user_toggle_staff'),
    path('panel/usuarios/exportar/', panel_views.panel_users_export, name='panel_users_export'),
    path('panel/biblioteca/', panel_views.panel_library, name='panel_library'),
    path('panel/biblioteca/<int:entry_id>/estado/', panel_views.panel_library_status, name='panel_library_status'),
    path('panel/biblioteca/<int:entry_id>/eliminar/', panel_views.panel_library_delete, name='panel_library_delete'),
    path('panel/biblioteca/exportar/', panel_views.panel_library_export, name='panel_library_export'),
]