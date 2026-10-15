# REFERENCIA — NO SE USA EN TIEMPO DE EJECUCIÓN.
# Salida de `python manage.py inspectdb` sobre la base de datos MariaDB
# "indievault" (esquema de bd.txt + tablas propias de Django). Se guarda
# únicamente como referencia del modelo físico. La aplicación usa
# IndieVault/models.py.
#
# This is an auto-generated Django model module.
# You'll have to do the following manually to clean this up:
#   * Rearrange models' order
#   * Make sure each model has one field with primary_key=True
#   * Make sure each ForeignKey and OneToOneField has `on_delete` set to the desired behavior
#   * Remove `managed = False` lines if you wish to allow Django to create, modify, and delete the table
# Feel free to rename the models, but don't rename db_table values or field names.
from django.db import models


class Compra(models.Model):
    id_compra = models.AutoField(primary_key=True)
    fecha_compra = models.DateField()
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    usuario_id_usuario = models.ForeignKey('Usuario', models.DO_NOTHING, db_column='Usuario_id_usuario')  # Field name made lowercase.
    juego_id_juego = models.ForeignKey('Juego', models.DO_NOTHING, db_column='JUEGO_id_juego')  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'COMPRA'


class Desarrollador(models.Model):
    id_desarrollador = models.AutoField(primary_key=True)
    nombre_estudio = models.CharField(max_length=100)
    sitio_web = models.CharField(max_length=150, blank=True, null=True)
    usuario_id_usuario = models.ForeignKey('Usuario', models.DO_NOTHING, db_column='Usuario_id_usuario')  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'DESARROLLADOR'


class Genero(models.Model):
    id_genero = models.AutoField(primary_key=True)
    nombre_genero = models.CharField(max_length=50)

    class Meta:
        managed = False
        db_table = 'GENERO'


class IndievaultGame(models.Model):
    id = models.BigAutoField(primary_key=True)
    title = models.CharField(max_length=120)
    studio = models.CharField(max_length=120)
    year = models.PositiveIntegerField()
    genres = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=5, decimal_places=2)
    symbol = models.CharField(max_length=8)
    tint = models.CharField(max_length=64)
    slug = models.CharField(unique=True, max_length=140)

    class Meta:
        managed = False
        db_table = 'IndieVault_game'


class IndievaultLibraryentry(models.Model):
    id = models.BigAutoField(primary_key=True)
    status = models.CharField(max_length=12)
    game = models.ForeignKey(IndievaultGame, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'IndieVault_libraryentry'


class Juego(models.Model):
    id_juego = models.AutoField(primary_key=True)
    titulo = models.CharField(max_length=100)
    descripcion = models.CharField(max_length=500)
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    fecha_lanzamiento = models.DateField(blank=True, null=True)
    desarrollador_id_desarrollador = models.ForeignKey(Desarrollador, models.DO_NOTHING, db_column='DESARROLLADOR_id_desarrollador')  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'JUEGO'


class JuegoGenero(models.Model):
    pk = models.CompositePrimaryKey('id_juego_genero', 'JUEGO_id_juego')
    id_juego_genero = models.IntegerField()
    juego_id_juego = models.ForeignKey(Juego, models.DO_NOTHING, db_column='JUEGO_id_juego')  # Field name made lowercase.
    genero_id_genero = models.ForeignKey(Genero, models.DO_NOTHING, db_column='GENERO_id_genero')  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'JUEGO_GENERO'


class Usuario(models.Model):
    id_usuario = models.AutoField(primary_key=True)
    username = models.CharField(max_length=50)
    email = models.CharField(max_length=100)
    password = models.CharField(max_length=225)
    fecha_registro = models.DateField()

    class Meta:
        managed = False
        db_table = 'Usuario'


class AuthGroup(models.Model):
    name = models.CharField(unique=True, max_length=150)

    class Meta:
        managed = False
        db_table = 'auth_group'


class AuthGroupPermissions(models.Model):
    id = models.BigAutoField(primary_key=True)
    group = models.ForeignKey(AuthGroup, models.DO_NOTHING)
    permission = models.ForeignKey('AuthPermission', models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'auth_group_permissions'
        unique_together = (('group', 'permission'),)


class AuthPermission(models.Model):
    name = models.CharField(max_length=255)
    content_type = models.ForeignKey('DjangoContentType', models.DO_NOTHING)
    codename = models.CharField(max_length=100)

    class Meta:
        managed = False
        db_table = 'auth_permission'
        unique_together = (('content_type', 'codename'),)


class AuthUser(models.Model):
    password = models.CharField(max_length=128)
    last_login = models.DateTimeField(blank=True, null=True)
    is_superuser = models.IntegerField()
    username = models.CharField(unique=True, max_length=150)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    email = models.CharField(max_length=254)
    is_staff = models.IntegerField()
    is_active = models.IntegerField()
    date_joined = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'auth_user'


class AuthUserGroups(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(AuthUser, models.DO_NOTHING)
    group = models.ForeignKey(AuthGroup, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'auth_user_groups'
        unique_together = (('user', 'group'),)


class AuthUserUserPermissions(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(AuthUser, models.DO_NOTHING)
    permission = models.ForeignKey(AuthPermission, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'auth_user_user_permissions'
        unique_together = (('user', 'permission'),)


class DjangoAdminLog(models.Model):
    action_time = models.DateTimeField()
    object_id = models.TextField(blank=True, null=True)
    object_repr = models.CharField(max_length=200)
    action_flag = models.PositiveSmallIntegerField()
    change_message = models.TextField()
    content_type = models.ForeignKey('DjangoContentType', models.DO_NOTHING, blank=True, null=True)
    user = models.ForeignKey(AuthUser, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'django_admin_log'


class DjangoContentType(models.Model):
    app_label = models.CharField(max_length=100)
    model = models.CharField(max_length=100)

    class Meta:
        managed = False
        db_table = 'django_content_type'
        unique_together = (('app_label', 'model'),)


class DjangoMigrations(models.Model):
    id = models.BigAutoField(primary_key=True)
    app = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    applied = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'django_migrations'


class DjangoSession(models.Model):
    session_key = models.CharField(primary_key=True, max_length=40)
    session_data = models.TextField()
    expire_date = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'django_session'
