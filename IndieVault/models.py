from django.conf import settings
from django.db import models
from django.utils.text import slugify


class Game(models.Model):
    title = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
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
        return [g.strip() for g in self.genres.split(',') if g.strip()]

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


class LibraryEntry(models.Model):
    class Status(models.TextChoices):
        WANT = 'Pendiente', 'Pendiente'
        PLAYING = 'En curso', 'En curso'
        DONE = 'Terminado', 'Terminado'

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
