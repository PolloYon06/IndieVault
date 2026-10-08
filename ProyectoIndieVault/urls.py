from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('IndieVault.urls')),
]

handler404 = 'IndieVault.views.custom_404'