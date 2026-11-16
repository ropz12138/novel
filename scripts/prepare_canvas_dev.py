"""Initialize and validate dev configuration before touching any running service."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from runtime_environment import load_runtime_config, prepare_development_config


if __name__ == "__main__":
    prepare_development_config(ROOT)
    _, config = load_runtime_config(ROOT, "development")
    print(config["app"]["dev_port"])
    print(config["frontend"]["dev_port"])
