from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import DatabaseError, models, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify


class Game(models.Model):
    # En IndieVault todo el catálogo es indie, así que repetirlo como género
    # en las etiquetas y en los filtros solo añade ruido.
    IGNORED_GENRES = {'indie'}

    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    steam_app_id = models.PositiveBigIntegerField(null=True, blank=True, unique=True)
    studio = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    year = models.PositiveIntegerField(default=0)
    genres = models.CharField(max_length=255, blank=True)
    price = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    symbol = models.CharField(max_length=8, blank=True, default='◈')
    tint = models.CharField(max_length=64, blank=True)
    publisher = models.ForeignKey(
        'Enterprise',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='games',
    )

    class Meta:
        ordering = ['title']

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title) or 'juego'
            slug = base
            suffix = 2
            while Game.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base}-{suffix}'
                suffix += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def genre_list(self):
        return [
            genre
            for genre in (g.strip() for g in self.genres.split(','))
            if genre and genre.casefold() not in self.IGNORED_GENRES
        ]

    def is_free(self):
        return self.price == 0


class Enterprise(models.Model):
    """Cuenta de empresa/estudio que publica juegos en IndieVault."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='enterprise',
    )
    studio_name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    website = models.URLField(blank=True)
    description = models.TextField(blank=True)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['studio_name']
        verbose_name = 'empresa'
        verbose_name_plural = 'empresas'

    def __str__(self):
        return self.studio_name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.studio_name) or 'estudio'
            slug = base
            suffix = 2
            while Enterprise.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base}-{suffix}'
                suffix += 1
            self.slug = slug
        super().save(*args, **kwargs)


class Profile(models.Model):
    """Personalización de una cuenta: avatar y presentación pública."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
    )
    avatar = models.ImageField(upload_to='avatars/', blank=True)
    # La foto se guarda también en la base para que viaje con los datos y se
    # vea igual en todos los equipos. `avatar` queda como ruta heredada.
    avatar_data = models.BinaryField(blank=True, null=True, editable=False)
    avatar_mime = models.CharField(max_length=40, blank=True)
    avatar_version = models.PositiveIntegerField(default=0)
    bio = models.CharField(max_length=200, blank=True)
    accent = models.CharField(
        max_length=7,
        blank=True,
        help_text='Color de acento en formato #rrggbb. Vacío usa el color de la marca.',
    )
    auto_accent = models.BooleanField(
        default=True,
        help_text='Tomar el color dominante de la foto de perfil.',
    )

    class Visibility(models.TextChoices):
        PUBLIC = 'public', 'Público'
        MEMBERS = 'members', 'Solo cuentas registradas'
        PRIVATE = 'private', 'Solo yo'

    visibility = models.CharField(
        max_length=10,
        choices=Visibility.choices,
        default=Visibility.MEMBERS,
        help_text='Quién puede ver tu perfil público y las secciones que compartes.',
    )
    show_library = models.BooleanField(
        default=True,
        help_text='Mostrar tu biblioteca en el perfil público.',
    )
    show_stats = models.BooleanField(
        default=True,
        help_text='Mostrar un resumen de tus estadísticas en el perfil público.',
    )
    show_discussions = models.BooleanField(
        default=True,
        help_text='Mostrar tu actividad reciente en la comunidad.',
    )

    class Meta:
        verbose_name = 'perfil'
        verbose_name_plural = 'perfiles'

    def __str__(self):
        return f'Perfil de {self.user.username}'

    def accent_source(self):
        """Origen que entiende `dominant_accent`: bytes o el archivo heredado."""
        return self.avatar_data or self.avatar or None

    def is_visible_to(self, viewer):
        """Indica si `viewer` puede ver el perfil público de esta cuenta."""
        if viewer.is_authenticated and (
            viewer == self.user or viewer.is_staff
        ):
            return True
        if self.visibility == self.Visibility.PUBLIC:
            return True
        if self.visibility == self.Visibility.MEMBERS and viewer.is_authenticated:
            return True
        return False


