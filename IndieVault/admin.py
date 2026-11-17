from django.contrib import admin

from .models import (
    Discussion,
    DiscussionReply,
    Enterprise,
    Game,
    LibraryEntry,
    Profile,
)


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'steam_app_id', 'studio', 'publisher', 'year', 'price', 'genres',
    ]
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


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'bio']
    search_fields = [
        'user__username', 'user__email', 'user__first_name', 'user__last_name',
    ]


@admin.register(Discussion)
class DiscussionAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'game', 'author', 'category', 'is_pinned', 'is_locked',
        'last_activity_at',
    ]
    list_filter = ['category', 'is_pinned', 'is_locked']
    search_fields = ['title', 'body', 'author__username', 'game__title']
    autocomplete_fields = ['game', 'author']
    list_per_page = 25


@admin.register(DiscussionReply)
class DiscussionReplyAdmin(admin.ModelAdmin):
    list_display = ['discussion', 'author', 'created_at']
    search_fields = ['body', 'author__username', 'discussion__title']
    autocomplete_fields = ['discussion', 'author']
    list_per_page = 25

