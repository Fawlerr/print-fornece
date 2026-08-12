from __future__ import annotations

from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import PasswordChangeForm, PasswordResetForm

from .models import User


class LoginForm(forms.Form):
    email = forms.CharField(label="E-mail ou Usuário", widget=forms.TextInput(attrs={"autocomplete": "username", "autofocus": True}))
    password = forms.CharField(label="Senha", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user_cache = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        email_or_user = cleaned_data.get("email", "").strip()
        password = cleaned_data.get("password")
        if email_or_user and password:
            lookup_email = email_or_user
            if "@" not in email_or_user:
                matched = User.objects.filter(email__iexact=f"{email_or_user}@printfornece.com.br").first() or \
                          User.objects.filter(email__istartswith=email_or_user).first() or \
                          User.objects.filter(name__iexact=email_or_user).first()
                if matched:
                    lookup_email = matched.email

            self.user_cache = authenticate(self.request, username=lookup_email, password=password)
            if self.user_cache is None:
                raise forms.ValidationError("E-mail ou senha inválidos.")
            if not self.user_cache.is_active:
                raise forms.ValidationError("Esta conta está desativada.")
        return cleaned_data

    def get_user(self):
        return self.user_cache


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["name"]
        labels = {"name": "Nome"}


class UserCreateForm(forms.ModelForm):
    password1 = forms.CharField(label="Senha inicial", min_length=8, widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirme a senha", min_length=8, widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ["name", "email", "role"]
        labels = {"name": "Nome", "email": "E-mail", "role": "Perfil"}

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("password1") != cleaned.get("password2"):
            self.add_error("password2", "As senhas não conferem.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        user.force_password_change = True
        if commit:
            user.save()
        return user


class UserUpdateForm(forms.ModelForm):
    password = forms.CharField(label="Nova senha", min_length=8, required=False, widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ["name", "email", "role", "is_active"]
        labels = {"name": "Nome", "email": "E-mail", "role": "Perfil", "is_active": "Ativo"}

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("password"):
            user.set_password(self.cleaned_data["password"])
            user.force_password_change = True
        if commit:
            user.save()
        return user


class PrintFornecePasswordChangeForm(PasswordChangeForm):
    old_password = forms.CharField(label="Senha atual", strip=False, widget=forms.PasswordInput)
    new_password1 = forms.CharField(label="Nova senha", strip=False, min_length=8, widget=forms.PasswordInput)
    new_password2 = forms.CharField(label="Confirme a nova senha", strip=False, min_length=8, widget=forms.PasswordInput)


class PrintFornecePasswordResetForm(PasswordResetForm):
    email = forms.EmailField(label="E-mail", max_length=254)

