"""测试 _normalize_outline_result 对非 dict 元素的容错处理

验证：
1. timeline 数组中混入字符串时，不报错，将字符串转为兜底 dict
2. branches 数组中混入字符串时，不报错
3. foreshadowing 数组中混入字符串时，不报错
4. characters 数组中混入字符串时，不报错
5. 混入 None / int 等其他类型时跳过
"""

import sys

sys.path.insert(0, "/root/Novel/backend")

from app.services.work_service import WorkService


def test_normalize_timeline_with_string_element():
    """timeline 中混入纯字符串元素时，应转为兜底 dict 而非抛 AttributeError"""
    result = WorkService._normalize_outline_result({
        "story": {"title": "测试", "genre": "玄幻", "volume": "第一卷"},
        "timeline": [
            "这是一段纯文本时间线节点",
            {
                "id": "N2",
                "order": 2,
                "development_node": "发展",
                "summary": "故事展开",
                "time_node": "中期",
                "chapter_start": 11,
                "chapter_end": 20,
            },
        ],
        "branches": [],
        "foreshadowing": [],
        "characters": [],
    })

    assert len(result["timeline"]) == 2
    # 字符串元素应被转为兜底 dict，content 保留原文
    assert result["timeline"][0]["summary"] == "这是一段纯文本时间线节点"
    # 正常 dict 元素不受影响
    assert result["timeline"][1]["development_node"] == "发展"


def test_normalize_timeline_with_only_strings():
    """timeline 全是字符串时，应全部转为兜底 dict"""
    result = WorkService._normalize_outline_result({
        "story": {"title": "测试", "genre": "玄幻", "volume": "第一卷"},
        "timeline": ["阶段一", "阶段二"],
        "branches": [],
        "foreshadowing": [],
        "characters": [],
    })

    assert len(result["timeline"]) == 2
    assert result["timeline"][0]["summary"] == "阶段一"
    assert result["timeline"][1]["summary"] == "阶段二"


def test_normalize_branches_with_string_element():
    """branches 中混入字符串时，应转为兜底 dict"""
    result = WorkService._normalize_outline_result({
        "story": {"title": "测试", "genre": "玄幻", "volume": "第一卷"},
        "timeline": [],
        "branches": [
            "支线剧情描述",
            {"id": "B1", "name": "副线", "attach_to": "N1", "summary": "副线展开"},
        ],
        "foreshadowing": [],
        "characters": [],
    })

    assert len(result["branches"]) == 2
    assert result["branches"][0]["summary"] == "支线剧情描述"
    assert result["branches"][1]["name"] == "副线"


def test_normalize_foreshadowing_with_string_element():
    """foreshadowing 中混入字符串时，应转为兜底 dict"""
    result = WorkService._normalize_outline_result({
        "story": {"title": "测试", "genre": "玄幻", "volume": "第一卷"},
        "timeline": [],
        "branches": [],
        "foreshadowing": [
            "神秘伏笔",
            {"id": "F1", "content": "已结构化的伏笔", "plant_node": "N1", "payoff_node": "N5"},
        ],
        "characters": [],
    })

    assert len(result["foreshadowing"]) == 2
    assert result["foreshadowing"][0]["content"] == "神秘伏笔"
    assert result["foreshadowing"][1]["content"] == "已结构化的伏笔"


def test_normalize_characters_with_string_element():
    """characters 中混入字符串时，应转为兜底 dict"""
    result = WorkService._normalize_outline_result({
        "story": {"title": "测试", "genre": "玄幻", "volume": "第一卷"},
        "timeline": [],
        "branches": [],
        "foreshadowing": [],
        "characters": [
            "嬴XX，男主",
            {"name": "女主", "role_type": "主角", "gender": "女"},
        ],
    })

    assert len(result["characters"]) == 2
    # 字符串元素应被兜底处理，name 使用兜底值
    assert result["characters"][0]["name"] == "未知角色"
    # 原始文本保存在 background 中
    assert result["characters"][0]["background"] == "嬴XX，男主"
    # 正常 dict 元素不受影响
    assert result["characters"][1]["name"] == "女主"


def test_normalize_skips_non_string_non_dict():
    """非 dict、非字符串元素（None、int）应被跳过"""
    result = WorkService._normalize_outline_result({
        "story": {"title": "测试", "genre": "玄幻", "volume": "第一卷"},
        "timeline": [None, 42, {"id": "N1", "summary": "正常"}],
        "branches": [None],
        "foreshadowing": [123],
        "characters": [None, {"name": "正常角色"}],
    })

    assert len(result["timeline"]) == 1
    assert result["timeline"][0]["summary"] == "正常"
    assert len(result["branches"]) == 0
    assert len(result["foreshadowing"]) == 0
    assert len(result["characters"]) == 1
    assert result["characters"][0]["name"] == "正常角色"


def test_normalize_empty_string_skipped():
    """空字符串元素应被跳过"""
    result = WorkService._normalize_outline_result({
        "story": {"title": "测试", "genre": "玄幻", "volume": "第一卷"},
        "timeline": ["", "  ", {"id": "N1", "summary": "正常"}],
        "branches": [],
        "foreshadowing": [],
        "characters": [],
    })

    assert len(result["timeline"]) == 1
    assert result["timeline"][0]["summary"] == "正常"


def test_normalize_coerces_loose_integer_fields():
    """LLM 返回 order_3 / 第12章 等字符串数字字段时，应归一化为 int。"""
    result = WorkService._normalize_outline_result({
        "story": {"title": "测试", "genre": "末日", "volume": "第一卷"},
        "timeline": [
            {
                "id": "N3",
                "order": "order_3",
                "summary": "正常",
                "chapter_start": "第21章",
                "chapter_end": "chapter_30",
            }
        ],
        "branches": [
            {
                "id": "B1",
                "name": "支线",
                "chapter_start": "side_4",
                "chapter_end": "第6章",
                "summary": "支线",
            }
        ],
        "foreshadowing": [],
        "characters": [{"name": "角色", "first_appearance_stage": "M2"}],
    })

    assert result["timeline"][0]["order"] == 3
    assert result["timeline"][0]["chapter_start"] == 21
    assert result["timeline"][0]["chapter_end"] == 30
    assert result["branches"][0]["chapter_start"] == 4
    assert result["branches"][0]["chapter_end"] == 6
    assert result["characters"][0]["first_appearance_stage"] == "M2"
