"""写作 Agent 读取研究 Agent 产出的工具测试。"""
import importlib
import json

import database
from models.research import ResearchArtifact, ResearchJob
from models.user import User


rt = importlib.import_module("services.agents.tools.research_tools")


def _create_user(db, suffix: str) -> User:
    user = User(
        username=f"research-tool-{suffix}",
        email=f"research-tool-{suffix}@test.dev",
        password_hash="x",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _create_artifact(
    db,
    user: User,
    filename: str,
    artifact_type: str,
    title: str,
    content: str,
) -> tuple[ResearchJob, ResearchArtifact]:
    job = ResearchJob(
        user_id=user.id,
        original_filename=filename,
        status="completed",
        progress_current=100,
        progress_total=100,
        progress_unit="章",
        progress_detail="分析完成",
        completed=True,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    artifact = ResearchArtifact(
        job_id=job.id,
        artifact_type=artifact_type,
        title=title,
        content=content,
        metadata_text="{}",
    )
    db.add(artifact)
    db.commit()
    db.refresh(artifact)
    return job, artifact


def test_list_research_artifacts_only_returns_current_users_results(monkeypatch):
    db = database.SessionLocal()
    try:
        owner = _create_user(db, "owner")
        other = _create_user(db, "other")
        owner_job, owner_artifact = _create_artifact(
            db,
            owner,
            "参考小说.txt",
            "technique_card",
            "悬念递进",
            "通过信息差逐层释放悬念。",
        )
        _create_artifact(
            db,
            other,
            "其他小说.txt",
            "technique_card",
            "不可见成果",
            "不应返回给当前用户。",
        )
        monkeypatch.setattr(rt, "_get_current_user_id", lambda: owner.id)

        result = json.loads(rt._list_research_artifacts_sync(
            job_id=owner_job.id,
            artifact_type="technique_card",
            keyword="信息差",
        ))

        assert result["success"] is True
        assert result["total"] == 1
        assert result["artifacts"][0]["id"] == owner_artifact.id
        assert result["artifacts"][0]["source_filename"] == "参考小说.txt"
        assert "信息差" in result["artifacts"][0]["content_preview"]
    finally:
        db.close()


def test_read_research_artifacts_preserves_order_and_blocks_other_users(monkeypatch):
    db = database.SessionLocal()
    try:
        owner = _create_user(db, "read-owner")
        other = _create_user(db, "read-other")
        _, first = _create_artifact(
            db, owner, "甲.txt", "final_report", "甲报告", "甲内容"
        )
        _, second = _create_artifact(
            db, owner, "乙.txt", "technique_card", "乙卡片", "乙内容"
        )
        _, forbidden = _create_artifact(
            db, other, "丙.txt", "final_report", "丙报告", "不可读取"
        )
        monkeypatch.setattr(rt, "_get_current_user_id", lambda: owner.id)

        result = json.loads(rt._read_research_artifacts_sync(
            [second.id, forbidden.id, first.id],
        ))

        assert result["success"] is True
        assert [item["id"] for item in result["artifacts"]] == [
            second.id,
            first.id,
        ]
        assert forbidden.id in result["unavailable_artifact_ids"]
        assert all(item["content"] != "不可读取" for item in result["artifacts"])
    finally:
        db.close()


def test_research_tools_require_user_context(monkeypatch):
    monkeypatch.setattr(rt, "_get_current_user_id", lambda: None)

    listed = json.loads(rt._list_research_artifacts_sync())
    read = json.loads(rt._read_research_artifacts_sync(["missing"]))

    assert listed["success"] is False
    assert read["success"] is False
    assert "user_id" in listed["error"]
    assert "user_id" in read["error"]


def test_research_tools_are_registered():
    assert [tool.name for tool in rt.research_tools] == [
        "list_research_artifacts",
        "read_research_artifacts",
    ]
