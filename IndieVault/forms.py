from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .appearance import DEFAULT_ACCENT, HEX_RE, dominant_accent, prepare_avatar
from .models import Enterprise, Game, Profile


class EnterpriseSignupForm(forms.Form):
    """Registro de una cuenta de empresa (estudio que publica juegos)."""

    studio_name = forms.CharField(
        max_length=120,
        label='Nombre del estudio',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej. Lumen Studio'}),
    )
    username = forms.CharField(
        max_length=150,
        label='Usuario',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'autocomplete': 'username',
            'autocapitalize': 'none',
        }),
    )
    email = forms.EmailField(
        label='Correo',
        widget=forms.EmailInput(attrs={'class': 'form-control', 'autocomplete': 'email'}),
    )
    website = forms.URLField(
        required=False,
        label='Sitio web',
        widget=forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://'}),
    )
    description = forms.CharField(
        required=False,
        label='Descripción',
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
    )
    password1 = forms.CharField(
        label='Contraseña',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
    )
    password2 = forms.CharField(
        label='Repetir contraseña',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
    )

    def clean_username(self):
        username = self.cleaned_data['username']
        if get_user_model().objects.filter(username__iexact=username).exists():
            raise ValidationError('Ese usuario ya está en uso.')
        return username

    def clean_email(self):
        email = self.cleaned_data['email']
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise ValidationError('Ese correo ya está registrado.')
        return email

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get('password1')
        password2 = cleaned.get('password2')

        if password1 and password2 and password1 != password2:
            self.add_error('password2', 'Las contraseñas no coinciden.')

        if password1:
            try:
                validate_password(password1)
            except ValidationError as error:
                self.add_error('password1', error)

        return cleaned

    def save(self):
        data = self.cleaned_data
        user = get_user_model().objects.create_user(
            username=data['username'],
            email=data['email'],
            password=data['password1'],
        )
        return Enterprise.objects.create(
            user=user,
            studio_name=data['studio_name'],
            website=data.get('website') or '',
            description=data.get('description') or '',
        )


class GameForm(forms.ModelForm):
    class Meta:
        model = Game
        fields = ['title', 'description', 'genres', 'year', 'price', 'symbol', 'tint']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'genres': forms.TextInput(attrs={'placeholder': 'Acción, Aventura'}),
            'symbol': forms.TextInput(attrs={'maxlength': 8}),
            'tint': forms.TextInput(attrs={'placeholder': 'linear-gradient(135deg, #2b1055, #7597de)'}),
        }
        help_texts = {
            'genres': 'Separa los géneros con comas.',
            'symbol': 'Un emoji o símbolo para la portada.',
            'tint': 'Color o degradado CSS para la portada (opcional).',
        }


class AdminGameForm(GameForm):
    """Ficha completa para que el personal gestione cualquier juego."""

    studio = forms.CharField(max_length=120, label='Estudio')
    publisher = forms.ModelChoiceField(
        queryset=Enterprise.objects.all(),
        required=False,
        label='Empresa publicadora',
    )

    class Meta(GameForm.Meta):
        fields = [
            'title', 'studio', 'publisher', 'description',
            'genres', 'year', 'price', 'symbol', 'tint',
        ]


class AdminEnterpriseForm(forms.ModelForm):
    class Meta:
        model = Enterprise
        fields = ['studio_name', 'website', 'description', 'is_verified']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
        }
        labels = {
            'is_verified': 'Empresa verificada',
        }


class ProfileForm(forms.ModelForm):
    """Datos de la cuenta y personalización del perfil."""

    first_name = forms.CharField(
        max_length=150,
        required=False,
        label='Nombre',
        widget=forms.TextInput(attrs={'autocomplete': 'given-name'}),
    )
    last_name = forms.CharField(
        max_length=150,
        required=False,
        label='Apellidos',
        widget=forms.TextInput(attrs={'autocomplete': 'family-name'}),
    )
    email = forms.EmailField(
        required=False,
        label='Correo',
        widget=forms.EmailInput(attrs={'autocomplete': 'email'}),
    )
    avatar = forms.ImageField(
        required=False,
        label='Foto de perfil',
        help_text='JPG, PNG o WebP. Máximo 4 MB. Se guarda en tu cuenta.',
        widget=forms.ClearableFileInput(attrs={'accept': 'image/*'}),
    )

    class Meta:
        model = Profile
        fields = ['bio']
        widgets = {
            'bio': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'Cuéntanos qué tipo de juegos te gustan…',
            }),
        }
        labels = {
            'bio': 'Sobre mí',
        }
        help_texts = {
            'bio': 'Una frase corta que se mostrará en tu perfil.',
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        self._avatar_payload = None
        super().__init__(*args, **kwargs)

        if user is not None:
            self.fields['first_name'].initial = user.first_name
            self.fields['last_name'].initial = user.last_name
            self.fields['email'].initial = user.email

    def clean_avatar(self):
        avatar = self.cleaned_data.get('avatar')
        self._avatar_payload = None
        if not avatar:
            return avatar

        try:
            self._avatar_payload = prepare_avatar(avatar)
        except ValueError as error:
            raise ValidationError(str(error))
        except Exception:
            raise ValidationError('No pudimos leer la imagen. Prueba con un JPG o PNG.')
        return avatar

    def save(self, commit=True):
        profile = super().save(commit=False)

        if self._avatar_payload:
            profile.avatar_data, profile.avatar_mime = self._avatar_payload
            profile.avatar_version = (profile.avatar_version or 0) + 1
            # La ruta en media/ deja de usarse: la foto ya está en la base.
            profile.avatar = ''

        if self.user is not None:
            self.user.first_name = self.cleaned_data.get('first_name', '').strip()
            self.user.last_name = self.cleaned_data.get('last_name', '').strip()
            self.user.email = self.cleaned_data.get('email', '').strip()
            if commit:
                self.user.save(update_fields=['first_name', 'last_name', 'email'])

        if commit:
            profile.save()
            if profile.auto_accent:
                source = profile.accent_source()
                profile.accent = dominant_accent(source) if source else ''
                profile.save(update_fields=['accent'])

        return profile


class AppearanceForm(forms.ModelForm):
    """Paleta de color personal: automática desde el avatar o elegida a mano."""

    class Meta:
        model = Profile
        fields = ['accent', 'auto_accent']
        widgets = {
            'accent': forms.TextInput(attrs={'type': 'color'}),
        }
        labels = {
            'accent': 'Color de acento',
            'auto_accent': 'Usar el color dominante de mi foto de perfil',
        }
        help_texts = {
            'accent': 'Elige un color o escribe su código hexadecimal.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['accent'].required = False
        if not self.instance.accent:
            self.initial['accent'] = DEFAULT_ACCENT

    def clean_accent(self):
        accent = (self.cleaned_data.get('accent') or '').strip()
        if accent and not HEX_RE.match(accent):
            raise ValidationError('Usa un color en formato #rrggbb.')
        return accent.lower()

    def save(self, commit=True):
        profile = super().save(commit=False)
        if profile.auto_accent:
            source = profile.accent_source()
            profile.accent = dominant_accent(source) if source else ''
        if commit:
            profile.save()
        return profile
