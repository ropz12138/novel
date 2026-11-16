"""Select and initialize isolated development configuration without connecting to DB."""
import json
import os
from pathlib import Path


def runtime_config_path(root: Path, environment: str) -> Path:
    names = {"production": "config.json", "development": "config.dev.json"}
    if environment not in names:
        raise ValueError("NOVEL_ENV 必须为 production 或 development")
    return root / names[environment]


def load_runtime_config(root: Path, environment: str) -> tuple[Path, dict]:
    path = runtime_config_path(root, environment)
    data = json.loads(path.read_text(encoding="utf-8"))
    if environment == "development":
        production = json.loads((root / "config.json").read_text(encoding="utf-8"))
        if data["database"]["db_name"] == production["database"]["db_name"]:
            raise ValueError("开发数据库名称必须与生产数据库不同，请修改 config.dev.json")
        development_ports = {int(data["app"]["dev_port"]), int(data["frontend"]["dev_port"])}
        production_ports = {int(production["app"]["prod_port"]), int(production["frontend"]["prod_port"])}
        if len(development_ports) != 2 or development_ports & production_ports:
            raise ValueError("开发前后端端口必须各自独立，并与生产端口不同")
    return path, data


def prepare_development_config(root: Path) -> None:
    """Initialize once; subsequent launches preserve the user's development settings."""
    path = runtime_config_path(root, "development")
    if path.exists():
        return
    data = json.loads((root / "config.json").read_text(encoding="utf-8"))
    data["database"]["db_name"] += "_dev"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
        fp.write("\n")
