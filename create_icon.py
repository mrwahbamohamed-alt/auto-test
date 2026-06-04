"""
create_icon.py — Generates injector.ico for Auto Test
Draws a professional diesel injector icon programmatically using Pillow.
"""
from PIL import Image, ImageDraw, ImageFilter
import math, sys

# ── App palette (matches the dashboard UI) ─────────────────────────────
BG          = (11,  13,  17)
BORDER      = (44,  51,  71)
METAL_HI    = (195, 205, 215)
METAL_MID   = (130, 142, 158)
METAL_LO    = ( 75,  85, 100)
METAL_DARK  = ( 50,  58,  72)
NUT_COL     = ( 85,  96, 112)
CONNECTOR   = ( 60,  70,  85)
PIN_GOLD    = (200, 170,  80)
SPRAY_GRN   = (  0, 230, 118)   # phosphor green
SPRAY_DIM   = (  0, 140,  72)
AMBER       = (255, 179,   0)
RED_GLOW    = (239,  83,  80)


def lerp_color(a, b, t):
    return tuple(int(a[i] + (b[i]-a[i]) * t) for i in range(3))


def draw_injector(size: int = 256) -> Image.Image:
    img  = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    s    = size / 256.0
    cx   = size // 2

    def sc(v):          # scale a value
        return int(v * s)
    def sx(v):          # x coordinate
        return int(cx + v * s)
    def sy(v):          # y coordinate  (0 = top)
        return int(v * s)

    # ── Background ────────────────────────────────────────────────────
    r = sc(24)
    draw.rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=r,
        fill=BG + (255,), outline=BORDER + (255,), width=max(1, sc(2)))

    # subtle vignette (radial darkening ring)
    for i in range(sc(18), 0, -1):
        alpha = int(60 * (1 - i / sc(18)))
        draw.rounded_rectangle(
            [size//2-sc(128)+i, size//2-sc(128)+i,
             size//2+sc(128)-i, size//2+sc(128)-i],
            radius=max(1, r - i),
            outline=(0, 0, 0, alpha), width=1)

    # ── Electrical Connector Cap (top) ───────────────────────────────
    cap_w  = sc(38)
    cap_h  = sc(28)
    cap_x1 = sx(-cap_w//2)
    cap_x2 = sx( cap_w//2)
    cap_y1 = sy(14)
    cap_y2 = sy(14 + cap_h)

    draw.rounded_rectangle(
        [cap_x1, cap_y1, cap_x2, cap_y2], radius=sc(5),
        fill=CONNECTOR + (255,), outline=METAL_DARK + (255,), width=max(1, sc(1)))
    # highlight on top edge
    draw.line([(cap_x1 + sc(4), cap_y1 + sc(2)),
               (cap_x2 - sc(4), cap_y1 + sc(2))],
              fill=METAL_MID + (120,), width=max(1, sc(1)))
    # connector pins
    for px in [-sc(8), 0, sc(8)]:
        draw.rectangle(
            [sx(px) - sc(3), cap_y1 + sc(4),
             sx(px) + sc(3), cap_y1 + sc(14)],
            fill=PIN_GOLD + (255,))

    # ── Upper Body (main cylinder) ────────────────────────────────────
    bw  = sc(54)
    bx1 = sx(-bw//2);  bx2 = sx(bw//2)
    by1 = cap_y2 - sc(4)
    by2 = sy(128)
    bh  = by2 - by1

    # gradient fill (column by column for metallic sheen)
    for xi in range(bx1, bx2 + 1):
        t_x = (xi - bx1) / max(1, bx2 - bx1)
        # bell-curve highlight at ~30% from left
        shine = math.exp(-((t_x - 0.28) ** 2) / 0.015)
        for yi in range(by1, by2 + 1):
            t_y  = (yi - by1) / max(1, bh)
            base = lerp_color(METAL_HI, METAL_LO, t_y)
            col  = lerp_color(base, METAL_HI, shine * 0.55)
            draw.point((xi, yi), fill=col + (255,))

    draw.rounded_rectangle(
        [bx1, by1, bx2, by2], radius=sc(4),
        outline=METAL_DARK + (255,), width=max(1, sc(1)))

    # body groove ring
    groove_y = sy(90)
    draw.rectangle(
        [bx1, groove_y, bx2, groove_y + sc(5)],
        fill=METAL_DARK + (255,))
    draw.line([(bx1, groove_y + sc(2)), (bx2, groove_y + sc(2))],
              fill=METAL_MID + (160,), width=max(1, sc(1)))

    # ── Hex Nut (wrench flat) ─────────────────────────────────────────
    hw  = sc(76)
    hx1 = sx(-hw//2);  hx2 = sx(hw//2)
    hy1 = sy(128);     hy2 = sy(156)
    hh  = hy2 - hy1

    for xi in range(hx1, hx2 + 1):
        t_x = (xi - hx1) / max(1, hx2 - hx1)
        shine = math.exp(-((t_x - 0.25) ** 2) / 0.018)
        for yi in range(hy1, hy2 + 1):
            t_y = (yi - hy1) / max(1, hh)
            base = lerp_color(NUT_COL, METAL_DARK, t_y * 0.6)
            col  = lerp_color(base, METAL_HI, shine * 0.4)
            draw.point((xi, yi), fill=col + (255,))

    draw.rectangle(
        [hx1, hy1, hx2, hy2],
        outline=METAL_DARK + (255,), width=max(1, sc(1)))
    # chamfer lines on nut
    for oy in [sc(4), hy2 - hy1 - sc(4)]:
        draw.line([(hx1 + sc(6), hy1 + oy),
                   (hx2 - sc(6), hy1 + oy)],
                  fill=METAL_DARK + (180,), width=max(1, sc(1)))
    draw.line([(hx1, hy1), (hx2, hy1)],
              fill=METAL_HI + (150,), width=max(1, sc(1)))

    # ── Lower Nozzle Body (tapered) ───────────────────────────────────
    ntop_w = sc(50);  nbot_w = sc(20)
    ny1    = hy2 - sc(2)
    ny2    = sy(214)

    for yi in range(ny1, ny2 + 1):
        t = (yi - ny1) / max(1, ny2 - ny1)
        w = int((ntop_w + (nbot_w - ntop_w) * t) / 2)
        shine = math.exp(-0.2 * (1 + t) ** 2)
        col   = lerp_color(METAL_MID, METAL_LO, t)
        col   = lerp_color(col, METAL_HI, shine * 0.3)
        draw.line([(cx - w, yi), (cx + w, yi)], fill=col + (255,))

    # nozzle outline
    nozzle_poly = [
        (cx - ntop_w//2, ny1), (cx + ntop_w//2, ny1),
        (cx + nbot_w//2, ny2), (cx - nbot_w//2, ny2),
    ]
    draw.polygon(nozzle_poly, outline=METAL_DARK + (255,))

    # ── Nozzle Tip ────────────────────────────────────────────────────
    tip_w = sc(16)
    tip_y1 = ny2 - sc(2)
    tip_y2 = ny2 + sc(12)
    draw.rectangle(
        [cx - tip_w//2, tip_y1, cx + tip_w//2, tip_y2],
        fill=METAL_DARK + (255,))
    draw.line([(cx - tip_w//2, tip_y1), (cx + tip_w//2, tip_y1)],
              fill=METAL_MID + (200,), width=max(1, sc(1)))

    # ── Amber pressure glow ring around nozzle ────────────────────────
    gx, gy = cx, tip_y2
    for r2 in range(sc(22), 0, -1):
        alpha = int(55 * (r2 / sc(22)) ** 2)
        draw.ellipse([gx - r2, gy - r2//2, gx + r2, gy + r2//2],
                     outline=AMBER + (alpha,), width=1)

    # ── Fuel Spray ────────────────────────────────────────────────────
    spray_org = tip_y2 + sc(2)
    spray_end = sy(252)

    # spray angles: 0°, ±20°, ±42°
    spray_defs = [
        (0,   255, sc(2)),
        (-20, 200, sc(2)),
        ( 20, 200, sc(2)),
        (-42, 100, sc(1)),
        ( 42, 100, sc(1)),
    ]
    for angle_deg, alpha, width in spray_defs:
        angle_rad  = math.radians(angle_deg)
        length     = spray_end - spray_org
        ex = cx        + int(length * math.sin(angle_rad))
        ey = spray_org + int(length * math.cos(angle_rad))
        # draw with fading: 3 segments of decreasing alpha
        for seg in range(4):
            t0 = seg / 4
            t1 = (seg + 1) / 4
            seg_alpha = int(alpha * (1 - t0 * 0.7))
            sx0 = cx        + int((length * t0) * math.sin(angle_rad))
            sy0 = spray_org + int((length * t0) * math.cos(angle_rad))
            sx1 = cx        + int((length * t1) * math.sin(angle_rad))
            sy1 = spray_org + int((length * t1) * math.cos(angle_rad))
            overlay = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            odraw   = ImageDraw.Draw(overlay)
            odraw.line([(sx0, sy0), (sx1, sy1)],
                       fill=SPRAY_GRN + (seg_alpha,), width=width)
            img = Image.alpha_composite(img, overlay)
            draw = ImageDraw.Draw(img)

    # spray origin bright dot
    dot_r = sc(5)
    draw.ellipse([cx - dot_r, spray_org - dot_r, cx + dot_r, spray_org + dot_r],
                 fill=SPRAY_GRN + (200,))
    draw.ellipse([cx - sc(2), spray_org - sc(2), cx + sc(2), spray_org + sc(2)],
                 fill=(255, 255, 255, 240))

    # ── Final glow overlay (green subtle) ────────────────────────────
    glow = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gr = sc(48)
    gdraw.ellipse([cx - gr, spray_org - gr//2, cx + gr, spray_org + gr],
                  fill=SPRAY_GRN + (22,))
    glow = glow.filter(ImageFilter.GaussianBlur(sc(12)))
    img  = Image.alpha_composite(img, glow)

    return img


def make_ico(path: str = 'injector.ico'):
    """Render at 256 and downsample to all ICO sizes."""
    sizes  = [256, 128, 64, 48, 32, 16]
    base   = draw_injector(256)
    frames = []

    for sz in sizes:
        if sz == 256:
            frames.append(base.copy())
        else:
            # Resize base; use LANCZOS for quality
            frame = base.resize((sz, sz), Image.LANCZOS)
            # At very small sizes boost contrast slightly
            if sz <= 32:
                from PIL import ImageEnhance
                frame = ImageEnhance.Contrast(frame).enhance(1.25)
                frame = ImageEnhance.Sharpness(frame).enhance(1.4)
            frames.append(frame)

    frames[0].save(
        path,
        format='ICO',
        sizes=[(sz, sz) for sz in sizes],
        append_images=frames[1:],
    )
    print(f"Saved: {path}  ({len(sizes)} sizes: {sizes})")

    # Also save a PNG preview
    preview = path.replace('.ico', '_preview.png')
    base.save(preview)
    print(f"Preview: {preview}")


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else 'injector.ico'
    make_ico(out)
