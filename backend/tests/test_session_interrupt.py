"""Supervisor 会话中断：标志复位、轮询检测、流式中止。"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, "/root/Novel/backend")


class TestSessionInterruptFlag:
    def test_is_session_interrupted_uses_fresh_sql_query(self):
        from app.services.supervisor.session_interrupt import is_session_interrupted

        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = True
        assert is_session_interrupted(mock_db, "sess-1") is True
        executed_sql = str(mock_db.execute.call_args[0][0])
        assert "supervisor_sessions" in executed_sql
        assert mock_db.execute.call_args[0][1] == {"sid": "sess-1"}

    @pytest.mark.asyncio
    async def test_resume_clears_interrupted_flag(self):
        from app.models.agent_model import SupervisorSession
        from app.services.supervisor.supervisor_agent import SupervisorAgent

        session = SupervisorSession(
            work_id="w1",
            user_id="u1",
            stage="interrupted",
            status="interrupted",
            interrupted=True,
        )
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = session

        agent = SupervisorAgent(emit=lambda e, d: None, db=mock_db, work_id="w1", user_id="u1")

        with patch.object(agent, "_run_graph", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = {"message": "ok"}
            await agent.resume("sess-1", "继续写")

        assert session.interrupted is False
        assert session.status == "running"


class TestStreamChainInterrupt:
    @pytest.mark.asyncio
    async def test_stream_chain_aborts_when_should_abort(self):
        from app.services.supervisor.session_interrupt import SessionInterruptedError
        from app.services.supervisor.sub_agent_base import stream_chain_with_reasoning

        async def fake_astream(_inputs):
            yield MagicMock(content="a", additional_kwargs={})
            yield MagicMock(content="b", additional_kwargs={})

        chain = MagicMock()
        chain.astream = fake_astream
        calls = {"n": 0}

        def should_abort():
            calls["n"] += 1
            return calls["n"] >= 2

        with pytest.raises(SessionInterruptedError):
            await stream_chain_with_reasoning(
                chain,
                {},
                lambda e, d: None,
                "write_stream",
                should_abort=should_abort,
            )
