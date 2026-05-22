"""测试多模型配置

验证：
1. config.json 中 llm 为列表结构，每个元素是 {模型名: {base_url, api_key}} 格式
2. config.json 中 default_model 为字符串，指向默认模型名
3. config.json 中包含 deepseek-v4-pro 模型
4. Settings 类能正确解析多模型配置
5. Settings.get_model_config() 能按模型名获取配置
6. Settings.get_model_config() 对默认模型有快捷访问
7. get_llm() 支持 model_name 参数，可指定非默认模型
8. 大纲 agent 使用 deepseek-v4-pro 模型
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.json"


# ────────────────────────── 1. config.json 结构测试 ──────────────────────────


class TestConfigStructure:
    """验证 config.json 的 llm 字段结构"""

    def test_llm_is_list(self):
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        assert isinstance(config["llm"], list), f"llm 应为列表，实际为 {type(config['llm'])}"

    def test_llm_list_not_empty(self):
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        assert len(config["llm"]) > 0, "llm 列表不应为空"

    def test_llm_elements_are_dicts_with_model_name_key(self):
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        for i, item in enumerate(config["llm"]):
            assert isinstance(item, dict), f"llm[{i}] 应为字典，实际为 {type(item)}"
            assert len(item) == 1, f"llm[{i}] 应只有一个 key（模型名），实际有 {len(item)} 个"
            model_name = list(item.keys())[0]
            model_config = item[model_name]
            assert "base_url" in model_config, f"llm[{i}].{model_name} 缺少 base_url"
            assert "api_key" in model_config, f"llm[{i}].{model_name} 缺少 api_key"

    def test_default_model_exists_and_is_string(self):
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        assert "default_model" in config, "config.json 缺少 default_model 字段"
        assert isinstance(config["default_model"], str), f"default_model 应为字符串，实际为 {type(config['default_model'])}"

    def test_default_model_refers_to_existing_entry(self):
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        default_name = config["default_model"]
        model_names = []
        for item in config["llm"]:
            model_names.extend(item.keys())
        assert default_name in model_names, (
            f"default_model '{default_name}' 在 llm 列表中找不到。可用模型: {model_names}"
        )

    def test_deepseek_v4_pro_exists(self):
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        model_names = []
        for item in config["llm"]:
            model_names.extend(item.keys())
        assert "deepseek-v4-pro" in model_names, (
            f"deepseek-v4-pro 不在 llm 列表中。可用模型: {model_names}"
        )

    def test_app_has_dev_port(self):
        """config.json 的 app 字段应包含 dev_port"""
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        assert "dev_port" in config["app"], "app 缺少 dev_port 字段"
        assert isinstance(config["app"]["dev_port"], int), "dev_port 应为整数"

    def test_app_has_prod_port(self):
        """config.json 的 app 字段应包含 prod_port"""
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        assert "prod_port" in config["app"], "app 缺少 prod_port 字段"
        assert isinstance(config["app"]["prod_port"], int), "prod_port 应为整数"

    def test_dev_port_and_prod_port_differ(self):
        """dev_port 和 prod_port 不能相同，避免端口冲突"""
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        assert config["app"]["dev_port"] != config["app"]["prod_port"], (
            f"dev_port ({config['app']['dev_port']}) 不应与 prod_port ({config['app']['prod_port']}) 相同"
        )

    def test_no_legacy_port_field(self):
        """config.json 的 app 字段不应再包含旧的 port 字段"""
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        assert "port" not in config["app"], (
            "app 中仍存在旧的 'port' 字段，应已迁移为 'dev_port' 和 'prod_port'"
        )


# ────────────────────────── 2. Settings 类解析测试 ──────────────────────────


class TestSettingsMultiModel:
    """验证 Settings 类能正确解析多模型配置"""

    @pytest.fixture()
    def mock_config(self):
        return {
            "app": {"name": "test", "host": "0.0.0.0", "dev_port": 9001, "prod_port": 9002, "debug": False},
            "database": {
                "host": "127.0.0.1", "port": 5432, "user": "pg",
                "password": "pw", "db_name": "test",
            },
            "llm": [
                {
                    "model-a": {
                        "base_url": "https://api-a.example.com/v1",
                        "api_key": "sk-aaa",
                    },
                },
                {
                    "model-b": {
                        "base_url": "https://api-b.example.com/v1",
                        "api_key": "sk-bbb",
                    },
                },
            ],
            "default_model": "model-a",
            "observability": {},
        }

    def test_settings_loads_default_model(self, mock_config):
        with patch("app.core.config.CONFIG_PATH") as mock_path:
            mock_path.open.return_value.__enter__ = lambda s: s
            mock_path.open.return_value.__exit__ = lambda s, *a: None
            mock_path.open.return_value.read.return_value = json.dumps(mock_config)
            mock_path.resolve.return_value = mock_path

            # 直接用 mock 数据构建 Settings
            from app.core.config import Settings
            s = Settings.__new__(Settings)
            s.__dict__.update({})
            config = mock_config

            s.app_name = config["app"]["name"]
            s.host = config["app"]["host"]
            s.dev_port = config["app"]["dev_port"]
            s.prod_port = config["app"]["prod_port"]
            s.debug = config["app"]["debug"]
            s.db_host = config["database"]["host"]
            s.db_port = config["database"]["port"]
            s.db_user = config["database"]["user"]
            s.db_password = config["database"]["password"]
            s.db_name = config["database"]["db_name"]
            s.db_echo = False
            s.db_pool_size = 10
            s.db_max_overflow = 20
            s.db_pool_timeout = 30
            s.db_pool_recycle = 1800

            s._parse_llm_config(config)
            s.langsmith_api_key = ""
            s.langsmith_project = ""
            s.langsmith_endpoint = ""
            s.langsmith_tracing_v2 = False

    def test_get_model_config_returns_correct_config(self, mock_config):
        """get_model_config 应返回指定模型的配置"""
        from app.core.config import Settings

        s = Settings.__new__(Settings)
        s._init_defaults()
        config = mock_config
        s._parse_llm_config(config)

        result = s.get_model_config("model-a")
        assert result["base_url"] == "https://api-a.example.com/v1"
        assert result["api_key"] == "sk-aaa"

        result_b = s.get_model_config("model-b")
        assert result_b["base_url"] == "https://api-b.example.com/v1"
        assert result_b["api_key"] == "sk-bbb"

    def test_get_model_config_default_returns_default_model(self, mock_config):
        """get_model_config() 不传参应返回默认模型配置"""
        from app.core.config import Settings

        s = Settings.__new__(Settings)
        s._init_defaults()
        s._parse_llm_config(config=mock_config)

        result = s.get_model_config()
        assert result["base_url"] == "https://api-a.example.com/v1"
        assert result["api_key"] == "sk-aaa"

    def test_get_model_config_raises_on_unknown_model(self, mock_config):
        """get_model_config 对不存在的模型应抛出 KeyError"""
        from app.core.config import Settings

        s = Settings.__new__(Settings)
        s._init_defaults()
        s._parse_llm_config(config=mock_config)

        with pytest.raises(KeyError):
            s.get_model_config("nonexistent-model")

    def test_default_model_property(self, mock_config):
        """default_model 属性应返回默认模型名"""
        from app.core.config import Settings

        s = Settings.__new__(Settings)
        s._init_defaults()
        s._parse_llm_config(config=mock_config)

        assert s.default_model == "model-a"

    def test_available_models(self, mock_config):
        """应能列出所有可用模型名"""
        from app.core.config import Settings

        s = Settings.__new__(Settings)
        s._init_defaults()
        s._parse_llm_config(config=mock_config)

        models = s.available_models
        assert "model-a" in models
        assert "model-b" in models
        assert len(models) == 2


# ────────────────────────── 3. 调用点测试 ──────────────────────────


class TestCallSitesUseNewInterface:
    """验证所有调用点使用 settings.get_model_config() 新接口"""

    def test_sub_agent_base_get_llm_uses_new_interface(self):
        """get_llm 应使用 get_model_config() 获取模型配置"""
        from app.services.supervisor.sub_agent_base import get_llm

        mock_settings = MagicMock()
        mock_settings.default_model = "test-model"
        mock_settings.get_model_config.return_value = {
            "base_url": "https://test.example.com/v1",
            "api_key": "sk-test",
        }
        with patch("app.services.supervisor.sub_agent_base.settings", mock_settings):
            llm = get_llm()
            mock_settings.get_model_config.assert_called_once_with(None)
            assert llm.model_name == "test-model"

    def test_get_llm_with_model_name_uses_specified_model(self):
        """get_llm(model_name='x') 应使用指定模型而非默认模型"""
        from app.services.supervisor.sub_agent_base import get_llm

        mock_settings = MagicMock()
        mock_settings.default_model = "flash-model"
        mock_settings.get_model_config.return_value = {
            "base_url": "https://pro.example.com/v1",
            "api_key": "sk-pro",
        }
        with patch("app.services.supervisor.sub_agent_base.settings", mock_settings):
            llm = get_llm(model_name="pro-model")
            mock_settings.get_model_config.assert_called_once_with("pro-model")
            assert llm.model_name == "pro-model"

    def test_nodes_get_llm_uses_new_interface(self):
        """nodes._get_llm 应使用 get_model_config() 获取模型配置"""
        mock_settings = MagicMock()
        mock_settings.get_model_config.return_value = {
            "base_url": "https://test.example.com/v1",
            "api_key": "sk-test",
        }
        mock_settings.default_model = "test-model"

        with patch("app.services.agent.nodes.settings", mock_settings):
            from app.services.agent.nodes import _get_llm

            _get_llm()
            mock_settings.get_model_config.assert_called_once()


class TestOutlineAgentUsesProModel:
    """验证大纲 agent 使用 deepseek-v4-pro 模型"""

    def test_outline_agent_build_graph_uses_pro_model(self):
        """OutlineAgent._build_graph 应使用 deepseek-v4-pro 模型"""
        from app.services.supervisor.outline_agent import OutlineAgent

        agent = OutlineAgent(emit=lambda e, d: None)

        with patch("app.services.supervisor.outline_agent.get_llm") as mock_get_llm:
            mock_get_llm.return_value = MagicMock()
            mock_get_llm.return_value.bind_tools.return_value = MagicMock()

            agent._build_graph(auto_mode=True)

            mock_get_llm.assert_called_once_with(
                temperature=0.7,
                model_name="deepseek-v4-pro",
            )
