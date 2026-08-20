from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.inventory.models import SupplyItem


class Command(BaseCommand):
    help = "Cria a grade inicial de insumos de estoque (DTF Têxtil, DTF UV e Camisetas) se ainda não existirem."

    def handle(self, *args, **options):
        initial_supplies = [
            # DTF Têxtil - Tintas
            {"category": SupplyItem.Category.DTF_TEXTIL, "name": "Tinta DTF Têxtil - Preto", "unit": SupplyItem.Unit.LITER, "min_qty": Decimal("2.00")},
            {"category": SupplyItem.Category.DTF_TEXTIL, "name": "Tinta DTF Têxtil - Branco", "unit": SupplyItem.Unit.LITER, "min_qty": Decimal("4.00")},
            {"category": SupplyItem.Category.DTF_TEXTIL, "name": "Tinta DTF Têxtil - Azul (Ciano)", "unit": SupplyItem.Unit.LITER, "min_qty": Decimal("2.00")},
            {"category": SupplyItem.Category.DTF_TEXTIL, "name": "Tinta DTF Têxtil - Amarelo", "unit": SupplyItem.Unit.LITER, "min_qty": Decimal("2.00")},
            {"category": SupplyItem.Category.DTF_TEXTIL, "name": "Tinta DTF Têxtil - Magenta", "unit": SupplyItem.Unit.LITER, "min_qty": Decimal("2.00")},
            # DTF Têxtil - Consumíveis
            {"category": SupplyItem.Category.DTF_TEXTIL, "name": "Pó TPU DTF Têxtil", "unit": SupplyItem.Unit.KG, "min_qty": Decimal("5.00")},
            {"category": SupplyItem.Category.DTF_TEXTIL, "name": "Filme DTF Têxtil (Bobina 60cm)", "unit": SupplyItem.Unit.METER, "min_qty": Decimal("50.00")},

            # DTF UV - Tintas
            {"category": SupplyItem.Category.DTF_UV, "name": "Tinta DTF UV - Preto", "unit": SupplyItem.Unit.LITER, "min_qty": Decimal("1.00")},
            {"category": SupplyItem.Category.DTF_UV, "name": "Tinta DTF UV - Branco", "unit": SupplyItem.Unit.LITER, "min_qty": Decimal("2.00")},
            {"category": SupplyItem.Category.DTF_UV, "name": "Tinta DTF UV - Azul (Ciano)", "unit": SupplyItem.Unit.LITER, "min_qty": Decimal("1.00")},
            {"category": SupplyItem.Category.DTF_UV, "name": "Tinta DTF UV - Amarelo", "unit": SupplyItem.Unit.LITER, "min_qty": Decimal("1.00")},
            {"category": SupplyItem.Category.DTF_UV, "name": "Tinta DTF UV - Magenta", "unit": SupplyItem.Unit.LITER, "min_qty": Decimal("1.00")},
            {"category": SupplyItem.Category.DTF_UV, "name": "Verniz DTF UV", "unit": SupplyItem.Unit.LITER, "min_qty": Decimal("1.00")},
            # DTF UV - Consumíveis
            {"category": SupplyItem.Category.DTF_UV, "name": "Filme A - DTF UV", "unit": SupplyItem.Unit.ROLL, "min_qty": Decimal("2.00")},
            {"category": SupplyItem.Category.DTF_UV, "name": "Filme B - DTF UV (Transfer)", "unit": SupplyItem.Unit.ROLL, "min_qty": Decimal("2.00")},

            # Camisetas - Dry Fit
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Dry Fit - Tam. P", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("10.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Dry Fit - Tam. M", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("15.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Dry Fit - Tam. G", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("15.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Dry Fit - Tam. GG", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("10.00")},

            # Camisetas - Algodão
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Algodão - Tam. P", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("10.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Algodão - Tam. M", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("15.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Algodão - Tam. G", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("15.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Algodão - Tam. GG", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("10.00")},
        ]

        created_count = 0
        for data in initial_supplies:
            item, created = SupplyItem.objects.get_or_create(
                category=data["category"],
                name=data["name"],
                defaults={
                    "unit": data["unit"],
                    "quantity": Decimal("0.00"),
                    "minimum_quantity": data["min_qty"],
                }
            )
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"Insumo criado: {item.name}"))

        self.stdout.write(self.style.SUCCESS(f"Carga inicial concluída: {created_count} insumos adicionados."))
