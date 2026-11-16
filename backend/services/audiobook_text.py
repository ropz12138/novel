"""Chapter text split into audiobook lines."""
from __future__ import annotations

import re

PLOT_START = "[[PLOT]]"
PLOT_END = "[[/PLOT]]"


def split_audiobook_lines(text: str) -> list[str]:
    if text == "":
        return []
    parts: list[str] = []
    start = 0
    for index, char in enumerate(text):
        if char == "\n":
            parts.append(text[start:index + 1])
            start = index + 1
    if start < len(text):
        parts.append(text[start:])
    if "".join(parts) != text:
        raise ValueError("split changed text")
    return parts


def speech_text(line: str) -> str:
    return line.replace(PLOT_START, "").replace(PLOT_END, "").strip()


def line_is_speakable(speech: str) -> bool:
    for char in speech:
        code = ord(char)
        if code < 128 and char.isalnum():
            return True
        if 0x4E00 <= code <= 0x9FFF:
            return True
    return False


AUDIOBOOK_CHUNK_CHARACTERS = 2000


def split_audiobook_chunks(text: str) -> list[str]:
    """Partition all text, preferring paragraphs, then sentences, within 2000 characters."""
    chunks = []
    start = 0
    while len(text) - start > AUDIOBOOK_CHUNK_CHARACTERS:
        window = text[start:start + AUDIOBOOK_CHUNK_CHARACTERS]
        paragraph_end = window.rfind("\n\n")
        line_end = window.rfind("\n")
        if paragraph_end >= AUDIOBOOK_CHUNK_CHARACTERS // 2:
            length = paragraph_end + 2
        elif line_end >= AUDIOBOOK_CHUNK_CHARACTERS // 2:
            length = line_end + 1
        else:
            sentences = list(re.finditer(r'[。！？!?；;.][”’」』"]*', window))
            length = sentences[-1].end() if sentences else len(window)
        chunks.append(text[start:start + length])
        start += length
    if start < len(text):
        chunks.append(text[start:])
    return chunks



def audiobook_paragraph_parts(content: str, start_index: int = 0) -> list[dict]:
    """One request per speakable line, with bounded parts for exceptionally long lines."""
    parts = []
    for index, line in enumerate(split_audiobook_lines(content)):
        if index < start_index:
            continue
        text = speech_text(line)
        if line_is_speakable(text):
            parts.extend({"line_index": index, "text": part} for part in split_audiobook_chunks(text))
    return parts
