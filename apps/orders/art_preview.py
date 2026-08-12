from __future__ import annotations

import io
from pathlib import Path
from PIL import Image, ImageDraw


def generate_art_preview_image(order) -> bytes:
    """Generate a composite preview image of the order's artwork on a clean gray background."""
    bg_width, bg_height = 1000, 1000
    bg_color = (220, 224, 230)  # Neutral gray background

    # Create canvas
    canvas = Image.new("RGB", (bg_width, bg_height), bg_color)
    draw = ImageDraw.Draw(canvas)

    # Find active attachments
    active_attachments = list(order.attachments.filter(removed_at__isnull=True))

    artwork_attachment = None
    image_extensions = ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff', '.gif')

    # First look for raster image attachments
    for att in active_attachments:
        ext = Path(att.original_name).suffix.lower()
        if ext in image_extensions:
            artwork_attachment = att
            break

    image_placed = False

    if artwork_attachment and artwork_attachment.file:
        try:
            with artwork_attachment.file.open("rb") as f:
                raw_data = f.read()
                art_img = Image.open(io.BytesIO(raw_data))
                if art_img.mode == "CMYK":
                    art_img = art_img.convert("RGB")
                art_img = art_img.convert("RGBA")

                # Scale image proportionally to fill the card comfortably (up to 780x720)
                w, h = art_img.size
                max_w, max_h = 780, 720
                scale = min(max_w / max(1, w), max_h / max(1, h))

                new_w = int(w * scale)
                new_h = int(h * scale)
                art_img = art_img.resize((new_w, new_h), Image.Resampling.LANCZOS)

                # Drop shadow card behind artwork
                pos_x = (bg_width - new_w) // 2
                pos_y = (bg_height - new_h) // 2 - 20

                shadow_offset = 12
                shadow_box = [pos_x + shadow_offset, pos_y + shadow_offset, pos_x + new_w + shadow_offset, pos_y + new_h + shadow_offset]
                draw.rectangle(shadow_box, fill=(180, 185, 192))

                # White frame card
                frame_box = [pos_x - 10, pos_y - 10, pos_x + new_w + 10, pos_y + new_h + 10]
                draw.rectangle(frame_box, fill=(255, 255, 255))

                # Paste art
                canvas.paste(art_img, (pos_x, pos_y), mask=art_img)
                image_placed = True
        except Exception:
            image_placed = False

    if not image_placed:
        # Placeholder / Document card on gray background
        card_w, card_h = 820, 540
        pos_x = (bg_width - card_w) // 2
        pos_y = (bg_height - card_h) // 2 - 30

        # Card shadow & background
        draw.rectangle([pos_x + 10, pos_y + 10, pos_x + card_w + 10, pos_y + card_h + 10], fill=(180, 185, 192))
        draw.rectangle([pos_x, pos_y, pos_x + card_w, pos_y + card_h], fill=(255, 255, 255), outline=(200, 205, 210), width=2)

        # Header banner
        draw.rectangle([pos_x, pos_y, pos_x + card_w, pos_y + 90], fill=(30, 41, 59))
        draw.text((pos_x + 35, pos_y + 28), "PRINT FORNECE — PREVIEW DA ARTE", fill=(255, 255, 255))

        # Order details
        draw.text((pos_x + 40, pos_y + 120), f"Pedido: #{order.number}", fill=(17, 24, 39))
        draw.text((pos_x + 40, pos_y + 160), f"Cliente: {order.client_name}", fill=(17, 24, 39))

        desc_snippet = (order.description[:65] + "...") if len(order.description) > 65 else order.description
        draw.text((pos_x + 40, pos_y + 200), f"Descrição: {desc_snippet}", fill=(75, 85, 99))
        draw.text((pos_x + 40, pos_y + 240), f"Valor Total: R$ {order.total_amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."), fill=(16, 185, 129))

        if active_attachments:
            first_att = active_attachments[0]
            size_kb = max(1, first_att.size // 1024)
            draw.rectangle([pos_x + 40, pos_y + 300, pos_x + card_w - 40, pos_y + 460], fill=(241, 245, 249), outline=(203, 213, 225), width=1)
            draw.text((pos_x + 60, pos_y + 325), f"📁 ARQUIVO DE IMPRESSÃO: {first_att.original_name}", fill=(15, 23, 42))
            draw.text((pos_x + 60, pos_y + 365), f"Tamanho: {size_kb} KB · Total de arquivos: {len(active_attachments)}", fill=(71, 85, 105))
            draw.text((pos_x + 60, pos_y + 410), "STATUS: DOCUMENTO ANEXADO - PRONTO PARA IMPRESSÃO", fill=(36, 120, 60))
        else:
            draw.rectangle([pos_x + 40, pos_y + 310, pos_x + card_w - 40, pos_y + 450], fill=(254, 242, 242), outline=(254, 202, 202), width=1)
            draw.text((pos_x + 60, pos_y + 345), "⚠️ ARTE EM FASE DE PREPARAÇÃO", fill=(185, 28, 28))
            draw.text((pos_x + 60, pos_y + 390), "Nenhum arquivo de arte foi anexado a este pedido ainda.", fill=(120, 40, 40))

    # Watermark text at the bottom
    draw.text((30, bg_height - 50), f"Print Fornece · Orçamento do Pedido #{order.number}", fill=(120, 125, 135))
    draw.text((bg_width - 320, bg_height - 50), "⚠️ MARCA D'ÁGUA TEMPORÁRIA", fill=(220, 38, 38))

    output = io.BytesIO()
    canvas.save(output, format="PNG")
    png_bytes = output.getvalue()
    output.close()
    return png_bytes
