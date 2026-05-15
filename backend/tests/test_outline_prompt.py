import sys
from pathlib import Path

sys.path.insert(0, "/root/Novel/backend")


PROMPT_PATH = Path("/root/Novel/backend/app/services/prompt_templates/work_generate_outline.txt")


def test_outline_generation_prompt_allows_flexible_counts():
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    forbidden_phrases = [
        "固定 3 个主线节点",
        "固定 2 个支线节点",
        "固定 2 个伏笔",
        "固定 3 个核心角色",
        "不要超过 3",
        "不要超过 2",
        "不要输出 80+ 章",
        "mainline",
    ]

    for phrase in forbidden_phrases:
        assert phrase not in prompt

    assert "数量由故事复杂度决定" in prompt
    assert "不设置固定数量上限" in prompt
    assert "development_node, summary, time_node" in prompt
