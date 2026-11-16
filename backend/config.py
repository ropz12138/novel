import os
from pathlib import Path

from runtime_environment import load_runtime_config, runtime_config_path

# config.py 位于 backend/config.py
# parents[0] = backend, parents[1] = Novel
PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENT = os.environ.get("NOVEL_ENV", "production")
CONFIG_PATH = runtime_config_path(PROJECT_ROOT, ENVIRONMENT)


class Settings:
    def __init__(self) -> None:
        _, config = load_runtime_config(PROJECT_ROOT, ENVIRONMENT)
        self.environment = ENVIRONMENT

        self.app_name = config["app"]["name"]
        self.host = config["app"]["host"]
        self.dev_port = config["app"]["dev_port"]
        self.prod_port = config["app"]["prod_port"]
        self.debug = config["app"]["debug"]

        mobile = config["app"]["mobile"]
        self.mobile_app_id = mobile["app_id"]
        self.mobile_app_name = mobile["app_name"]
        self.mobile_version_name = mobile["version_name"]
        self.mobile_version_code = int(mobile["version_code"])
        self.mobile_server_base_url = mobile["server_base_url"]
        self.mobile_api_base_url = mobile["api_base_url"]
        self.mobile_download_url = mobile["download_url"]
        self.mobile_apk_filename = mobile["apk_filename"]
        self.mobile_apk_publish_path = mobile["apk_publish_path"]
        self.mobile_android_build_variant = mobile["android_build_variant"]
        self.mobile_android_java_home = mobile["android_java_home"]
        self.mobile_android_sdk_root = mobile["android_sdk_root"]
        self.mobile_android_compile_sdk = int(mobile["android_compile_sdk"])

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

        self._parse_tts_config(config["tts"])

    def _parse_tts_config(self, tts: dict) -> None:
        self.tts_provider = tts["provider"]
        if self.tts_provider not in ("iflytek_xtts", "mimo_tts", "mimo_voicedesign"):
            raise ValueError("tts.provider must be iflytek_xtts, mimo_tts or mimo_voicedesign")
        profile = tts[self.tts_provider]
        if profile["audio_format"] != "pcm":
            raise ValueError(f"tts.{self.tts_provider}.audio_format must be pcm")
        if self.tts_provider in ("mimo_tts", "mimo_voicedesign"):
            if int(profile["sample_rate"]) != 24000:
                raise ValueError(f"tts.{self.tts_provider}.sample_rate must be 24000")
            self.tts_mimo_base_url = profile["base_url"]
            self.tts_mimo_api_key = profile["api_key"]
            self.tts_mimo_model = profile["model"]
            if self.tts_provider == "mimo_voicedesign":
                self.tts_voice_description = profile["voice_description"]
            else:
                self.tts_mimo_voice = profile["voice"]
                self.tts_style = profile["style"]
            self.tts_timeout_seconds = int(profile["timeout_seconds"])
            self.tts_sample_rate = 24000
            return
        if int(profile["sample_rate"]) != 16000:
            raise ValueError("tts.iflytek_xtts.sample_rate must be 16000")
        self.tts_sdk_dir = str((PROJECT_ROOT / profile["sdk_dir"]).resolve())
        self.tts_app_id = profile["app_id"]
        self.tts_api_key = profile["api_key"]
        self.tts_api_secret = profile["api_secret"]
        self.tts_vcn = profile["vcn"]
        self.tts_language = int(profile["language"])
        self.tts_sample_rate = 16000
        self.tts_worker_path = str(PROJECT_ROOT / "backend" / "native" / "xtts_worker")

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
                    "extra_headers": model_conf.get("extra_headers"),
                    "provider": model_conf.get("provider", "openai"),
                    "model": model_conf.get("model", model_name),
                    "model_type": model_conf.get("model_type", "llm"),
                    "enable_thinking": model_conf.get("enable_thinking"),
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
