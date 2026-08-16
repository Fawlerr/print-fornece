from __future__ import annotations

import io
from pathlib import Path
from django.conf import settings
from PIL import Image, ImageDraw, ImageFont, ImageEnhance


def generate_art_preview_image(order, attachment_id: int | str | None = None) -> bytes:
    """
    Generate a composite preview image of an order's artwork on a neutral gray background,
    with an elegant, semi-transparent watermark based on the company logo and branding.
    Supports images (.png, .jpg, .webp, .tiff, etc.) and PDFs (.pdf).
    """
    bg_width, bg_height = 1200, 1200
    bg_color = (226, 232, 240)  # Slate 200 neutral background

    canvas = Image.new("RGBA", (bg_width, bg_height), bg_color + (255,))
    draw = ImageDraw.Draw(canvas)

    active_attachments = list(order.attachments.filter(removed_at__isnull=True).order_by("id"))
    total_files = len(active_attachments)

    target_attachment = None
    current_index = 1

    if attachment_id:
        try:
            target_id = int(attachment_id)
            for idx, att in enumerate(active_attachments, 1):
                if att.pk == target_id:
                    target_attachment = att
                    current_index = idx
                    break
        except (ValueError, TypeError):
            pass

    if not target_attachment and active_attachments:
        target_attachment = active_attachments[0]
        current_index = 1

    art_img = None
    file_title = "Sem anexo"

    if target_attachment and target_attachment.file:
        file_title = target_attachment.original_name
        ext = Path(target_attachment.original_name).suffix.lower()

        try:
            with target_attachment.file.open("rb") as f:
                raw_bytes = f.read()

            if ext == ".pdf":
                try:
                    import pypdfium2 as pdfium
                    pdf = pdfium.PdfDocument(raw_bytes)
                    if len(pdf) > 0:
                        page = pdf[0]
                        # Render at 2x resolution
                        rendered = page.render(scale=2.5)
                        art_img = rendered.to_pil().convert("RGBA")
                except Exception:
                    art_img = None
            else:
                try:
                    raw_img = Image.open(io.BytesIO(raw_bytes))
                    if raw_img.mode == "CMYK":
                        raw_img = raw_img.convert("RGB")
                    art_img = raw_img.convert("RGBA")
                except Exception:
                    art_img = None
        except Exception:
            art_img = None

    if art_img:
        # Scale image to fit inside 940x840 comfortably
        orig_w, orig_h = art_img.size
        max_w, max_h = 940, 840
        scale = min(max_w / max(1, orig_w), max_h / max(1, orig_h))
        new_w = max(1, int(orig_w * scale))
        new_h = max(1, int(orig_h * scale))
        art_img = art_img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        pos_x = (bg_width - new_w) // 2
        pos_y = 110 + (max_h - new_h) // 2

        # 1. Card Drop Shadow
        shadow_offset = 12
        shadow_box = [pos_x + shadow_offset, pos_y + shadow_offset, pos_x + new_w + shadow_offset, pos_y + new_h + shadow_offset]
        draw.rectangle(shadow_box, fill=(148, 163, 184, 255))

        # 2. High-contrast Gray mat card (Slate 800) so white prints and transparent PNGs stand out
        frame_pad = 12
        frame_box = [pos_x - frame_pad, pos_y - frame_pad, pos_x + new_w + frame_pad, pos_y + new_h + frame_pad]
        draw.rectangle(frame_box, fill=(51, 65, 85, 255), outline=(71, 85, 105, 255), width=2)

        # 3. Paste Artwork
        canvas.paste(art_img, (pos_x, pos_y), mask=art_img)

        # 4. Apply Watermark Overlay (Company Logo & Security Markings)
        watermark_layer = Image.new("RGBA", (bg_width, bg_height), (0, 0, 0, 0))
        wm_draw = ImageDraw.Draw(watermark_layer)

        # Load Logo for Watermark
        logo_path = None
        for candidate in ("images/logo.png", "static/logo.png", "images/logo.jpg", "static/logo.jpg"):
            p = Path(settings.BASE_DIR) / candidate
            if p.is_file():
                logo_path = p
                break

        if logo_path:
            try:
                logo_raw = Image.open(logo_path).convert("RGBA")
                # Semi-transparent watermark logo in center of artwork
                wm_w = min(int(new_w * 0.65), 500)
                wm_scale = wm_w / max(1, logo_raw.size[0])
                wm_h = int(logo_raw.size[1] * wm_scale)
                logo_resized = logo_raw.resize((wm_w, wm_h), Image.Resampling.LANCZOS)

                # Adjust logo opacity to ~28%
                alpha = logo_resized.split()[3]
                alpha = ImageEnhance.Brightness(alpha).enhance(0.28)
                logo_resized.putalpha(alpha)

                wm_pos_x = pos_x + (new_w - wm_w) // 2
                wm_pos_y = pos_y + (new_h - wm_h) // 2
                watermark_layer.paste(logo_resized, (wm_pos_x, wm_pos_y), mask=logo_resized)
            except Exception:
                pass

        # Diagonal watermark text stripes over the artwork
        wm_step_x = max(180, new_w // 3)
        wm_step_y = max(140, new_h // 3)
        for wx in range(pos_x + 30, pos_x + new_w - 40, wm_step_x):
            for wy in range(pos_y + 40, pos_y + new_h - 40, wm_step_y):
                wm_draw.text((wx, wy), "PRINT FORNECE", fill=(255, 255, 255, 60))
                wm_draw.text((wx, wy + 16), "PRÉVIA DE APROVAÇÃO", fill=(15, 23, 42, 60))

        # Composite watermark onto main canvas
        canvas = Image.alpha_composite(canvas, watermark_layer)
        draw = ImageDraw.Draw(canvas)

    else:
        # Document or Placeholder Card
        card_w, card_h = 920, 580
        pos_x = (bg_width - card_w) // 2
        pos_y = (bg_height - card_h) // 2 - 20

        draw.rectangle([pos_x + 10, pos_y + 10, pos_x + card_w + 10, pos_y + card_h + 10], fill=(180, 190, 202, 255))
        draw.rectangle([pos_x, pos_y, pos_x + card_w, pos_y + card_h], fill=(255, 255, 255, 255), outline=(203, 213, 225, 255), width=2)

        # Header banner
        draw.rectangle([pos_x, pos_y, pos_x + card_w, pos_y + 80], fill=(30, 41, 59, 255))
        draw.text((pos_x + 30, pos_y + 26), "PRINT FORNECE — VISUALIZAÇÃO DO PEDIDO", fill=(255, 255, 255, 255))

        draw.text((pos_x + 40, pos_y + 120), f"Pedido: #{order.number}", fill=(15, 23, 42, 255))
        draw.text((pos_x + 40, pos_y + 160), f"Cliente: {order.client_name}", fill=(15, 23, 42, 255))

        desc_snippet = (order.description[:70] + "...") if len(order.description) > 70 else order.description
        draw.text((pos_x + 40, pos_y + 200), f"Descrição: {desc_snippet}", fill=(71, 85, 105, 255))
        draw.text((pos_x + 40, pos_y + 240), f"Valor Total: R$ {order.total_amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."), fill=(16, 185, 129, 255))

        if target_attachment:
            size_kb = max(1, target_attachment.size // 1024)
            draw.rectangle([pos_x + 40, pos_y + 310, pos_x + card_w - 40, pos_y + 490], fill=(241, 245, 249, 255), outline=(203, 213, 225, 255), width=1)
            draw.text((pos_x + 60, pos_y + 335), f"📁 ARQUIVO ANEXADO: {target_attachment.original_name}", fill=(15, 23, 42, 255))
            draw.text((pos_x + 60, pos_y + 375), f"Tamanho: {size_kb} KB · Arquivo {current_index} de {total_files}", fill=(71, 85, 105, 255))
            draw.text((pos_x + 60, pos_y + 420), "DOCUMENTO RECEBIDO COM SUCESSO", fill=(36, 120, 60, 255))
        else:
            draw.rectangle([pos_x + 40, pos_y + 310, pos_x + card_w - 40, pos_y + 470], fill=(254, 242, 242, 255), outline=(254, 202, 202, 255), width=1)
            draw.text((pos_x + 60, pos_y + 345), "ARQUIVO PENDENTE DE ENVIO", fill=(185, 28, 28, 255))
            draw.text((pos_x + 60, pos_y + 390), "Nenhum arquivo ou arte foi anexado a este pedido ainda.", fill=(120, 40, 40, 255))

    # Top Bar Info
    draw.rectangle([0, 0, bg_width, 60], fill=(15, 23, 42, 255))
    draw.text((30, 20), f"PRINT FORNECE · PEDIDO #{order.number} · {order.client_name.upper()}", fill=(255, 255, 255, 255))
    if total_files > 0:
        draw.text((bg_width - 320, 20), f"ARQUIVO {current_index} DE {total_files}: {file_title[:24]}", fill=(134, 239, 172, 255))

    # Bottom Branding & Anti-tamper footer
    draw.rectangle([0, bg_height - 50, bg_width, bg_height], fill=(241, 245, 249, 255))
    draw.text((30, bg_height - 35), f"Print Fornece · Pré-visualização com marca d'água · Documento protegido para conferência", fill=(100, 116, 139, 255))
    draw.text((bg_width - 240, bg_height - 35), f"Total de Anexos: {total_files}", fill=(100, 116, 139, 255))

    final_canvas = canvas.convert("RGB")
    output = io.BytesIO()
    final_canvas.save(output, format="PNG", optimize=True)
    png_bytes = output.getvalue()
    output.close()
    return png_bytes

