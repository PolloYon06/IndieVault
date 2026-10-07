from django.contrib import admin

from .models import Game, LibraryEntry


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ['title', 'studio', 'year', 'price', 'genres']
    list_filter = ['genres']
    search_fields = ['title', 'studio']


@admin.register(LibraryEntry)
class LibraryEntryAdmin(admin.ModelAdmin):
    list_display = ['game', 'status']
    list_filter = ['status']