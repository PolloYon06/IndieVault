from django.contrib import admin

from .models import Enterprise, Game, LibraryEntry


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ['title', 'studio', 'publisher', 'year', 'price', 'genres']
    list_filter = ['genres', 'publisher']
    search_fields = ['title', 'studio']
    prepopulated_fields = {'slug': ('title',)}
    list_editable = ['year', 'price']
    list_per_page = 25
    autocomplete_fields = ['publisher']


@admin.action(description='Marcar empresas seleccionadas como verificadas')
def mark_verified(modeladmin, request, queryset):
    queryset.update(is_verified=True)


@admin.action(description='Quitar verificación a las empresas seleccionadas')
def mark_unverified(modeladmin, request, queryset):
    queryset.update(is_verified=False)


@admin.register(Enterprise)
class EnterpriseAdmin(admin.ModelAdmin):
    list_display = ['studio_name', 'user', 'website', 'is_verified', 'created_at']
    list_filter = ['is_verified']
    search_fields = ['studio_name', 'user__username', 'user__email']
    prepopulated_fields = {'slug': ('studio_name',)}
    list_editable = ['is_verified']
    list_per_page = 25
    actions = [mark_verified, mark_unverified]


@admin.register(LibraryEntry)
class LibraryEntryAdmin(admin.ModelAdmin):
    list_display = ['user', 'game', 'status']
    list_filter = ['status']
    search_fields = ['user__username', 'game__title']
    list_editable = ['status']
    list_per_page = 25
    autocomplete_fields = ['user', 'game']
