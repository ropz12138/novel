import sys

sys.path.insert(0, "/root/Novel/backend")

from app.services.work_service import WorkService


def test_normalize_timeline_uses_summary_and_drops_mainline_flag():
    result = WorkService._normalize_outline_result({
        "story": {"title": "测试", "genre": "玄幻", "volume": "第一卷"},
        "timeline": [{
            "id": "N1",
            "order": 1,
            "development_node": "开端",
            "summary": "主角卷入核心冲突",
            "time_node": "初期",
            "chapter_start": 1,
            "chapter_end": 10,
            "mainline": True,
        }],
        "branches": [],
        "foreshadowing": [],
        "characters": [],
    })

    node = result["timeline"][0]
    assert node["development_node"] == "开端"
    assert node["summary"] == "主角卷入核心冲突"
    assert "mainline" not in node


def test_normalize_timeline_uses_text_mainline_as_legacy_summary():
    result = WorkService._normalize_outline_result({
        "story": {"title": "测试", "genre": "玄幻", "volume": "第一卷"},
        "timeline": [{
            "id": "N1",
            "order": 1,
            "development_node": "开端",
            "mainline": "旧数据里的主线正文",
            "time_node": "初期",
            "chapter_start": 1,
            "chapter_end": 10,
        }],
        "branches": [],
        "foreshadowing": [],
        "characters": [],
    })

    assert result["timeline"][0]["summary"] == "旧数据里的主线正文"


def test_apply_operations_preserves_outline_extra_keys():
    outline = {
        "story": {"title": "测试"},
        "timeline": [],
        "branches": [],
        "foreshadowing": [],
        "characters": [{"name": "主角"}],
    }

    updated = WorkService._apply_operations(outline, [{
        "tool": "add_timeline_node",
        "args": {
            "order": 1,
            "development_node": "开端",
            "summary": "主角发现异常",
            "time_node": "初期",
            "chapter_start": 1,
            "chapter_end": 10,
        },
    }])

    assert updated["characters"] == [{"name": "主角"}]
    assert updated["timeline"][0]["summary"] == "主角发现异常"
