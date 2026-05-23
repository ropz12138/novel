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
        self.dev_port = config["app"]["dev_port"]
        self.prod_port = config["app"]["prod_port"]
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

        self._parse_llm_config(config)

        auth = config.get("auth", {})
        self.jwt_secret = auth.get("jwt_secret", "change-me-in-production")
        self.jwt_expire_hours = int(auth.get("jwt_expire_hours", 72))

        observability = config.get("observability", {})
        self.langsmith_api_key = observability.get("langsmith_api_key", "")
        self.langsmith_project = observability.get("langsmith_project", "")
        self.langsmith_endpoint = observability.get("langsmith_endpoint", "https://api.smith.langchain.com")
        self.langsmith_tracing_v2 = bool(observability.get("langsmith_tracing_v2", False))

    def _init_defaults(self) -> None:
        """初始化默认值（供测试中使用 __new__ 后手动调用）"""
        self.app_name = ""
        self.host = "0.0.0.0"
        self.dev_port = 9001
        self.prod_port = 9002
        self.debug = False
        self.db_host = "127.0.0.1"
        self.db_port = 5432
        self.db_user = ""
        self.db_password = ""
        self.db_name = ""
        self.db_echo = False
        self.db_pool_size = 10
        self.db_max_overflow = 20
        self.db_pool_timeout = 30
        self.db_pool_recycle = 1800
        self.langsmith_api_key = ""
        self.langsmith_project = ""
        self.langsmith_endpoint = ""
        self.langsmith_tracing_v2 = False
        self.jwt_secret = "change-me-in-production"
        self.jwt_expire_hours = 72

    def _parse_llm_config(self, config: dict) -> None:
        """解析多模型配置列表。

        config["llm"] 格式: [{ "model-name": { "base_url": "...", "api_key": "..." } }, ...]
        config["default_model"] 格式: "model-name"
        """
        llm_list = config.get("llm", [])
        self._models: dict[str, dict] = {}
        for item in llm_list:
            for model_name, model_conf in item.items():
                self._models[model_name] = {
                    "base_url": model_conf["base_url"],
                    "api_key": model_conf["api_key"],
                }

        self.default_model: str = config.get("default_model", "")
        if self.default_model and self.default_model not in self._models:
            raise ValueError(
                f"default_model '{self.default_model}' 在 llm 配置列表中未找到。"
                f"可用模型: {list(self._models.keys())}"
            )

    def get_model_config(self, model_name: str | None = None) -> dict:
        """获取指定模型的配置。

        Args:
            model_name: 模型名称，不传则使用 default_model。

        Returns:
            {"base_url": str, "api_key": str}

        Raises:
            KeyError: 模型名不存在
        """
        name = model_name or self.default_model
        if name not in self._models:
            raise KeyError(f"模型 '{name}' 未在配置中找到。可用模型: {list(self._models.keys())}")
        return self._models[name]

    @property
    def available_models(self) -> list[str]:
        """返回所有已配置的模型名称列表"""
        return list(self._models.keys())


settings = Settings()