class LibraryEntry(models.Model):
    class Status(models.TextChoices):
        WANT = 'Pendiente', 'Pendiente'
        PLAYING = 'En curso', 'En curso'
        DONE = 'Terminado', 'Terminado'

    RATING_CHOICES = [(i, f'{i} ★') for i in range(1, 6)]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='library_entries',
    )
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='library_entries')
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.WANT)

    class Meta:
        ordering = ['status', 'game__title']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'game'],
                name='unique_library_entry_per_user',
            ),
        ]

    def __str__(self):
        return f'{self.game.title} · {self.status}'

    def _safe_review_record(self):
        if self.pk is None:
            return None
        try:
            with transaction.atomic():
                return self.review_record
        except (ObjectDoesNotExist, DatabaseError):
            return None

    @property
    def rating(self):
        record = self._safe_review_record()
        return record.rating if record is not None else None

    @property
    def review(self):
        record = self._safe_review_record()
        return record.review if record is not None else ''

    def rating_stars(self):
        val = self.rating
        if not val:
            return ''
        return '★' * val + '☆' * (5 - val)


class LibraryReview(models.Model):
    """Valoración y micro-reseña aislada en su propia tabla para no alterar LibraryEntry."""

    entry = models.OneToOneField(
        LibraryEntry,
        on_delete=models.CASCADE,
        related_name='review_record',
    )
    rating = models.PositiveSmallIntegerField(choices=LibraryEntry.RATING_CHOICES)
    review = models.CharField(max_length=280, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-pk']
        verbose_name = 'valoración de biblioteca'
        verbose_name_plural = 'valoraciones de biblioteca'

    def __str__(self):
        return f'{self.entry.user.username} · {self.entry.game.title} ({self.rating} ★)'

    @property
    def user(self):
        return self.entry.user

    def rating_stars(self):
        return '★' * self.rating + '☆' * (5 - self.rating)


class Discussion(models.Model):
    """Hilo del panel de comunidad, asociado a un juego o a la comunidad."""

    class Category(models.TextChoices):
        GENERAL = 'General', 'General'
        HELP = 'Ayuda', 'Ayuda'
        BUGS = 'Errores', 'Errores'
        GUIDES = 'Guías', 'Guías'
        TEAM = 'Busco gente', 'Busco gente'

    game = models.ForeignKey(
        Game,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='discussions',
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='discussions',
    )
    title = models.CharField(max_length=140)
    body = models.TextField()
    category = models.CharField(
        max_length=16,
        choices=Category.choices,
        default=Category.GENERAL,
    )
    is_pinned = models.BooleanField(default=False)
    is_locked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_activity_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-is_pinned', '-last_activity_at']
        verbose_name = 'tema de comunidad'
        verbose_name_plural = 'temas de comunidad'
        indexes = [
            models.Index(fields=['game', '-last_activity_at']),
        ]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('discussion_detail', args=[self.pk])


class DiscussionReply(models.Model):
    """Comentario dentro de un tema de comunidad."""

    discussion = models.ForeignKey(
        Discussion,
        on_delete=models.CASCADE,
        related_name='replies',
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='discussion_replies',
    )
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'comentario de comunidad'
        verbose_name_plural = 'comentarios de comunidad'

    def __str__(self):
        preview = self.body[:60].replace('\n', ' ')
        return f'{self.author.username}: {preview}'


class Notification(models.Model):
    """Notificación interna para actividad de comunidad y avisos de cuenta."""

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='triggered_notifications',
    )
    discussion = models.ForeignKey(
        Discussion,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='notifications',
    )
    reply = models.ForeignKey(
        DiscussionReply,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='notifications',
    )
    verb = models.CharField(max_length=200)
    target_url = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'notificación'
        verbose_name_plural = 'notificaciones'

    def __str__(self):
        return f'Para {self.recipient_id}: {self.verb}'


