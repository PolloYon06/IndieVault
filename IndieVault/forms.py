from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import Enterprise, Game


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
