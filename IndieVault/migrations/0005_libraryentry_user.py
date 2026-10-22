from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def assign_existing_entries(apps, schema_editor):
    """Las entradas antiguas eran globales; se asignan a una cuenta existente.

    Si la base de datos aún no tiene usuarios (instalación nueva), no hay a
    quién asignarlas y se eliminan.
    """
    LibraryEntry = apps.get_model('IndieVault', 'LibraryEntry')
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))

    if not LibraryEntry.objects.filter(user__isnull=True).exists():
        return

    owner = (
        User.objects.filter(is_staff=False).order_by('pk').first()
        or User.objects.order_by('pk').first()
    )

    if owner is None:
        LibraryEntry.objects.filter(user__isnull=True).delete()
    else:
        LibraryEntry.objects.filter(user__isnull=True).update(user=owner)


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('IndieVault', '0004_game_description_enterprise_game_publisher'),
    ]

    operations = [
        migrations.AddField(
            model_name='libraryentry',
            name='user',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='library_entries',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(assign_existing_entries, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='libraryentry',
            name='user',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='library_entries',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddConstraint(
            model_name='libraryentry',
            constraint=models.UniqueConstraint(
                fields=('user', 'game'),
                name='unique_library_entry_per_user',
            ),
        ),
    ]
