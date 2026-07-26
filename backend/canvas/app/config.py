import json
from pathlib import Path

# config.py 位于 backend/canvas/app/config.py
# parents[0] = app, parents[1] = canvas, parents[2] = backend, parents[3] = Novel
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

        self.frontend_dev_port = config["frontend"]["dev_port"]
        self.frontend_prod_port = config["frontend"]["prod_port"]

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

        image = config.get("image", {})
        self.image_provider = image.get("provider", "ark")
        self.image_api_base_url = image.get("api_base_url", "https://ark.cn-beijing.volces.com/api/v3")
        self.image_api_key = image.get("api_key", "")
        self.image_text2image_model = image.get("text2image_model", "")
        self.chapter_illustration_size = image.get("chapter_illustration_size", "2K")
        self.image_watermark = bool(image.get("watermark", True))

    def _parse_llm_config(self, config: dict) -> None:
        """解析多模型配置列表"""
        llm_list = config.get("llm", [])
        self._models: dict[str, dict] = {}
        for item in llm_list:
            for model_name, model_conf in item.items():
                self._models[model_name] = {
                    "base_url": model_conf["base_url"],
                    "api_key": model_conf["api_key"],
                    "max_completed_token": model_conf.get("max_completed_token"),
                    "context_window": model_conf.get("context_window") or model_conf.get("max_context_tokens") or model_conf.get("max_completed_token"),
                    "extra_body": model_conf.get("extra_body"),
                }

        self.default_model: str = config.get("default_model", "")
        if self.default_model and self.default_model not in self._models:
            raise ValueError(
                f"default_model '{self.default_model}' 在 llm 配置列表中未找到。"
                f"可用模型: {list(self._models.keys())}"
            )

        self.fallback_model: str = config.get("fallback_model", "")
        if self.fallback_model and self.fallback_model not in self._models:
            raise ValueError(
                f"fallback_model '{self.fallback_model}' 在 llm 配置列表中未找到。"
                f"可用模型: {list(self._models.keys())}"
            )

    def get_model_config(self, model_name: str | None = None) -> dict:
        """获取指定模型的配置"""
        name = model_name or self.default_model
        if name not in self._models:
            raise KeyError(f"模型 '{name}' 未在配置中找到。可用模型: {list(self._models.keys())}")
        return self._models[name]

    def get_model_context_window(self, model_name: str | None = None) -> int | None:
        """返回模型上下文上限 token 数；支持配置值如 128k / 512k。"""
        raw = self.get_model_config(model_name).get("context_window")
        if raw is None or raw == "":
            return None
        if isinstance(raw, int):
            return raw
        text = str(raw).strip().lower()
        multiplier = 1
        if text.endswith("k"):
            multiplier = 1000
            text = text[:-1]
        elif text.endswith("m"):
            multiplier = 1000 * 1000
            text = text[:-1]
        try:
            return int(float(text) * multiplier)
        except ValueError:
            return None

    @property
    def available_models(self) -> list[str]:
        """返回所有已配置的模型名称列表"""
        return list(self._models.keys())


settings = Settings()
