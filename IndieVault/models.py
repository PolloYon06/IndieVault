from django.db import models


class Game(models.Model):
    title = models.CharField(max_length=120)
    studio = models.CharField(max_length=120)
    year = models.PositiveIntegerField(default=0)
    genres = models.CharField(max_length=255, blank=True)
    price = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    symbol = models.CharField(max_length=8, blank=True, default='◈')
    tint = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ['title']

    def __str__(self):
        return self.title

    def genre_list(self):
        return [g.strip() for g in self.genres.split(',') if g.strip()]

    def is_free(self):
        return self.price == 0


class LibraryEntry(models.Model):
    class Status(models.TextChoices):
        WANT = 'Pendiente', 'Pendiente'
        PLAYING = 'En curso', 'En curso'
        DONE = 'Terminado', 'Terminado'

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='library_entries')
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.WANT)

    class Meta:
        ordering = ['status', 'game__title']

    def __str__(self):
        return f'{self.game.title} · {self.status}'