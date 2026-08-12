import os
from django.core.management.base import BaseCommand
from apps.accounts.models import User


class Command(BaseCommand):
    help = "Cria um usuário administrador inicial se nenhum existir."

    def handle(self, *args, **options):
        email = os.environ.get("ADMIN_EMAIL", "admin@printfornece.com.br")
        password = os.environ.get("ADMIN_PASSWORD", "admin123456")
        name = os.environ.get("ADMIN_NAME", "Administrador")

        if not User.objects.filter(role=User.Role.ADMINISTRATOR).exists():
            User.objects.create_superuser(
                email=email,
                name=name,
                password=password,
                role=User.Role.ADMINISTRATOR,
            )
            self.stdout.write(self.style.SUCCESS(f"Superusuário '{email}' criado com sucesso."))
        else:
            self.stdout.write("Administrador já existe no banco de dados.")

        dev_email = os.environ.get("DEV_EMAIL", "dev@printfornece.com.br")
        dev_password = os.environ.get("DEV_PASSWORD", "dev123456")
        dev_name = os.environ.get("DEV_NAME", "Desenvolvedor")

        if not User.objects.filter(role=User.Role.DEV).exists():
            User.objects.create_superuser(
                email=dev_email,
                name=dev_name,
                password=dev_password,
                role=User.Role.DEV,
            )
            self.stdout.write(self.style.SUCCESS(f"Usuário DEV '{dev_email}' criado com sucesso."))
