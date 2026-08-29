from __future__ import annotations

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone


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
        DEV = "dev", "Desenvolvedor"

    class Sector(models.TextChoices):
        ADMIN = "administracao", "Administração / Geral"
        ATENDIMENTO = "atendimento", "Atendimento / Vendas (Rats, Meno)"
        PRODUCAO = "producao", "Pré-Impressão / Produção (Paula)"

    name = models.CharField("nome", max_length=120)
    email = models.EmailField("e-mail", max_length=190, unique=True)
    role = models.CharField("perfil", max_length=20, choices=Role.choices, default=Role.EMPLOYEE)
    sector = models.CharField("setor", max_length=20, choices=Sector.choices, default=Sector.ADMIN)
    is_active = models.BooleanField("ativo", default=True)
    is_staff = models.BooleanField("acesso ao admin", default=False)
    force_password_change = models.BooleanField("forçar troca de senha", default=False)
    last_activity = models.DateTimeField("última atividade", null=True, blank=True, db_index=True)
    current_login_at = models.DateTimeField("início da sessão atual", null=True, blank=True)
    last_seen_page = models.CharField("última página acessada", max_length=255, blank=True, default="")
    last_seen_device = models.CharField("dispositivo", max_length=100, blank=True, default="")
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
    def is_dev(self) -> bool:
        return self.role == self.Role.DEV or (self.is_superuser and self.role == self.Role.DEV)

    @property
    def is_administrator(self) -> bool:
        if self.role == self.Role.EMPLOYEE:
            return False
        return self.is_superuser or self.role in {self.Role.ADMINISTRATOR, self.Role.DEV}

    @property
    def is_prepress_production_only(self) -> bool:
        if self.is_administrator or self.is_dev:
            return False
        name_lower = (self.name or "").lower()
        return self.sector == self.Sector.PRODUCAO or "paula" in name_lower

    @property
    def is_attendance_sales_only(self) -> bool:
        if self.is_administrator or self.is_dev:
            return False
        name_lower = (self.name or "").lower()
        return self.sector == self.Sector.ATENDIMENTO or "rats" in name_lower or "meno" in name_lower

    @property
    def is_online(self) -> bool:
        if not self.last_activity or not self.current_login_at:
            return False
        return (timezone.now() - self.last_activity).total_seconds() <= 60

    @property
    def is_idle(self) -> bool:
        if not self.last_activity or not self.current_login_at:
            return False
        diff = (timezone.now() - self.last_activity).total_seconds()
        return 60 < diff <= 300

    @property
    def online_status(self) -> str:
        if self.is_online:
            return "online"
        if self.is_idle:
            return "idle"
        return "offline"

    @property
    def online_duration_seconds(self) -> int:
        if not self.is_online and not self.is_idle:
            return 0
        start = self.current_login_at or self.last_login or self.last_activity
        if not start:
            return 0
        diff = (timezone.now() - start).total_seconds()
        return max(0, int(diff))

    def save(self, *args, **kwargs):
        if self.role in {self.Role.ADMINISTRATOR, self.Role.DEV}:
            self.is_staff = True
        elif self.role == self.Role.EMPLOYEE:
            self.is_staff = False
            self.is_superuser = False
        super().save(*args, **kwargs)

