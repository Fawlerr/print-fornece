from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.inventory.models import SupplyItem, SupplyMovement


class InventoryTestCase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin_inv@printfornece.com.br",
            name="Admin Insumos",
            role=User.Role.ADMINISTRATOR,
            password="adminpassword123",
        )
        self.employee = User.objects.create_user(
            email="employee_inv@printfornece.com.br",
            name="Funcionario Insumos",
            role=User.Role.EMPLOYEE,
            password="employeepassword123",
        )

    def test_seed_supplies_command(self):
        call_command("seed_supplies")
        self.assertTrue(SupplyItem.objects.filter(category=SupplyItem.Category.DTF_TEXTIL).exists())
        self.assertTrue(SupplyItem.objects.filter(category=SupplyItem.Category.DTF_UV).exists())
        self.assertTrue(SupplyItem.objects.filter(category=SupplyItem.Category.SHIRTS).exists())
        self.assertTrue(SupplyItem.objects.filter(name="Tinta DTF Têxtil - Branco").exists())
        self.assertTrue(SupplyItem.objects.filter(name="Verniz DTF UV").exists())
        self.assertTrue(SupplyItem.objects.filter(name="Camiseta Dry Fit - Tam. M").exists())

    def test_create_supply_item_and_movement(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("inventory:create"), {
            "name": "Tinta DTF Especial Dourada",
            "category": SupplyItem.Category.DTF_TEXTIL,
            "unit": SupplyItem.Unit.LITER,
            "quantity": "5,00",
            "minimum_quantity": "2,00",
            "notes": "Lote novo",
        })
        self.assertRedirects(response, reverse("inventory:list"))
        
        item = SupplyItem.objects.get(name="Tinta DTF Especial Dourada")
        self.assertEqual(item.quantity, Decimal("5.00"))
        self.assertEqual(item.minimum_quantity, Decimal("2.00"))
        self.assertFalse(item.is_low_stock)

        # Movement created on initial quantity
        self.assertTrue(SupplyMovement.objects.filter(item=item, movement_type=SupplyMovement.MovementType.ENTRY).exists())

    def test_quick_movement_entry_and_output(self):
        self.client.force_login(self.employee)
        item = SupplyItem.objects.create(
            name="Pó TPU Teste",
            category=SupplyItem.Category.DTF_TEXTIL,
            unit=SupplyItem.Unit.KG,
            quantity=Decimal("10.00"),
            minimum_quantity=Decimal("4.00"),
        )

        # Registrar saída de 3 kg
        response = self.client.post(reverse("inventory:quick_movement", args=[item.pk]), {
            "movement_type": "saida",
            "quantity": "3,00",
            "description": "Uso em produção",
        })
        self.assertRedirects(response, reverse("inventory:list"))
        item.refresh_from_db()
        self.assertEqual(item.quantity, Decimal("7.00"))

        # Registrar saída de 4 kg (saldo vai para 3 kg <= mínimo 4 kg -> alerta)
        self.client.post(reverse("inventory:quick_movement", args=[item.pk]), {
            "movement_type": "saida",
            "quantity": "4,00",
            "description": "Uso em produção turno tarde",
        })
        item.refresh_from_db()
        self.assertEqual(item.quantity, Decimal("3.00"))
        self.assertTrue(item.is_low_stock)

        # Registrar entrada de compra de 10 kg
        self.client.post(reverse("inventory:quick_movement", args=[item.pk]), {
            "movement_type": "entrada",
            "quantity": "10,00",
            "description": "Chegada de pedido",
        })
        item.refresh_from_db()
        self.assertEqual(item.quantity, Decimal("13.00"))
        self.assertFalse(item.is_low_stock)
