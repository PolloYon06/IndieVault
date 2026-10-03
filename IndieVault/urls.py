from django.urls import path

from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('explorar/', views.explorar, name='explorar'),
    path('biblioteca/', views.biblioteca, name='biblioteca'),
]