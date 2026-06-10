"""测试 resume 时可更新 enable_todolist / enable_evaluation"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestSupervisorResumeRequestFlags:
    def test_resume_request_accepts_feature_flags(self):
        from app.schemas.supervisor_schema import SupervisorResumeRequest

        schema = SupervisorResumeRequest.model_json_schema()
        props = schema["properties"]
        assert "enable_todolist" in props
        assert "enable_evaluation" in props

    def test_resume_request_flags_default_none(self):
        from app.schemas.supervisor_schema import SupervisorResumeRequest

        req = SupervisorResumeRequest(session_id="s1", message="继续")
        assert req.enable_todolist is None
        assert req.enable_evaluation is None

    def test_resume_request_flags_can_be_set(self):
        from app.schemas.supervisor_schema import SupervisorResumeRequest

        req = SupervisorResumeRequest(
            session_id="s1",
            message="继续",
            enable_todolist=True,
            enable_evaluation=True,
        )
        assert req.enable_todolist is True
        assert req.enable_evaluation is True


class TestSupervisorSessionOutFeatureFlags:
    def test_session_out_includes_feature_flags(self):
        from app.schemas.session_schema import SupervisorSessionOut

        schema = SupervisorSessionOut.model_json_schema()
        props = schema["properties"]
        assert "enable_todolist" in props
        assert "enable_evaluation" in props


class TestSupervisorAgentResumeUpdatesFlags:
    @pytest.mark.asyncio
    async def test_resume_updates_session_flags_before_run_graph(self):
        from app.services.supervisor.supervisor_agent import SupervisorAgent

        mock_db = MagicMock()
        session = MagicMock()
        session.id = "sess-1"
        session.work_id = "w1"
        session.user_id = "u1"
        session.auto_mode = True
        session.enable_todolist = False
        session.enable_evaluation = False
        session.status = "idle"
        session.stage = "idle"

        mock_db.query.return_value.filter_by.return_value.first.return_value = session

        agent = SupervisorAgent(emit=MagicMock(), db=mock_db, work_id="w1", user_id="u1")

        with patch("app.services.supervisor.supervisor_agent.message_service") as mock_msg_svc:
            mock_msg_svc.get_next_sort_order.return_value = 1
            mock_msg_svc.create_message.return_value = None
            with patch.object(agent, "_run_graph", new_callable=AsyncMock) as mock_run:
                mock_run.return_value = {"ok": True}

                await agent.resume(
                    "sess-1",
                    "继续写",
                    enable_todolist=True,
                    enable_evaluation=True,
                )

        assert session.enable_todolist is True
        assert session.enable_evaluation is True
        mock_run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_resume_keeps_flags_when_not_provided(self):
        from app.services.supervisor.supervisor_agent import SupervisorAgent

        mock_db = MagicMock()
        session = MagicMock()
        session.id = "sess-1"
        session.work_id = "w1"
        session.user_id = "u1"
        session.auto_mode = True
        session.enable_todolist = True
        session.enable_evaluation = False
        session.status = "idle"
        session.stage = "idle"

        mock_db.query.return_value.filter_by.return_value.first.return_value = session

        agent = SupervisorAgent(emit=MagicMock(), db=mock_db, work_id="w1", user_id="u1")

        with patch("app.services.supervisor.supervisor_agent.message_service") as mock_msg_svc:
            mock_msg_svc.get_next_sort_order.return_value = 1
            mock_msg_svc.create_message.return_value = None
            with patch.object(agent, "_run_graph", new_callable=AsyncMock) as mock_run:
                mock_run.return_value = {"ok": True}

                await agent.resume("sess-1", "继续写")

        assert session.enable_todolist is True
        assert session.enable_evaluation is False
