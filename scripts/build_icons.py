#!/usr/bin/env python3
from pathlib import Path

from PIL import Image, ImageDraw


def create_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, size - 2, size - 2), fill=(12, 34, 56, 255), outline=(94, 178, 255, 255), width=max(2, size // 24))
    shield = [
        (size * 0.50, size * 0.16),
        (size * 0.78, size * 0.28),
        (size * 0.72, size * 0.62),
        (size * 0.50, size * 0.84),
        (size * 0.28, size * 0.62),
        (size * 0.22, size * 0.28),
    ]
    d.polygon(shield, fill=(35, 150, 255, 255), outline=(200, 235, 255, 255))
    d.line(
        (size * 0.34, size * 0.52, size * 0.46, size * 0.64, size * 0.68, size * 0.38),
        fill=(240, 250, 255, 255),
        width=max(3, size // 18),
    )
    return img


def main() -> None:
    out = Path("assets")
    out.mkdir(parents=True, exist_ok=True)

    tray = create_icon(64)
    tray.save(out / "dvpn-tray.png")

    installer = create_icon(256)
    installer.save(out / "dvpn-installer.png")
    installer.save(out / "dvpn-installer.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

    print("Generated assets/dvpn-tray.png and assets/dvpn-installer.{png,ico}")


if __name__ == "__main__":
    main()
