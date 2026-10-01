from pathlib import Path

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ICON = PROJECT_ROOT / "app_logo.png"
RES_DIR = PROJECT_ROOT / "frontend" / "android" / "app" / "src" / "main" / "res"
RESOURCES_ICON = PROJECT_ROOT / "frontend" / "resources" / "icon.png"

LAUNCHER_SIZES = {
    "mipmap-mdpi": 48,
    "mipmap-hdpi": 72,
    "mipmap-xhdpi": 96,
    "mipmap-xxhdpi": 144,
    "mipmap-xxxhdpi": 192,
}
FOREGROUND_SIZES = {
    "mipmap-mdpi": 108,
    "mipmap-hdpi": 162,
    "mipmap-xhdpi": 216,
    "mipmap-xxhdpi": 324,
    "mipmap-xxxhdpi": 432,
}


def resize_icon(source: Image.Image, size: int) -> Image.Image:
    return source.resize((size, size), Image.Resampling.LANCZOS)


def sample_background_hex(source: Image.Image) -> str:
    rgb = source.convert("RGB")
    pixel = rgb.getpixel((rgb.width // 4, rgb.height // 4))
    return "#{:02X}{:02X}{:02X}".format(*pixel)


def write_background_color(hex_color: str) -> None:
    color_file = RES_DIR / "values" / "ic_launcher_background.xml"
    color_file.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<resources>\n"
        f'    <color name="ic_launcher_background">{hex_color}</color>\n'
        "</resources>\n",
        encoding="utf-8",
    )


def main() -> None:
    if not SOURCE_ICON.is_file():
        raise FileNotFoundError(f"缺少 App 图标: {SOURCE_ICON}")
    source = Image.open(SOURCE_ICON).convert("RGBA")
    RESOURCES_ICON.parent.mkdir(parents=True, exist_ok=True)
    source.save(RESOURCES_ICON, format="PNG")
    write_background_color(sample_background_hex(source))
    for folder, size in LAUNCHER_SIZES.items():
        target_dir = RES_DIR / folder
        target_dir.mkdir(parents=True, exist_ok=True)
        icon = resize_icon(source, size)
        icon.save(target_dir / "ic_launcher.png", format="PNG")
        icon.save(target_dir / "ic_launcher_round.png", format="PNG")
    for folder, size in FOREGROUND_SIZES.items():
        target_dir = RES_DIR / folder
        target_dir.mkdir(parents=True, exist_ok=True)
        resize_icon(source, size).save(target_dir / "ic_launcher_foreground.png", format="PNG")


if __name__ == "__main__":
    main()
