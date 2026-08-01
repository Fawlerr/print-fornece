from __future__ import annotations

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email: str, name: str, password: str | None = None, **extra_fields):
        if not email:
            raise ValueError("O e-mail é obrigatório.")
        if not name:
            raise ValueError("O nome é obrigatório.")
        email = self.normalize_email(email)
        user = self.model(email=email, name=name, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, name: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("role", User.Role.ADMINISTRATOR)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        if extra_fields.get("is_staff") is not True or extra_fields.get("is_superuser") is not True:
            raise ValueError("O superusuário deve ter is_staff=True e is_superuser=True.")
        return self.create_user(email, name, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        ADMINISTRATOR = "administrador", "Administrador"
        EMPLOYEE = "funcionario", "Funcionário"

    name = models.CharField("nome", max_length=120)
    email = models.EmailField("e-mail", max_length=190, unique=True)
    role = models.CharField("perfil", max_length=20, choices=Role.choices, default=Role.EMPLOYEE)
    is_active = models.BooleanField("ativo", default=True)
    is_staff = models.BooleanField("acesso ao admin", default=False)
    force_password_change = models.BooleanField("forçar troca de senha", default=False)
    date_joined = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name"]

    class Meta:
        db_table = "pf_users"
        ordering = ["name"]
        indexes = [models.Index(fields=["role", "is_active"], name="pf_user_role_active")]

    def __str__(self) -> str:
        return self.name or self.email

    @property
    def is_administrator(self) -> bool:
        return self.is_superuser or self.role == self.Role.ADMINISTRATOR

    def save(self, *args, **kwargs):
        if self.role == self.Role.ADMINISTRATOR:
            self.is_staff = True
        super().save(*args, **kwargs)

