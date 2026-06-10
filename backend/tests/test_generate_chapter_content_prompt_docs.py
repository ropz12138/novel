"""generate_chapter_content 提示词与工具描述应说明自动元数据同步。"""

from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parents[1] / "app" / "services" / "prompt_templates"


def test_chapter_agent_system_prompt_documents_auto_metadata_sync():
    text = (PROMPT_DIR / "chapter_agent_system.txt").read_text(encoding="utf-8")
    assert "generate_chapter_content" in text
    assert "自动同步" in text and "元数据" in text
    assert "sync_chapter_metadata" in text


def test_generate_chapter_content_tool_description_documents_auto_metadata_sync():
    from app.services.agent.chapter_tools import generate_chapter_content

    desc = generate_chapter_content.description or ""
    assert "自动保存" in desc
    assert "元数据" in desc
