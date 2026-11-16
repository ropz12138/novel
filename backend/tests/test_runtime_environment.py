"""Development startup must use a distinct config and database."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from runtime_environment import load_runtime_config, prepare_development_config


@pytest.fixture
def environment_root(tmp_path):
    config = json.loads((Path(__file__).resolve().parents[2] / "config.json.example").read_text())
    (tmp_path / "config.json").write_text(json.dumps(config))
    return tmp_path, config


def test_production_keeps_existing_config(environment_root):
    root, production = environment_root
    path, data = load_runtime_config(root, "production")
    assert path == root / "config.json"
    assert data == production


def test_development_requires_its_own_config(environment_root):
    root, _ = environment_root
    with pytest.raises(FileNotFoundError):
        load_runtime_config(root, "development")


def test_prepare_development_config_is_separate_private_and_idempotent(environment_root):
    root, production = environment_root
    original = (root / "config.json").read_bytes()
    prepare_development_config(root)
    path, data = load_runtime_config(root, "development")
    assert path == root / "config.dev.json"
    assert data["database"]["db_name"] == production["database"]["db_name"] + "_dev"
    assert path.stat().st_mode & 0o777 == 0o600
    assert (root / "config.json").read_bytes() == original
    data["app"]["name"] = "custom-dev"
    path.write_text(json.dumps(data))
    prepare_development_config(root)
    assert json.loads(path.read_text()) == data


def test_development_rejects_production_database_before_startup(environment_root):
    root, production = environment_root
    (root / "config.dev.json").write_text(json.dumps(production))
    with pytest.raises(ValueError, match="数据库"):
        load_runtime_config(root, "development")


@pytest.mark.parametrize("section,key", [("app", "dev_port"), ("frontend", "dev_port")])
def test_development_rejects_ports_used_by_production(environment_root, section, key):
    root, production = environment_root
    development = copy.deepcopy(production)
    development["database"]["db_name"] += "_dev"
    development[section][key] = production["app"]["prod_port"]
    (root / "config.dev.json").write_text(json.dumps(development))
    with pytest.raises(ValueError, match="端口"):
        load_runtime_config(root, "development")


def test_unknown_environment_is_rejected(environment_root):
    root, _ = environment_root
    with pytest.raises(ValueError, match="NOVEL_ENV"):
        load_runtime_config(root, "developmnt")


@pytest.mark.parametrize("environment,filename,suffix", [
    ("production", "config.json", ""),
    ("development", "config.dev.json", "_dev"),
])
def test_backend_process_selects_the_expected_configuration(environment_root, environment, filename, suffix):
    root, production = environment_root
    prepare_development_config(root)
    backend = root / "backend"
    backend.mkdir()
    source = Path(__file__).resolve().parents[1]
    for name in ("config.py", "runtime_environment.py"):
        shutil.copyfile(source / name, backend / name)
    check = (
        "from config import CONFIG_PATH, settings\n"
        f"assert CONFIG_PATH.name == {filename!r}\n"
        f"assert settings.environment == {environment!r}\n"
        f"assert settings.db_name == {production['database']['db_name'] + suffix!r}\n"
    )
    result = subprocess.run([sys.executable, "-c", check], cwd=backend,
                            env={**os.environ, "NOVEL_ENV": environment}, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("conflict", ["database", "port"])
def test_dev_launcher_validates_config_before_stopping_existing_processes(environment_root, conflict):
    root, production = environment_root
    development = copy.deepcopy(production)
    if conflict == "port":
        development["database"]["db_name"] += "_dev"
        development["app"]["dev_port"] = production["app"]["prod_port"]
    (root / "config.dev.json").write_text(json.dumps(development))
    source = Path(__file__).resolve().parents[2]
    for name in ("scripts/start_canvas_dev.sh", "scripts/prepare_canvas_dev.py", "backend/runtime_environment.py"):
        target = root / name
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(source / name, target)
    logs = root / "logs"
    logs.mkdir()
    pid = logs / "canvas-backend-dev.pid"
    pid.write_text("999999999")
    result = subprocess.run(["bash", str(root / "scripts/start_canvas_dev.sh")],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert ("数据库" if conflict == "database" else "端口") in result.stderr
    assert pid.read_text() == "999999999"
    assert not (root / "backend/.venv-dev").exists()
    assert not (root / "backend/.venv").exists()
