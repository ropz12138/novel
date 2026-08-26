"""章节正文字数统计。"""


def chapter_body_word_count(content: str) -> int:
    return len((content or "").replace("\n", "").replace(" ", ""))


def build_word_count_advice(actual: int, expected: int) -> str:
    diff = actual - expected
    if diff == 0:
        return f"建议：实际字数与期望字数一致（{expected} 字），篇幅合适。"
    if diff < 0:
        short_by = -diff
        pct = round(short_by / expected * 100)
        return (
            f"建议：实际字数比期望少 {short_by} 字（约少 {pct}%），"
            f"可补充情节推进、对话或场景细节以达到目标篇幅。"
        )
    long_by = diff
    pct = round(long_by / expected * 100)
    return (
        f"建议：实际字数比期望多 {long_by} 字（约多 {pct}%），"
        f"可删减冗余描写、合并重复信息或收紧节奏。"
    )
