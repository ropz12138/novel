import json
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config.json"
GRADLE_PATH = PROJECT_ROOT / "frontend" / "android" / "app" / "build.gradle"


def main() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    mobile = config["app"]["mobile"]
    gradle = GRADLE_PATH.read_text(encoding="utf-8")
    gradle, code_count = re.subn(
        r"versionCode\s+\d+",
        f'versionCode {int(mobile["version_code"])}',
        gradle,
        count=1,
    )
    gradle, name_count = re.subn(
        r'versionName\s+"[^"]+"',
        f'versionName "{mobile["version_name"]}"',
        gradle,
        count=1,
    )
    if code_count != 1 or name_count != 1:
        raise RuntimeError("无法在 Android build.gradle 中定位版本配置")
    GRADLE_PATH.write_text(gradle, encoding="utf-8")


if __name__ == "__main__":
    main()
