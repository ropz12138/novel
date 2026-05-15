import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = PROJECT_ROOT / "config.json"


class Settings:
    def __init__(self) -> None:
        with CONFIG_PATH.open("r", encoding="utf-8") as fp:
            config = json.load(fp)

        self.app_name = config["app"]["name"]
        self.host = config["app"]["host"]
        self.port = config["app"]["port"]
        self.debug = config["app"]["debug"]

        self.db_host = config["database"]["host"]
        self.db_port = config["database"]["port"]
        self.db_user = config["database"]["user"]
        self.db_password = config["database"]["password"]
        self.db_name = config["database"]["db_name"]
        self.db_echo = bool(config["database"].get("echo", False))
        self.db_pool_size = int(config["database"].get("pool_size", 10))
        self.db_max_overflow = int(config["database"].get("max_overflow", 20))
        self.db_pool_timeout = int(config["database"].get("pool_timeout", 30))
        self.db_pool_recycle = int(config["database"].get("pool_recycle", 1800))

        self.llm_base_url = config["llm"]["base_url"]
        self.llm_api_key = config["llm"]["api_key"]
        self.llm_model = config["llm"]["model"]

        observability = config.get("observability", {})
        self.langsmith_api_key = observability.get("langsmith_api_key", "")
        self.langsmith_project = observability.get("langsmith_project", "")
        self.langsmith_endpoint = observability.get("langsmith_endpoint", "https://api.smith.langchain.com")
        self.langsmith_tracing_v2 = bool(observability.get("langsmith_tracing_v2", False))


settings = Settings()
