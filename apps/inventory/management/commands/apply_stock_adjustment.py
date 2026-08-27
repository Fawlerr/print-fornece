from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from apps.inventory.models import SupplyItem, SupplyMovement


class Command(BaseCommand):
    help = "Aplica o ajuste de inventário geral de estoque solicitado pelo cliente de forma aditiva e segura."

    def handle(self, *args, **options):
        self.stdout.write("Iniciando ajuste geral de estoque...")

        # Mapeamento estrito dos 31 itens solicitados pelo cliente
        stock_target = [
            # Insumos - Têxtil
            {"category": SupplyItem.Category.DTF_TEXTIL, "name": "Tinta DTF Têxtil - Magenta (M)", "legacy_name": "Tinta DTF Têxtil - Magenta", "unit": SupplyItem.Unit.UNIT, "qty": Decimal("6.00"), "min_qty": Decimal("2.00")},
            {"category": SupplyItem.Category.DTF_TEXTIL, "name": "Tinta DTF Têxtil - Ciano (C)", "legacy_name": "Tinta DTF Têxtil - Azul (Ciano)", "unit": SupplyItem.Unit.UNIT, "qty": Decimal("6.00"), "min_qty": Decimal("2.00")},
            {"category": SupplyItem.Category.DTF_TEXTIL, "name": "Tinta DTF Têxtil - Black (BK)", "legacy_name": "Tinta DTF Têxtil - Preto", "unit": SupplyItem.Unit.UNIT, "qty": Decimal("5.00"), "min_qty": Decimal("2.00")},
            {"category": SupplyItem.Category.DTF_TEXTIL, "name": "Tinta DTF Têxtil - Yellow (Y)", "legacy_name": "Tinta DTF Têxtil - Amarelo", "unit": SupplyItem.Unit.UNIT, "qty": Decimal("4.00"), "min_qty": Decimal("2.00")},
            {"category": SupplyItem.Category.DTF_TEXTIL, "name": "Tinta DTF Têxtil - White (WT)", "legacy_name": "Tinta DTF Têxtil - Branco", "unit": SupplyItem.Unit.UNIT, "qty": Decimal("94.00"), "min_qty": Decimal("10.00")},
            {"category": SupplyItem.Category.DTF_TEXTIL, "name": "Pó TPU DTF Têxtil", "legacy_name": "Pó TPU DTF Têxtil", "unit": SupplyItem.Unit.KG, "qty": Decimal("21.00"), "min_qty": Decimal("5.00")},
            {"category": SupplyItem.Category.DTF_TEXTIL, "name": "Filme DTF Têxtil (Bobina 60cm)", "legacy_name": "Filme DTF Têxtil (Bobina 60cm)", "unit": SupplyItem.Unit.METER, "qty": Decimal("130.00"), "min_qty": Decimal("50.00")},

            # Insumos - UV
            {"category": SupplyItem.Category.DTF_UV, "name": "Tinta DTF UV - Magenta (M)", "legacy_name": "Tinta DTF UV - Magenta", "unit": SupplyItem.Unit.UNIT, "qty": Decimal("6.00"), "min_qty": Decimal("2.00")},
            {"category": SupplyItem.Category.DTF_UV, "name": "Tinta DTF UV - Ciano (C)", "legacy_name": "Tinta DTF UV - Azul (Ciano)", "unit": SupplyItem.Unit.UNIT, "qty": Decimal("6.00"), "min_qty": Decimal("2.00")},
            {"category": SupplyItem.Category.DTF_UV, "name": "Tinta DTF UV - Yellow (Y)", "legacy_name": "Tinta DTF UV - Amarelo", "unit": SupplyItem.Unit.UNIT, "qty": Decimal("6.00"), "min_qty": Decimal("2.00")},
            {"category": SupplyItem.Category.DTF_UV, "name": "Verniz DTF UV - Verniz (V)", "legacy_name": "Verniz DTF UV", "unit": SupplyItem.Unit.UNIT, "qty": Decimal("7.00"), "min_qty": Decimal("2.00")},
            {"category": SupplyItem.Category.DTF_UV, "name": "Tinta DTF UV - White (WT)", "legacy_name": "Tinta DTF UV - Branco", "unit": SupplyItem.Unit.UNIT, "qty": Decimal("8.00"), "min_qty": Decimal("2.00")},
            {"category": SupplyItem.Category.DTF_UV, "name": "Tinta DTF UV - Black (BK)", "legacy_name": "Tinta DTF UV - Preto", "unit": SupplyItem.Unit.UNIT, "qty": Decimal("6.00"), "min_qty": Decimal("2.00")},
            {"category": SupplyItem.Category.DTF_UV, "name": "Filme A - DTF UV", "legacy_name": "Filme A - DTF UV", "unit": SupplyItem.Unit.METER, "qty": Decimal("400.00"), "min_qty": Decimal("50.00")},
            {"category": SupplyItem.Category.DTF_UV, "name": "Filme B - DTF UV (Transfer)", "legacy_name": "Filme B - DTF UV (Transfer)", "unit": SupplyItem.Unit.METER, "qty": Decimal("400.00"), "min_qty": Decimal("50.00")},

            # Camisa 100% Algodão Branca
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Algodão - Branca Tam. P", "legacy_name": "Camiseta Algodão - Tam. P", "unit": SupplyItem.Unit.UNIT, "qty": Decimal("2.00"), "min_qty": Decimal("5.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Algodão - Branca Tam. M", "legacy_name": "Camiseta Algodão - Tam. M", "unit": SupplyItem.Unit.UNIT, "qty": Decimal("0.00"), "min_qty": Decimal("5.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Algodão - Branca Tam. G", "legacy_name": None, "unit": SupplyItem.Unit.UNIT, "qty": Decimal("13.00"), "min_qty": Decimal("5.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Algodão - Branca Tam. GG", "legacy_name": "Camiseta Algodão - Tam. GG", "unit": SupplyItem.Unit.UNIT, "qty": Decimal("2.00"), "min_qty": Decimal("5.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Algodão - Branca Tam. XG", "legacy_name": None, "unit": SupplyItem.Unit.UNIT, "qty": Decimal("2.00"), "min_qty": Decimal("2.00")},

            # Camisa 100% Algodão Preta
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Algodão - Preta Tam. P", "legacy_name": None, "unit": SupplyItem.Unit.UNIT, "qty": Decimal("7.00"), "min_qty": Decimal("5.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Algodão - Preta Tam. M", "legacy_name": None, "unit": SupplyItem.Unit.UNIT, "qty": Decimal("16.00"), "min_qty": Decimal("5.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Algodão - Preta Tam. G", "legacy_name": "Camiseta Algodão - Preta Tam. G", "unit": SupplyItem.Unit.UNIT, "qty": Decimal("19.00"), "min_qty": Decimal("5.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Algodão - Preta Tam. GG", "legacy_name": None, "unit": SupplyItem.Unit.UNIT, "qty": Decimal("1.00"), "min_qty": Decimal("5.00")},

            # Camisa Dry Preta
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Dry Fit - Preta Tam. P", "legacy_name": "Camiseta Dry Fit - Tam. P", "unit": SupplyItem.Unit.UNIT, "qty": Decimal("5.00"), "min_qty": Decimal("5.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Dry Fit - Preta Tam. M", "legacy_name": "Camiseta Dry Fit - Tam. M", "unit": SupplyItem.Unit.UNIT, "qty": Decimal("10.00"), "min_qty": Decimal("5.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Dry Fit - Preta Tam. G", "legacy_name": "Camiseta Dry Fit - Tam. G", "unit": SupplyItem.Unit.UNIT, "qty": Decimal("4.00"), "min_qty": Decimal("5.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Dry Fit - Preta Tam. GG", "legacy_name": "Camiseta Dry Fit - Tam. GG", "unit": SupplyItem.Unit.UNIT, "qty": Decimal("16.00"), "min_qty": Decimal("5.00")},

            # Camisa Dry Branca
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Dry Fit - Branca Tam. P", "legacy_name": None, "unit": SupplyItem.Unit.UNIT, "qty": Decimal("2.00"), "min_qty": Decimal("5.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Dry Fit - Branca Tam. M", "legacy_name": None, "unit": SupplyItem.Unit.UNIT, "qty": Decimal("8.00"), "min_qty": Decimal("5.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Dry Fit - Branca Tam. G", "legacy_name": None, "unit": SupplyItem.Unit.UNIT, "qty": Decimal("5.00"), "min_qty": Decimal("5.00")},
            {"category": SupplyItem.Category.SHIRTS, "name": "Camiseta Dry Fit - Branca Tam. GG", "legacy_name": None, "unit": SupplyItem.Unit.UNIT, "qty": Decimal("0.00"), "min_qty": Decimal("5.00")},
        ]

        with transaction.atomic():
            for target in stock_target:
                item = None

                # 1. Tentar encontrar pelo nome exato
                item = SupplyItem.objects.filter(category=target["category"], name=target["name"]).first()

                # 2. Se não encontrar, tentar pelo nome legado (para renomear e reaproveitar histórico de movimentações)
                if not item and target.get("legacy_name"):
                    item = SupplyItem.objects.filter(category=target["category"], name=target["legacy_name"]).first()

                if item:
                    # Atualizar metadados do item existente
                    old_name = item.name
                    old_qty = item.quantity
                    item.name = target["name"]
                    item.unit = target["unit"]
                    item.minimum_quantity = target["min_qty"]
                    item.quantity = target["qty"]
                    item.save()

                    # Criar movimentação de ajuste no histórico
                    SupplyMovement.objects.create(
                        item=item,
                        movement_type=SupplyMovement.MovementType.ADJUSTMENT,
                        quantity=target["qty"],
                        previous_quantity=old_qty,
                        new_quantity=target["qty"],
                        description="Inventário Geral de Estoque - Ajuste Solicitado",
                    )
                    self.stdout.write(self.style.SUCCESS(
                        f"[ATUALIZADO] {old_name} -> {item.name} | Saldo: {old_qty} -> {target['qty']} {item.unit}"
                    ))
                else:
                    # Criar novo item
                    item = SupplyItem.objects.create(
                        category=target["category"],
                        name=target["name"],
                        unit=target["unit"],
                        quantity=target["qty"],
                        minimum_quantity=target["min_qty"],
                    )
                    SupplyMovement.objects.create(
                        item=item,
                        movement_type=SupplyMovement.MovementType.ADJUSTMENT,
                        quantity=target["qty"],
                        previous_quantity=Decimal("0.00"),
                        new_quantity=target["qty"],
                        description="Inventário Geral de Estoque - Carga Inicial",
                    )
                    self.stdout.write(self.style.SUCCESS(
                        f"[NOVO] {item.name} | Saldo Inicial: {target['qty']} {item.unit}"
                    ))

        total_items = SupplyItem.objects.count()
        self.stdout.write(self.style.SUCCESS(f"\nAjuste de estoque concluído com sucesso! Total de itens cadastrados: {total_items}"))
