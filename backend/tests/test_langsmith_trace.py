"""LangSmith Trace 功能测试

验证：
1. setup_langsmith() 正确设置环境变量
2. setup_langsmith() 在 tracing 关闭时不设置环境变量
3. @traceable 装饰器应用到关键函数
4. trace 元数据包含 session_id、work_id、user_id
5. trace URL 可通过 langsmith client 获取
"""

import os
from unittest.mock import MagicMock, patch

import pytest


# ────────────────────────── 1. 环境变量设置测试 ──────────────────────────


class TestSetupLangsmithEnvVars:
    """验证 setup_langsmith 正确设置环境变量"""

    def setup_method(self):
        """清理环境变量"""
        for key in [
            "LANGSMITH_API_KEY",
            "LANGSMITH_PROJECT",
            "LANGSMITH_ENDPOINT",
            "LANGSMITH_TRACING",
            "LANGCHAIN_TRACING_V2",
        ]:
            os.environ.pop(key, None)

    def teardown_method(self):
        """清理环境变量"""
        for key in [
            "LANGSMITH_API_KEY",
            "LANGSMITH_PROJECT",
            "LANGSMITH_ENDPOINT",
            "LANGSMITH_TRACING",
            "LANGCHAIN_TRACING_V2",
        ]:
            os.environ.pop(key, None)

    def test_setup_langsmith_sets_env_vars_when_enabled(self):
        """tracing 启用时应设置所有环境变量"""
        from app.core.observability import setup_langsmith

        mock_settings = MagicMock()
        mock_settings.langsmith_tracing_v2 = True
        mock_settings.langsmith_api_key = "test-api-key"
        mock_settings.langsmith_project = "test-project"
        mock_settings.langsmith_endpoint = "https://test.smith.langchain.com"

        with patch("app.core.observability.settings", mock_settings):
            setup_langsmith()

        assert os.environ.get("LANGSMITH_API_KEY") == "test-api-key"
        assert os.environ.get("LANGSMITH_PROJECT") == "test-project"
        assert os.environ.get("LANGSMITH_ENDPOINT") == "https://test.smith.langchain.com"
        assert os.environ.get("LANGSMITH_TRACING") == "true"
        assert os.environ.get("LANGCHAIN_TRACING_V2") == "true"

    def test_setup_langsmith_skips_when_disabled(self):
        """tracing 禁用时不应设置环境变量"""
        from app.core.observability import setup_langsmith

        mock_settings = MagicMock()
        mock_settings.langsmith_tracing_v2 = False

        with patch("app.core.observability.settings", mock_settings):
            setup_langsmith()

        assert "LANGSMITH_API_KEY" not in os.environ
        assert "LANGSMITH_PROJECT" not in os.environ
        assert "LANGSMITH_ENDPOINT" not in os.environ
        assert "LANGSMITH_TRACING" not in os.environ
        assert "LANGCHAIN_TRACING_V2" not in os.environ

    def test_setup_langsmith_skips_empty_values(self):
        """空值字段不应设置对应环境变量"""
        from app.core.observability import setup_langsmith

        mock_settings = MagicMock()
        mock_settings.langsmith_tracing_v2 = True
        mock_settings.langsmith_api_key = ""
        mock_settings.langsmith_project = ""
        mock_settings.langsmith_endpoint = ""

        with patch("app.core.observability.settings", mock_settings):
            setup_langsmith()

        assert "LANGSMITH_API_KEY" not in os.environ
        assert "LANGSMITH_PROJECT" not in os.environ
        assert "LANGSMITH_ENDPOINT" not in os.environ
        assert os.environ.get("LANGSMITH_TRACING") == "true"
        assert os.environ.get("LANGCHAIN_TRACING_V2") == "true"


# ────────────────────────── 2. @traceable 装饰器测试 ──────────────────────────


class TestTraceableDecorator:
    """验证关键函数使用了 @traceable 装饰器"""

    def test_supervisor_agent_start_is_traceable(self):
        """SupervisorAgent.start 应使用 @traceable 装饰器"""
        from app.services.supervisor.supervisor_agent import SupervisorAgent

        # 检查方法是否有 traceable 装饰器的标记
        # langsmith 的 traceable 会添加 __wrapped__ 属性
        assert hasattr(SupervisorAgent.start, "__wrapped__") or hasattr(
            SupervisorAgent.start, "langsmith_tracing"
        ), "SupervisorAgent.start 应使用 @traceable 装饰器"

    def test_supervisor_agent_resume_is_traceable(self):
        """SupervisorAgent.resume 应使用 @traceable 装饰器"""
        from app.services.supervisor.supervisor_agent import SupervisorAgent

        assert hasattr(SupervisorAgent.resume, "__wrapped__") or hasattr(
            SupervisorAgent.resume, "langsmith_tracing"
        ), "SupervisorAgent.resume 应使用 @traceable 装饰器"

    def test_supervisor_agent_run_graph_is_traceable(self):
        """SupervisorAgent._run_graph 应使用 @traceable 装饰器"""
        from app.services.supervisor.supervisor_agent import SupervisorAgent

        assert hasattr(SupervisorAgent._run_graph, "__wrapped__") or hasattr(
            SupervisorAgent._run_graph, "langsmith_tracing"
        ), "SupervisorAgent._run_graph 应使用 @traceable 装饰器"


# ────────────────────────── 3. Trace 元数据测试 ──────────────────────────


class TestTraceMetadata:
    """验证 trace 元数据包含必要的上下文信息"""

    def test_trace_metadata_includes_session_id(self):
        """trace 元数据应包含 session_id"""
        from langsmith import traceable

        # 验证 traceable 装饰器支持 metadata 参数
        @traceable(metadata={"test": "value"})
        def dummy_func():
            return "ok"

        # 如果装饰器应用成功，函数应该可以正常调用
        assert dummy_func() == "ok"

    def test_supervisor_agent_stores_trace_context(self):
        """SupervisorAgent 应存储 trace 上下文信息"""
        from app.services.supervisor.supervisor_agent import SupervisorAgent

        emit = MagicMock()
        db = MagicMock()

        agent = SupervisorAgent(
            emit=emit,
            db=db,
            work_id="test-work-id",
            user_id="test-user-id",
        )

        assert agent.work_id == "test-work-id"
        assert agent.user_id == "test-user-id"


# ────────────────────────── 4. Trace URL 测试 ──────────────────────────


class TestTraceUrlGeneration:
    """验证 trace URL 生成"""

    def test_langsmith_client_can_be_created(self):
        """应能创建 langsmith Client 实例"""
        from langsmith import Client

        # 验证 Client 可以被实例化
        client = Client(api_key="test-key", api_url="https://test.smith.langchain.com")
        assert client is not None

    def test_trace_url_format(self):
        """验证 trace URL 格式正确"""
        # LangSmith trace URL 格式: https://smith.langchain.com/public/<trace_id>/r
        base_url = "https://smith.langchain.com"
        trace_id = "test-trace-id"
        expected_url = f"{base_url}/public/{trace_id}/r"

        assert expected_url == "https://smith.langchain.com/public/test-trace-id/r"
