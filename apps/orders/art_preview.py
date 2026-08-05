from __future__ import annotations

import io
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def generate_art_preview_image(order) -> bytes:
    """Generate a composite preview image of the order's artwork on a clean gray background."""
    bg_width, bg_height = 1000, 1000
    bg_color = (220, 224, 230)  # Neutral gray background
    
    # Create canvas
    canvas = Image.new("RGB", (bg_width, bg_height), bg_color)
    draw = ImageDraw.Draw(canvas)

    # Find artwork attachment
    artwork_attachment = None
    for att in order.attachments.filter(removed_at__isnull=True):
        ext = Path(att.original_name).suffix.lower()
        if ext in ('.png', '.jpg', '.jpeg', '.webp'):
            artwork_attachment = att
            break

    image_placed = False
    if artwork_attachment and artwork_attachment.file:
        try:
            art_img = Image.open(artwork_attachment.file.path)
            art_img = art_img.convert("RGBA")
            
            # Scale image to fit canvas with padding
            max_w, max_h = 800, 750
            art_img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)

            # Drop shadow card behind artwork
            w, h = art_img.size
            pos_x = (bg_width - w) // 2
            pos_y = (bg_height - h) // 2 - 20
            
            shadow_offset = 10
            shadow_box = [pos_x + shadow_offset, pos_y + shadow_offset, pos_x + w + shadow_offset, pos_y + h + shadow_offset]
            draw.rectangle(shadow_box, fill=(180, 185, 192))
            
            # White frame card
            frame_box = [pos_x - 8, pos_y - 8, pos_x + w + 8, pos_y + h + 8]
            draw.rectangle(frame_box, fill=(255, 255, 255))
            
            # Paste art
            canvas.paste(art_img, (pos_x, pos_y), mask=art_img)
            image_placed = True
        except Exception:
            image_placed = False

    if not image_placed:
        # Placeholder graphic card on gray background
        card_w, card_h = 750, 500
        pos_x = (bg_width - card_w) // 2
        pos_y = (bg_height - card_h) // 2 - 40
        
        # Card shadow & background
        draw.rectangle([pos_x + 8, pos_y + 8, pos_x + card_w + 8, pos_y + card_h + 8], fill=(180, 185, 192))
        draw.rectangle([pos_x, pos_y, pos_x + card_w, pos_y + card_h], fill=(255, 255, 255), outline=(200, 205, 210), width=2)
        
        # Header banner
        draw.rectangle([pos_x, pos_y, pos_x + card_w, pos_y + 90], fill=(30, 41, 59))
        draw.text((pos_x + 30, pos_y + 28), "PRINT FORNECE — PREVIEW DA ARTE", fill=(255, 255, 255))
        
        # Text details
        draw.text((pos_x + 40, pos_y + 130), f"Pedido: #{order.number}", fill=(17, 24, 39))
        draw.text((pos_x + 40, pos_y + 170), f"Cliente: {order.client_name}", fill=(17, 24, 39))
        draw.text((pos_x + 40, pos_y + 210), f"Descrição: {order.description[:60]}...", fill=(75, 85, 99))
        draw.text((pos_x + 40, pos_y + 270), f"Valor Total: R$ {order.total_amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."), fill=(16, 185, 129))
        
        draw.text((pos_x + 40, pos_y + 360), "[ARTE EM FASE DE PREPARAÇÃO / AGUARDANDO ANEXO]", fill=(156, 163, 175))

    # Watermark text at the bottom
    draw.text((30, bg_height - 50), f"Print Fornece · Orçamento do Pedido #{order.number}", fill=(120, 125, 135))
    draw.text((bg_width - 320, bg_height - 50), "⚠️ MARCA D'ÁGUA TEMPORÁRIA", fill=(220, 38, 38))

    output = io.BytesIO()
    canvas.save(output, format="PNG")
    png_bytes = output.getvalue()
    output.close()
    return png_bytes
