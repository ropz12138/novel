def test_sub_agent_report_renders_summary():
    from app.services.supervisor.sub_agent_report import SubAgentReport
    from app.services.supervisor.todo_harness import _report_digest

    report = SubAgentReport(
        status="completed",
        summary="章节编辑完成。",
        actions=["删除开篇呓语", "修正玉佩描写"],
        artifacts=["第1章正文"],
    )

    rendered = _report_digest({"report": report.model_dump()})

    assert "子 Agent 汇报" in rendered
    assert "章节编辑完成" in rendered
    assert "删除开篇呓语" in rendered
    assert "第1章正文" in rendered


def test_dispatch_result_message_still_prefers_message():
    from app.services.supervisor.todo_harness import _dispatch_result_message

    message = _dispatch_result_message(
        {"ok": True, "status": "completed", "message": "任务完成", "report": {"summary": "摘要"}},
        None,
    )

    assert message == "任务完成"
