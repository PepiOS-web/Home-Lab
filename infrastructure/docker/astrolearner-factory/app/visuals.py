from __future__ import annotations

import hashlib
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_REGULAR = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
FONT_BOLD = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
BRAND_MAGENTA = (210, 0, 105)
BRAND_CYAN = (39, 209, 255)
BACKGROUND_TOP = (4, 8, 24)
BACKGROUND_BOTTOM = (19, 8, 42)


def _seed(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_BOLD if bold else FONT_REGULAR), size=size)


def _gradient(width: int, height: int) -> Image.Image:
    strip = Image.new("RGB", (1, height), BACKGROUND_TOP)
    pixels = strip.load()
    for y in range(height):
        ratio = y / max(1, height - 1)
        pixels[0, y] = tuple(
            round(
                BACKGROUND_TOP[index] * (1 - ratio) + BACKGROUND_BOTTOM[index] * ratio
            )
            for index in range(3)
        )
    return strip.resize((width, height))


def _starfield(width: int, height: int, seed_text: str) -> Image.Image:
    image = _gradient(width, height)
    draw = ImageDraw.Draw(image)
    rng = random.Random(_seed(seed_text))
    for _ in range(max(130, (width * height) // 12000)):
        x = rng.randrange(width)
        y = rng.randrange(height)
        radius = rng.choice((1, 1, 1, 2, 2, 3))
        brightness = rng.randrange(125, 256)
        color = rng.choice(
            ((brightness, brightness, brightness), (145, 200, 255), (220, 170, 225))
        )
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
    return image


def _wrap(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    lines: list[str] = []
    current: list[str] = []
    for word in text.split():
        candidate = " ".join([*current, word])
        box = draw.textbbox((0, 0), candidate, font=font)
        if current and box[2] - box[0] > max_width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    center_x: int,
    start_y: int,
    fill: tuple[int, int, int],
    spacing: int,
) -> int:
    y = start_y
    for line in lines:
        box = draw.textbbox((0, 0), line, font=font)
        draw.text((center_x - (box[2] - box[0]) // 2, y), line, font=font, fill=fill)
        y += box[3] - box[1] + spacing
    return y


def resolve_visual_kind(heading: str, direction: str, requested: str = "auto") -> str:
    if requested != "auto":
        return requested
    text = f"{heading} {direction}".lower()
    if "fase" in text and not any(
        word in text for word in ("órbita", "orbita", "ciclo")
    ):
        return "moon_phases"
    if any(word in text for word in ("eclipse", "umbra", "penumbra")):
        return "eclipse"
    if "luna" in text and any(word in text for word in ("luz", "sol", "ilumin")):
        return "moon_light"
    if any(word in text for word in ("órbita", "orbita", "ciclo", "trayectoria")):
        return "orbit"
    if any(word in text for word in ("anillo", "saturno")):
        return "rings"
    if any(word in text for word in ("galax", "vía láctea", "via lactea")):
        return "galaxy"
    if any(word in text for word in ("estrella", "supernova", "sol")):
        return "star"
    if any(word in text for word in ("telescop", "observatorio")):
        return "telescope"
    if any(word in text for word in ("escala", "tamaño", "tamano", "distancia")):
        return "scale"
    if any(word in text for word in ("cronología", "cronologia", "historia", "años")):
        return "timeline"
    if any(
        word in text
        for word in (
            "planeta",
            "mercurio",
            "venus",
            "tierra",
            "marte",
            "júpiter",
            "jupiter",
            "urano",
            "neptuno",
        )
    ):
        return "planet"
    return "galaxy"


def _moon_disc(radius: int, phase: float, seed_text: str) -> Image.Image:
    size = radius * 2 + 2
    disc = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pixels = disc.load()
    sun_x = math.sin(2 * math.pi * phase)
    sun_z = -math.cos(2 * math.pi * phase)
    for py in range(size):
        ny = (py - radius) / radius
        for px in range(size):
            nx = (px - radius) / radius
            squared = nx * nx + ny * ny
            if squared > 1:
                continue
            nz = math.sqrt(max(0.0, 1.0 - squared))
            light = nx * sun_x + nz * sun_z
            limb = max(0.25, nz)
            if light > 0:
                value = round(152 + 92 * min(1.0, light * 1.25) * limb)
                pixels[px, py] = (value, value, min(255, value + 8), 255)
            else:
                value = round(15 + 20 * limb)
                pixels[px, py] = (value, value + 1, value + 8, 255)

    crater_layer = Image.new("RGBA", disc.size, (0, 0, 0, 0))
    crater_draw = ImageDraw.Draw(crater_layer)
    rng = random.Random(_seed(seed_text))
    for _ in range(10):
        crater_radius = rng.randint(max(2, radius // 18), max(4, radius // 7))
        cx = rng.randint(radius // 3, radius * 5 // 3)
        cy = rng.randint(radius // 3, radius * 5 // 3)
        if (cx - radius) ** 2 + (cy - radius) ** 2 > (radius * 0.72) ** 2:
            continue
        crater_draw.ellipse(
            (
                cx - crater_radius,
                cy - crater_radius,
                cx + crater_radius,
                cy + crater_radius,
            ),
            fill=(15, 20, 36, 35),
            outline=(230, 235, 250, 25),
            width=max(1, radius // 40),
        )
    return Image.alpha_composite(disc, crater_layer)


def _paste_center(image: Image.Image, item: Image.Image, x: int, y: int) -> None:
    image.alpha_composite(item, (x - item.width // 2, y - item.height // 2))


def _draw_arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    color: tuple[int, int, int, int],
    width: int,
) -> None:
    draw.line((*start, *end), fill=color, width=width)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    length = width * 4
    for offset in (2.55, -2.55):
        point = (
            end[0] + round(math.cos(angle + offset) * length),
            end[1] + round(math.sin(angle + offset) * length),
        )
        draw.line((*end, *point), fill=color, width=width)


def _draw_moon_light(
    image: Image.Image, box: tuple[int, int, int, int], seed_text: str
) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    left, top, right, bottom = box
    cy = (top + bottom) // 2
    span = right - left
    sun_radius = max(70, span // 11)
    maximum_halo_radius = sun_radius + 4 * sun_radius // 3
    sun_x = left + maximum_halo_radius + max(16, span // 80)
    for halo in range(4, 0, -1):
        radius = sun_radius + halo * sun_radius // 3
        alpha = 18 + (4 - halo) * 8
        draw.ellipse(
            (sun_x - radius, cy - radius, sun_x + radius, cy + radius),
            fill=(255, 185, 45, alpha),
        )
    draw.ellipse(
        (
            sun_x - sun_radius,
            cy - sun_radius,
            sun_x + sun_radius,
            cy + sun_radius,
        ),
        fill=(255, 201, 62, 255),
    )

    moon_x = left + span * 55 // 100
    moon = _moon_disc(max(58, span // 18), 0.25, f"{seed_text}|moon-light")
    _paste_center(image, moon, moon_x, cy)

    earth_x = right - max(85, span // 14)
    earth_radius = max(48, span // 24)
    draw.ellipse(
        (
            earth_x - earth_radius,
            cy - earth_radius,
            earth_x + earth_radius,
            cy + earth_radius,
        ),
        fill=(38, 115, 204, 255),
        outline=(125, 210, 255, 255),
        width=max(2, span // 500),
    )
    draw.arc(
        (
            earth_x - earth_radius * 3 // 4,
            cy - earth_radius // 2,
            earth_x + earth_radius // 3,
            cy + earth_radius // 2,
        ),
        185,
        345,
        fill=(88, 190, 112, 255),
        width=max(5, earth_radius // 5),
    )
    ray_color = (255, 220, 115, 150)
    for offset in (-sun_radius // 2, 0, sun_radius // 2):
        _draw_arrow(
            draw,
            (sun_x + sun_radius + 15, cy + offset),
            (earth_x - earth_radius - 20, cy + offset),
            ray_color,
            max(2, span // 650),
        )

    label_font = _font(max(18, span // 60), bold=True)
    for label, x in (("SOL", sun_x), ("LUNA", moon_x), ("TIERRA", earth_x)):
        label_box = draw.textbbox((0, 0), label, font=label_font)
        draw.text(
            (x - (label_box[2] - label_box[0]) // 2, bottom - label_font.size * 2),
            label,
            font=label_font,
            fill=(210, 225, 245, 230),
        )


def _draw_moon_phases(
    image: Image.Image, box: tuple[int, int, int, int], seed_text: str
) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    left, top, right, bottom = box
    width = right - left
    height = bottom - top
    columns = 4 if width >= height else 2
    rows = 2 if columns == 4 else 4
    radius = max(34, min(width // (columns * 3), height // (rows * 3)))
    labels = (
        "NUEVA",
        "CRECIENTE",
        "CUARTO CRECIENTE",
        "GIBOSA CRECIENTE",
        "LLENA",
        "GIBOSA MENGUANTE",
        "CUARTO MENGUANTE",
        "MENGUANTE",
    )
    label_font = _font(max(13, min(width, height) // 42), bold=True)
    for index, label in enumerate(labels):
        row, column = divmod(index, columns)
        cx = left + (column * 2 + 1) * width // (columns * 2)
        cy = top + (row * 2 + 1) * height // (rows * 2) - label_font.size // 2
        moon = _moon_disc(radius, index / 8, f"{seed_text}|phase-{index}")
        _paste_center(image, moon, cx, cy)
        label_box = draw.textbbox((0, 0), label, font=label_font)
        draw.text(
            (cx - (label_box[2] - label_box[0]) // 2, cy + radius + 12),
            label,
            font=label_font,
            fill=(220, 228, 246, 230),
        )


def _draw_orbit(
    image: Image.Image, box: tuple[int, int, int, int], seed_text: str
) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    left, top, right, bottom = box
    cx, cy = (left + right) // 2, (top + bottom) // 2
    orbit_x = (right - left) * 38 // 100
    orbit_y = (bottom - top) * 38 // 100
    draw.ellipse(
        (cx - orbit_x, cy - orbit_y, cx + orbit_x, cy + orbit_y),
        outline=(75, 178, 230, 150),
        width=max(2, (right - left) // 500),
    )
    earth_radius = max(45, min(right - left, bottom - top) // 11)
    draw.ellipse(
        (
            cx - earth_radius,
            cy - earth_radius,
            cx + earth_radius,
            cy + earth_radius,
        ),
        fill=(35, 104, 192, 255),
        outline=(100, 205, 255, 255),
        width=max(3, earth_radius // 12),
    )
    draw.arc(
        (
            cx - earth_radius * 3 // 4,
            cy - earth_radius // 2,
            cx + earth_radius // 2,
            cy + earth_radius // 2,
        ),
        175,
        345,
        fill=(82, 190, 112, 255),
        width=max(5, earth_radius // 5),
    )
    moon_radius = max(22, earth_radius // 2)
    for index in range(8):
        angle = -math.pi / 2 + index * math.pi / 4
        mx = cx + round(math.cos(angle) * orbit_x)
        my = cy + round(math.sin(angle) * orbit_y)
        moon = _moon_disc(moon_radius, index / 8, f"{seed_text}|orbit-{index}")
        _paste_center(image, moon, mx, my)
    _draw_arrow(
        draw,
        (cx + orbit_x - 12, cy - 42),
        (cx + orbit_x, cy + 42),
        (*BRAND_MAGENTA, 230),
        max(3, (right - left) // 420),
    )


def _draw_eclipse(image: Image.Image, box: tuple[int, int, int, int]) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    left, top, right, bottom = box
    cy = (top + bottom) // 2
    width = right - left
    sun_x, moon_x, earth_x = left + width // 8, left + width // 2, right - width // 8
    sun_radius = max(60, width // 12)
    moon_radius = max(34, width // 26)
    earth_radius = max(46, width // 20)
    draw.ellipse(
        (sun_x - sun_radius, cy - sun_radius, sun_x + sun_radius, cy + sun_radius),
        fill=(255, 196, 55, 255),
    )
    draw.polygon(
        (
            (moon_x, cy - moon_radius),
            (earth_x + earth_radius * 2, cy - earth_radius // 2),
            (earth_x + earth_radius * 2, cy + earth_radius // 2),
            (moon_x, cy + moon_radius),
        ),
        fill=(4, 6, 16, 190),
    )
    draw.ellipse(
        (
            moon_x - moon_radius,
            cy - moon_radius,
            moon_x + moon_radius,
            cy + moon_radius,
        ),
        fill=(67, 70, 82, 255),
    )
    draw.ellipse(
        (
            earth_x - earth_radius,
            cy - earth_radius,
            earth_x + earth_radius,
            cy + earth_radius,
        ),
        fill=(35, 111, 198, 255),
        outline=(120, 215, 255, 255),
        width=3,
    )


def _draw_planet(
    image: Image.Image,
    box: tuple[int, int, int, int],
    seed_text: str,
    *,
    rings: bool,
) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    left, top, right, bottom = box
    cx, cy = (left + right) // 2, (top + bottom) // 2
    radius = min(right - left, bottom - top) * 3 // 10
    if rings:
        ring_box = (
            cx - radius * 8 // 5,
            cy - radius * 2 // 5,
            cx + radius * 8 // 5,
            cy + radius * 2 // 5,
        )
        draw.ellipse(ring_box, outline=(224, 190, 135, 180), width=max(8, radius // 12))
        draw.ellipse(ring_box, outline=(255, 227, 180, 150), width=max(2, radius // 45))
    planet = Image.new("RGBA", (radius * 2 + 2, radius * 2 + 2), (0, 0, 0, 0))
    planet_draw = ImageDraw.Draw(planet, "RGBA")
    rng = random.Random(_seed(seed_text))
    base = rng.choice(((182, 102, 68), (205, 166, 105), (63, 130, 188)))
    for local_y in range(radius * 2):
        relative = abs(local_y - radius) / radius
        shade = 1.0 - relative * 0.35
        color = tuple(round(channel * shade) for channel in base)
        half_width = round(math.sqrt(max(0, radius**2 - (local_y - radius) ** 2)))
        planet_draw.line(
            (radius - half_width, local_y, radius + half_width, local_y),
            fill=(*color, 255),
        )
    for _ in range(8):
        band_y = rng.randint(radius // 3, radius * 5 // 3)
        planet_draw.line(
            (radius // 5, band_y, radius * 9 // 5, band_y),
            fill=(255, 240, 220, 35),
            width=max(3, radius // 30),
        )
    _paste_center(image, planet, cx, cy)


def _draw_star(
    image: Image.Image, box: tuple[int, int, int, int], seed_text: str
) -> None:
    left, top, right, bottom = box
    cx, cy = (left + right) // 2, (top + bottom) // 2
    radius = min(right - left, bottom - top) // 5
    glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow, "RGBA")
    for scale, alpha in ((2.2, 18), (1.7, 28), (1.35, 55)):
        r = round(radius * scale)
        glow_draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 167, 44, alpha))
    glow = glow.filter(ImageFilter.GaussianBlur(max(18, radius // 3)))
    image.alpha_composite(glow)
    draw = ImageDraw.Draw(image, "RGBA")
    draw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        fill=(255, 205, 82, 255),
    )
    rng = random.Random(_seed(seed_text))
    for _ in range(25):
        x = rng.randint(cx - radius * 3 // 4, cx + radius * 3 // 4)
        y = rng.randint(cy - radius * 3 // 4, cy + radius * 3 // 4)
        if (x - cx) ** 2 + (y - cy) ** 2 <= (radius * 3 // 4) ** 2:
            draw.arc(
                (x - 18, y - 7, x + 18, y + 7),
                0,
                180,
                fill=(255, 130, 40, 130),
                width=3,
            )


def _draw_galaxy(
    image: Image.Image, box: tuple[int, int, int, int], seed_text: str
) -> None:
    left, top, right, bottom = box
    cx, cy = (left + right) // 2, (top + bottom) // 2
    rng = random.Random(_seed(seed_text))
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer, "RGBA")
    scale = min(right - left, bottom - top) * 0.36
    for arm in range(4):
        for step in range(240):
            angle = arm * math.pi / 2 + step * 0.055 + rng.uniform(-0.18, 0.18)
            radius = scale * (step / 240) ** 0.82
            x = cx + math.cos(angle) * radius * 1.35 + rng.uniform(-9, 9)
            y = cy + math.sin(angle) * radius * 0.55 + rng.uniform(-7, 7)
            size = rng.choice((1, 1, 2, 2, 3))
            color = rng.choice(
                ((130, 185, 255, 150), (255, 205, 225, 145), (255, 255, 220, 180))
            )
            draw.ellipse((x - size, y - size, x + size, y + size), fill=color)
    draw.ellipse((cx - 65, cy - 30, cx + 65, cy + 30), fill=(255, 238, 194, 220))
    blurred = layer.filter(ImageFilter.GaussianBlur(2))
    image.alpha_composite(blurred)
    image.alpha_composite(layer)


def _draw_telescope(image: Image.Image, box: tuple[int, int, int, int]) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    left, top, right, bottom = box
    width = right - left
    cx, cy = (left + right) // 2, (top + bottom) // 2
    tube_length = width * 36 // 100
    tube_height = max(45, width // 18)
    draw.rounded_rectangle(
        (
            cx - tube_length // 2,
            cy - tube_height,
            cx + tube_length // 2,
            cy,
        ),
        radius=tube_height // 3,
        fill=(58, 75, 108, 255),
        outline=(110, 210, 255, 230),
        width=4,
    )
    draw.ellipse(
        (
            cx + tube_length // 2 - tube_height // 2,
            cy - tube_height,
            cx + tube_length // 2 + tube_height // 2,
            cy,
        ),
        fill=(30, 45, 78, 255),
        outline=(39, 209, 255, 255),
        width=5,
    )
    pivot_y = cy + tube_height // 2
    draw.ellipse((cx - 20, pivot_y - 20, cx + 20, pivot_y + 20), fill=BRAND_MAGENTA)
    draw.line(
        (cx, pivot_y, cx - width // 8, bottom - 25), fill=(205, 215, 235, 230), width=8
    )
    draw.line(
        (cx, pivot_y, cx + width // 8, bottom - 25), fill=(205, 215, 235, 230), width=8
    )


def _draw_scale_or_timeline(
    image: Image.Image,
    box: tuple[int, int, int, int],
    *,
    timeline: bool,
) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    left, top, right, bottom = box
    cy = (top + bottom) // 2
    draw.line((left + 40, cy, right - 40, cy), fill=(*BRAND_CYAN, 200), width=6)
    count = 5 if timeline else 4
    label_font = _font(max(16, (right - left) // 70), bold=True)
    for index in range(count):
        x = left + 80 + index * (right - left - 160) // max(1, count - 1)
        radius = 17 + (index * 12 if not timeline else 0)
        draw.ellipse(
            (x - radius, cy - radius, x + radius, cy + radius), fill=BRAND_MAGENTA
        )
        label = f"{index + 1}"
        label_box = draw.textbbox((0, 0), label, font=label_font)
        draw.text(
            (x - (label_box[2] - label_box[0]) // 2, cy + radius + 15),
            label,
            font=label_font,
            fill=(225, 232, 248, 230),
        )


def make_science_visual(
    path: Path,
    *,
    brand: str,
    heading: str,
    visual_direction: str,
    visual_kind: str,
    width: int,
    height: int,
) -> str:
    resolved = resolve_visual_kind(heading, visual_direction, visual_kind)
    image = _starfield(width, height, f"{heading}|{visual_direction}").convert("RGBA")
    draw = ImageDraw.Draw(image, "RGBA")
    margin = round(width * 0.07)
    brand_font = _font(max(22, width // 48), bold=True)
    title_font = _font(max(38, width // 24), bold=True)
    draw.text((margin, round(height * 0.055)), brand, font=brand_font, fill=BRAND_CYAN)
    title_lines = _wrap(draw, heading, title_font, width - margin * 2)
    title_bottom = _draw_centered(
        draw,
        title_lines[:3],
        title_font,
        width // 2,
        round(height * 0.12),
        (255, 255, 255),
        max(8, height // 120),
    )
    box = (
        margin,
        title_bottom + round(height * 0.035),
        width - margin,
        height - round(height * 0.09),
    )
    draw.rounded_rectangle(
        box,
        radius=max(24, width // 50),
        fill=(2, 5, 18, 118),
        outline=(*BRAND_CYAN, 95),
        width=max(2, width // 700),
    )

    if resolved == "moon_light":
        _draw_moon_light(image, box, heading)
    elif resolved == "moon_phases":
        _draw_moon_phases(image, box, heading)
    elif resolved == "orbit":
        _draw_orbit(image, box, heading)
    elif resolved == "eclipse":
        _draw_eclipse(image, box)
    elif resolved in {"planet", "rings"}:
        _draw_planet(image, box, heading, rings=resolved == "rings")
    elif resolved == "star":
        _draw_star(image, box, heading)
    elif resolved == "telescope":
        _draw_telescope(image, box)
    elif resolved in {"scale", "timeline"}:
        _draw_scale_or_timeline(image, box, timeline=resolved == "timeline")
    else:
        _draw_galaxy(image, box, heading)

    footer_font = _font(max(13, width // 92))
    footer = "ILUSTRACIÓN ORIGINAL · ESQUEMA NO A ESCALA"
    footer_box = draw.textbbox((0, 0), footer, font=footer_font)
    draw.text(
        (
            width - margin - (footer_box[2] - footer_box[0]),
            height - round(height * 0.045),
        ),
        footer,
        font=footer_font,
        fill=(180, 193, 218, 180),
    )
    image.convert("RGB").save(path, format="PNG", optimize=True)
    return resolved
