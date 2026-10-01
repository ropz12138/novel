#!/usr/bin/env python3
import json
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT_DIR / "config.json"
STRINGS_FILE = ROOT_DIR / "frontend/android/app/src/main/res/values/strings.xml"


def main() -> None:
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    app_name = config["app"]["mobile"]["app_name"]

    tree = ET.parse(STRINGS_FILE)
    resources = tree.getroot()
    values = {
        item.get("name"): item
        for item in resources.findall("string")
    }
    values["app_name"].text = app_name
    values["title_activity_main"].text = app_name
    ET.indent(tree, space="    ")
    tree.write(STRINGS_FILE, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    main()
