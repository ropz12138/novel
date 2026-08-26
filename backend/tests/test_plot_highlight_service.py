from services.plot_highlight_service import (
    extract_plot_highlights,
    validate_plot_highlights,
)
def test_extract_plot_highlights_keeps_story_order():
    content = (
        "开场。[[PLOT]]林川收到失踪名单后决定潜入档案室，并找到了被篡改的登记记录。[[/PLOT]]"
        "发展。[[PLOT]]守卫发现林川后封锁出口，林川烧毁假记录制造混乱并带着真名单逃出。[[/PLOT]]"
    )
    assert extract_plot_highlights(content) == [
        "林川收到失踪名单后决定潜入档案室，并找到了被篡改的登记记录。",
        "守卫发现林川后封锁出口，林川烧毁假记录制造混乱并带着真名单逃出。",
    ]


def test_long_chapter_rejects_too_few_and_too_short_highlights():
    content = "背景与过程。" * 150 + "[[PLOT]]他逃了。[[/PLOT]]"
    result = validate_plot_highlights(content)

    assert result.valid is False
    assert result.required_count >= 2
    assert any("数量不足" in error for error in result.errors)
    assert any("过短" in error for error in result.errors)
    assert any("信息量不足" in error for error in result.errors)
    assert any("按顺序覆盖本章关键事件链" in error for error in result.errors)


def test_long_chapter_accepts_highlights_that_form_a_compact_overview():
    highlights = [
        "林川从匿名信中发现妹妹失踪与旧档案有关，于是决定当夜潜入市政档案室查证。",
        "林川潜入后找到被篡改的失踪人员名单，却因触发警报而遭到守卫封锁和追捕。",
        "林川烧毁假档案制造混乱，带着真名单逃出，并确认幕后人正在转移所有知情者。",
    ]
    content = ("环境、对话与行动细节铺陈。" * 95) + "".join(
        f"[[PLOT]]{item}[[/PLOT]]" for item in highlights
    )
    result = validate_plot_highlights(content)

    assert result.valid is True
    assert result.highlights == highlights
def test_short_draft_does_not_require_plot_highlights():
    result = validate_plot_highlights("很短的章节草稿。")
    assert result.valid is True
    assert result.required_count == 0


def test_unclosed_marker_is_rejected():
    result = validate_plot_highlights("[[PLOT]]林川进入档案室并找到了名单。")
    assert result.valid is False
    assert "剧情高亮标签未成对闭合" in result.errors
