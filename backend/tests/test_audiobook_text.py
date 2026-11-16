from services.audiobook_text import line_is_speakable, speech_text, split_audiobook_lines


def test_split_keeps_newlines_and_round_trips():
    text = "第一句。\n\n第二句。"
    lines = split_audiobook_lines(text)
    assert lines == ["第一句。\n", "\n", "第二句。"]
    assert "".join(lines) == text


def test_blank_and_punctuation_lines_are_not_speakable():
    assert line_is_speakable(speech_text("\n")) is False
    assert line_is_speakable(speech_text("……\n")) is False
    assert line_is_speakable(speech_text("第一句。\n")) is True
    assert line_is_speakable(speech_text("Room 3\n")) is True


def test_plot_markers_are_removed_before_speech():
    speech = speech_text("开场。[[PLOT]]重点[[/PLOT]]后续。\n")
    assert speech == "开场。重点后续。"
    assert "PLOT" not in speech
    assert line_is_speakable(speech) is True


def test_large_blocks_preserve_every_character_and_prefer_paragraph_boundaries():
    from services.audiobook_text import split_audiobook_chunks
    text = ('开头。' * 300) + '\n\n' + ('中段。' * 300) + '\n\n' + ('末段。' * 300)
    chunks = split_audiobook_chunks(text)
    assert ''.join(chunks) == text
    assert all(0 < len(chunk) <= 2000 for chunk in chunks)
    assert chunks[0].endswith('\n\n')
    assert len(chunks) == 2


def test_long_paragraph_splits_at_sentence_boundaries_and_keeps_quotes():
    from services.audiobook_text import split_audiobook_chunks
    text = ('“一句完整的话。”' * 500)
    chunks = split_audiobook_chunks(text)
    assert ''.join(chunks) == text
    assert all(len(chunk) <= 2000 for chunk in chunks)
    assert all(chunk.endswith('。”') for chunk in chunks)


def test_unpunctuated_long_text_and_unicode_are_split_without_loss():
    from services.audiobook_text import split_audiobook_chunks
    text = '甲😀' * 2500
    chunks = split_audiobook_chunks(text)
    assert list(map(len, chunks)) == [2000, 2000, 1000]
    assert ''.join(chunks) == text


def test_paragraph_parts_never_merge_lines_and_keep_long_paragraph_complete():
    from services.audiobook_text import audiobook_paragraph_parts
    long = '一句完整的话。' * 700
    content = '开头。\n\n[[PLOT]]第二段。[[/PLOT]]\n' + long
    parts = audiobook_paragraph_parts(content)
    assert [(p['line_index'], p['text']) for p in parts[:2]] == [(0, '开头。'), (2, '第二段。')]
    assert all(p['line_index'] == 3 for p in parts[2:])
    assert ''.join(p['text'] for p in parts[2:]) == long
    assert all(len(p['text']) <= 2000 for p in parts)
