from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('IndieVault', '0005_libraryentry_user'),
    ]

    operations = [
        migrations.AlterField(
            model_name='game',
            name='title',
            field=models.CharField(max_length=255),
        ),
        migrations.AddField(
            model_name='game',
            name='steam_app_id',
            field=models.PositiveBigIntegerField(blank=True, null=True, unique=True),
        ),
    ]
