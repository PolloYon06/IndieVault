from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path


def admin_login(request, extra_context=None):
    """El panel de administración no tiene login propio.

    Toda la autenticación pasa por /login/, donde las cuentas is_staff
    son detectadas y redirigidas al panel.
    """
    return redirect('login')


admin.site.login = admin_login
admin.site.site_header = 'IndieVault · Administración'
admin.site.site_title = 'IndieVault Admin'
admin.site.index_title = 'Gestión de la plataforma'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('IndieVault.urls')),
]

handler404 = 'IndieVault.views.custom_404'
