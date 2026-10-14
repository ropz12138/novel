"""清洗版小说的索引章节读取。"""
import json
from pathlib import Path

from models.research import ResearchTextVersion


def list_indexed_chapters(version: ResearchTextVersion) -> list[dict]:
    if version.kind != "cleaned":
        raise ValueError("章节浏览只支持清洗后的小说文本")
    if not version.index_path or not Path(version.index_path).is_file():
        raise ValueError("该整理版本尚未建立章节索引")
    sections = json.loads(Path(version.index_path).read_text(encoding="utf-8"))
    return [
        {
            "section_index": index,
            "number": section.get("number"),
            "title": section.get("title") or "",
            "heading": section.get("heading") or "",
        }
        for index, section in enumerate(sections)
        if section.get("type") == "chapter"
    ]


def read_indexed_chapter(version: ResearchTextVersion, section_index: int) -> dict:
    chapters = list_indexed_chapters(version)
    selected = next(
        (chapter for chapter in chapters if chapter["section_index"] == section_index),
        None,
    )
    if selected is None:
        raise ValueError("章节不存在")
    sections = json.loads(Path(version.index_path).read_text(encoding="utf-8"))
    section = sections[section_index]
    text = Path(version.file_path).read_text(encoding=version.encoding)
    start = int(section["char_start"])
    end = int(section["char_end"])
    return {**selected, "content": text[start:end].strip()}
