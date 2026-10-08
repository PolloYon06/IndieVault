from django.db import migrations, models
from django.utils.text import slugify


def backfill_slugs(apps, schema_editor):
    Game = apps.get_model('IndieVault', 'Game')
    for game in Game.objects.all():
        base = slugify(game.title) or 'juego'
        game.slug = base
        game.save(update_fields=['slug'])


class Migration(migrations.Migration):

    dependencies = [
        ('IndieVault', '0002_seed_initial_games'),
    ]

    operations = [
        migrations.AddField(
            model_name='game',
            name='slug',
            field=models.SlugField(max_length=140, default='', blank=True),
        ),
        migrations.RunPython(backfill_slugs, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='game',
            name='slug',
            field=models.SlugField(max_length=140, unique=True, blank=True),
        ),
    ]