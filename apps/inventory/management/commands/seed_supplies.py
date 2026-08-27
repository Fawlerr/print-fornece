from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.inventory.models import SupplyItem


class Command(BaseCommand):
    help = "Cria a grade inicial de insumos de estoque (DTF Têxtil, DTF UV e Camisetas) se ainda não existirem."

    def handle(self, *args, **options):
        initial_supplies = [
            # DTF Têxtil - Tintas
            {"category": SupplyItem.Category.DTF_TEXTIL, "name": "Tinta DTF Têxtil - Black (BK)", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("2.00")},
            {"category": SupplyItem.Category.DTF_TEXTIL, "name": "Tinta DTF Têxtil - White (WT)", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("10.00")},
            {"category": SupplyItem.Category.DTF_TEXTIL, "name": "Tinta DTF Têxtil - Ciano (C)", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("2.00")},
            {"category": SupplyItem.Category.DTF_TEXTIL, "name": "Tinta DTF Têxtil - Yellow (Y)", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("2.00")},
            {"category": SupplyItem.Category.DTF_TEXTIL, "name": "Tinta DTF Têxtil - Magenta (M)", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("2.00")},
            # DTF Têxtil - Consumíveis
            {"category": SupplyItem.Category.DTF_TEXTIL, "name": "Pó TPU DTF Têxtil", "unit": SupplyItem.Unit.KG, "min_qty": Decimal("5.00")},
            {"category": SupplyItem.Category.DTF_TEXTIL, "name": "Filme DTF Têxtil (Bobina 60cm)", "unit": SupplyItem.Unit.METER, "min_qty": Decimal("50.00")},

            # DTF UV - Tintas e Verniz
            {"category": SupplyItem.Category.DTF_UV, "name": "Tinta DTF UV - Black (BK)", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("2.00")},
            {"category": SupplyItem.Category.DTF_UV, "name": "Tinta DTF UV - White (WT)", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("2.00")},
            {"category": SupplyItem.Category.DTF_UV, "name": "Tinta DTF UV - Ciano (C)", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("2.00")},
            {"category": SupplyItem.Category.DTF_UV, "name": "Tinta DTF UV - Yellow (Y)", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("2.00")},
            {"category": SupplyItem.Category.DTF_UV, "name": "Tinta DTF UV - Magenta (M)", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("2.00")},
            {"category": SupplyItem.Category.DTF_UV, "name": "Verniz DTF UV - Verniz (V)", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("2.00")},
            # DTF UV - Consumíveis
            {"category": SupplyItem.Category.DTF_UV, "name": "Filme A - DTF UV", "unit": SupplyItem.Unit.METER, "min_qty": Decimal("50.00")},
            {"category": SupplyItem.Category.DTF_UV, "name": "Filme B - DTF UV (Transfer)", "unit": SupplyItem.Unit.METER, "min_qty": Decimal("50.00")},

            # Camisetas - Algodão Branca
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Algodão - Branca Tam. P", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("5.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Algodão - Branca Tam. M", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("5.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Algodão - Branca Tam. G", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("5.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Algodão - Branca Tam. GG", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("5.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Algodão - Branca Tam. XG", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("2.00")},

            # Camisetas - Algodão Preta
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Algodão - Preta Tam. P", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("5.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Algodão - Preta Tam. M", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("5.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Algodão - Preta Tam. G", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("5.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Algodão - Preta Tam. GG", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("5.00")},

            # Camisetas - Dry Fit Preta
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Dry Fit - Preta Tam. P", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("5.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Dry Fit - Preta Tam. M", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("5.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Dry Fit - Preta Tam. G", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("5.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Dry Fit - Preta Tam. GG", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("5.00")},

            # Camisetas - Dry Fit Branca
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Dry Fit - Branca Tam. P", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("5.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Dry Fit - Branca Tam. M", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("5.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Dry Fit - Branca Tam. G", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("5.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Dry Fit - Branca Tam. GG", "unit": SupplyItem.Unit.UNIT, "min_qty": Decimal("5.00")},
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
