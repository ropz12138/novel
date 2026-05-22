"""测试大纲相关所有 LLM 调用使用 pro 模型

验证 WorkService 中大纲生成流程的所有 LLM 实例均使用 deepseek-v4-pro 模型。
"""

from unittest.mock import MagicMock, call, patch

import pytest


class TestWorkServiceOutlineUsesProModel:
    """验证 WorkService 大纲相关 LLM 使用 deepseek-v4-pro"""

    def test_outline_llms_use_pro_model(self):
        """WorkService.__init__ 中所有 outline_ 开头的 LLM 应使用 pro 模型"""
        mock_settings = MagicMock()
        mock_settings.default_model = "deepseek-v4-flash"
        mock_settings.get_model_config = MagicMock()

        # get_model_config 需要为不同模型返回不同配置
        def mock_get_config(model_name=None):
            return {
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "api_key": "sk-test",
            }

        mock_settings.get_model_config.side_effect = mock_get_config

        with patch("app.services.work_service.settings", mock_settings):
            from app.services.work_service import WorkService
            ws = WorkService()

            # 验证 get_model_config 被调用时传入了 deepseek-v4-pro
            calls = mock_settings.get_model_config.call_args_list
            pro_calls = [c for c in calls if c == call("deepseek-v4-pro")]
            assert len(pro_calls) >= 1, (
                f"应至少调用一次 get_model_config('deepseek-v4-pro')，"
                f"实际调用: {calls}"
            )

    def test_chat_model_uses_default_model(self):
        """chat_model（非大纲用途）应继续使用默认模型"""
        mock_settings = MagicMock()
        mock_settings.default_model = "deepseek-v4-flash"

        def mock_get_config(model_name=None):
            return {
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "api_key": "sk-test",
            }

        mock_settings.get_model_config.side_effect = mock_get_config

        with patch("app.services.work_service.settings", mock_settings):
            from app.services.work_service import WorkService
            ws = WorkService()

            # chat_model 的 model_name 应该是 flash
            assert ws.chat_model.model_name == "deepseek-v4-flash"

    def test_outline_model_is_pro(self):
        """outline 相关的 base_model 的 model_name 应是 deepseek-v4-pro"""
        mock_settings = MagicMock()
        mock_settings.default_model = "deepseek-v4-flash"

        def mock_get_config(model_name=None):
            return {
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "api_key": "sk-test",
            }

        mock_settings.get_model_config.side_effect = mock_get_config

        with patch("app.services.work_service.settings", mock_settings):
            from app.services.work_service import WorkService
            ws = WorkService()

            # 验证 outline_tool_llm 绑定的底层模型是 pro
            # bind_tools 返回的是 RunnableBinding，底层模型通过 .bound 获取
            outline_llm = ws.outline_tool_llm
            # 追溯到底层 ChatOpenAI 实例
            bound = outline_llm
            while hasattr(bound, "bound"):
                bound = bound.bound
            assert bound.model_name == "deepseek-v4-pro", (
                f"outline_tool_llm 底层模型应为 deepseek-v4-pro，实际为 {bound.model_name}"
            )
