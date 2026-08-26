"""小说研究 Agent 使用的确定性文本工具。

本模块不调用 LLM。所有噪点、分类器、替换与编辑规则均由 Agent 显式传入。
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import statistics
import string
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import func

from config import PROJECT_ROOT
from models.research import ResearchJob, ResearchTextVersion


RESEARCH_ROOT = PROJECT_ROOT / "data" / "novel_research"
MAX_REGEX_LENGTH = 800
MAX_TOOL_TEXT = 80_000
MAX_WORKSPACE_WRITE_CHARS = 500_000
MAX_WORKSPACE_FILES = 5_000


def _get_db():
    from database import SessionLocal
    return SessionLocal()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_filename(name: str) -> str:
    clean = Path(name or "novel.txt").name.replace("\x00", "")
    return clean[:240] or "novel.txt"


def _detect_encoding(data: bytes) -> tuple[str, float]:
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig", 1.0
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16", 1.0
    for encoding, confidence in (
        ("utf-8", 0.98),
        ("gb18030", 0.9),
        ("big5", 0.65),
    ):
        try:
            data.decode(encoding)
            return encoding, confidence
        except UnicodeDecodeError:
            continue
    return "latin-1", 0.2


def _decode(data: bytes, encoding: str | None = None) -> tuple[str, str, float]:
    detected, confidence = _detect_encoding(data)
    selected = encoding or detected
    try:
        return data.decode(selected), selected, confidence if not encoding else 1.0
    except (LookupError, UnicodeDecodeError) as exc:
        raise ValueError(f"无法使用编码 {selected!r} 解码文件: {exc}") from exc


def _job_dir(job_id: str) -> Path:
    path = RESEARCH_ROOT / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _workspace_root(job_id: str) -> Path:
    root = _job_dir(job_id) / "workspace"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _resolve_workspace_path(
    job_id: str,
    relative_path: str,
    *,
    allow_root: bool = False,
) -> tuple[Path, Path]:
    """解析任务工作区路径，拒绝绝对路径、上级跳转和越界软链接。"""
    value = str(relative_path or ".").strip().replace("\\", "/")
    path = Path(value)
    if path.is_absolute() or "\x00" in value or ".." in path.parts:
        raise ValueError("工作区路径必须是安全的相对路径")
    root = _workspace_root(job_id)
    resolved = (root / path).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("工作区路径越界")
    if resolved == root and not allow_root:
        raise ValueError("必须指定工作区内的文件或子目录")
    return root, resolved


def _validate_workspace_glob(pattern: str) -> str:
    value = str(pattern or "**/*").strip().replace("\\", "/")
    path = Path(value)
    if path.is_absolute() or "\x00" in value or ".." in path.parts:
        raise ValueError("glob 必须是工作区内的安全相对模式")
    return value


def _workspace_relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _safe_section_filename(value: str) -> str:
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    clean = re.sub(r"\s+", " ", clean)
    if not clean:
        clean = "section"
    stem = clean[:-4] if clean.lower().endswith(".txt") else clean
    return stem[:216].rstrip(" .") + ".txt"


def create_job_files(user_id: str, filename: str, data: bytes) -> dict:
    """保存不可变原文件并创建任务与 raw 版本。"""
    if not data:
        raise ValueError("上传文件为空")
    job_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())
    safe_name = _safe_filename(filename)
    root = _job_dir(job_id)
    original_dir = root / "original"
    original_dir.mkdir(exist_ok=True)
    raw_path = original_dir / safe_name
    raw_path.write_bytes(data)
    encoding, confidence = _detect_encoding(data)

    db = _get_db()
    try:
        job = ResearchJob(
            id=job_id,
            user_id=user_id,
            original_filename=safe_name,
            status="queued",
            stage="等待研究 Agent",
            progress_detail=(
                f"文件大小 {len(data)} 字节；检测编码 {encoding}；"
                f"置信度 {confidence:.2f}"
            ),
        )
        version = ResearchTextVersion(
            id=version_id,
            job_id=job_id,
            version_number=0,
            kind="raw",
            encoding=encoding,
            file_path=str(raw_path),
            sha256=_sha256(data),
            manifest_text=json.dumps(
                {"operation": "upload", "filename": safe_name},
                ensure_ascii=False,
            ),
        )
        db.add_all([job, version])
        db.flush()
        job.active_version_id = version.id
        db.commit()
        return {
            "job_id": job.id,
            "version_id": version.id,
            "filename": safe_name,
            "encoding": encoding,
            "file_size": len(data),
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _get_job_version(db, job_id: str, version: str | None) -> tuple[ResearchJob, ResearchTextVersion]:
    job = db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
    if not job:
        raise ValueError("研究任务不存在")

    query = db.query(ResearchTextVersion).filter(ResearchTextVersion.job_id == job_id)
    if not version or version == "active":
        row = query.filter(ResearchTextVersion.id == job.active_version_id).first()
    elif version == "original":
        row = query.filter(ResearchTextVersion.kind == "raw").order_by(
            ResearchTextVersion.version_number
        ).first()
    elif version.startswith("v") and version[1:].isdigit():
        row = query.filter(
            ResearchTextVersion.version_number == int(version[1:])
        ).first()
    else:
        row = query.filter(ResearchTextVersion.id == version).first()
    if not row:
        raise ValueError(f"找不到文本版本 {version!r}")
    return job, row


def _read_version_text(row: ResearchTextVersion, encoding: str | None = None) -> tuple[str, str]:
    data = Path(row.file_path).read_bytes()
    text, selected, _ = _decode(data, encoding or row.encoding)
    return text, selected


def _create_version(
    db,
    job: ResearchJob,
    source: ResearchTextVersion,
    text: str,
    manifest: dict,
    *,
    index: list[dict] | None = None,
) -> ResearchTextVersion:
    number = (
        db.query(func.max(ResearchTextVersion.version_number))
        .filter(ResearchTextVersion.job_id == job.id)
        .scalar()
        or 0
    ) + 1
    version_id = str(uuid.uuid4())
    cleaned_dir = _job_dir(job.id) / "cleaned"
    cleaned_dir.mkdir(exist_ok=True)
    file_path = cleaned_dir / f"v{number}.txt"
    data = text.encode("utf-8")
    file_path.write_bytes(data)

    index_path = None
    if index is not None:
        index_dir = _job_dir(job.id) / "indexes"
        index_dir.mkdir(exist_ok=True)
        index_file = index_dir / f"v{number}.sections.json"
        index_file.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        index_path = str(index_file)

    row = ResearchTextVersion(
        id=version_id,
        job_id=job.id,
        source_version_id=source.id,
        version_number=number,
        kind="cleaned",
        encoding="utf-8",
        file_path=str(file_path),
        index_path=index_path,
        sha256=_sha256(data),
        manifest_text=json.dumps(manifest, ensure_ascii=False),
    )
    db.add(row)
    db.flush()
    job.active_version_id = row.id
    return row


def inspect_novel_text(
    job_id: str,
    version: str = "original",
    encoding: str | None = None,
    mode: str = "evenly_spaced",
    window_chars: int = 1600,
    count: int = 10,
    start: int | None = None,
) -> dict:
    db = _get_db()
    try:
        _, row = _get_job_version(db, job_id, version)
        data = Path(row.file_path).read_bytes()
        text, selected, confidence = _decode(data, encoding or row.encoding)
        window_chars = max(200, min(int(window_chars), 8_000))
        count = max(1, min(int(count), 30))
        positions: list[int]
        if mode == "head":
            positions = [0]
        elif mode == "tail":
            positions = [max(0, len(text) - window_chars)]
        elif mode == "head_tail":
            positions = [0, max(0, len(text) - window_chars)]
        elif mode == "char_range":
            positions = [max(0, min(int(start or 0), max(0, len(text) - 1)))]
        elif mode == "evenly_spaced":
            if count == 1:
                positions = [0]
            else:
                positions = [
                    int(i * max(0, len(text) - window_chars) / (count - 1))
                    for i in range(count)
                ]
        else:
            raise ValueError(f"不支持的采样模式: {mode}")
        samples = [
            {
                "char_start": pos,
                "char_end": min(len(text), pos + window_chars),
                "text": text[pos : pos + window_chars],
            }
            for pos in positions
        ]
        return {
            "version_id": row.id,
            "version_number": row.version_number,
            "kind": row.kind,
            "encoding": selected,
            "encoding_confidence": confidence,
            "bytes": len(data),
            "characters": len(text),
            "lines": text.count("\n") + 1,
            "sha256": row.sha256,
            "samples": samples,
        }
    finally:
        db.close()


def grep_novel_text(
    job_id: str,
    query: str,
    version: str = "active",
    mode: str = "literal",
    encoding: str | None = None,
    context_before: int = 120,
    context_after: int = 200,
    limit: int = 30,
    start_char: int = 0,
    count_only: bool = False,
) -> dict:
    if not query:
        raise ValueError("搜索内容不能为空")
    if len(query) > MAX_REGEX_LENGTH:
        raise ValueError("搜索表达式过长")
    db = _get_db()
    try:
        _, row = _get_job_version(db, job_id, version)
        text, _ = _read_version_text(row, encoding)
        flags = re.MULTILINE
        pattern = re.compile(re.escape(query) if mode == "literal" else query, flags)
        matches = []
        total = 0
        limit = max(1, min(int(limit), 200))
        before = max(0, min(int(context_before), 2_000))
        after = max(0, min(int(context_after), 4_000))
        for match in pattern.finditer(text, max(0, int(start_char))):
            total += 1
            if not count_only and len(matches) < limit:
                line = text.count("\n", 0, match.start()) + 1
                matches.append({
                    "line": line,
                    "char_start": match.start(),
                    "char_end": match.end(),
                    "before": text[max(0, match.start() - before) : match.start()],
                    "matched": match.group(0),
                    "after": text[match.end() : min(len(text), match.end() + after)],
                })
        return {
            "version_id": row.id,
            "total_matches": total,
            "truncated": not count_only and total > limit,
            "matches": matches,
        }
    finally:
        db.close()


def create_cleaned_copy(
    job_id: str,
    source_version: str = "original",
    source_encoding: str | None = None,
    normalize_newlines: bool = True,
    strip_bom: bool = True,
) -> dict:
    db = _get_db()
    try:
        job, source = _get_job_version(db, job_id, source_version)
        text, selected = _read_version_text(source, source_encoding)
        if strip_bom:
            text = text.lstrip("\ufeff")
        if normalize_newlines:
            text = text.replace("\r\n", "\n").replace("\r", "\n")
        row = _create_version(
            db,
            job,
            source,
            text,
            {
                "operation": "create_cleaned_copy",
                "source_encoding": selected,
                "target_encoding": "utf-8",
                "normalize_newlines": normalize_newlines,
                "strip_bom": strip_bom,
            },
        )
        db.commit()
        return {
            "version_id": row.id,
            "version_number": row.version_number,
            "encoding": row.encoding,
            "characters": len(text),
            "sha256": row.sha256,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _line_matches(line: str, mode: str, pattern: str) -> bool:
    if mode == "literal":
        return line.rstrip("\n") == pattern
    if mode == "contains":
        return pattern in line
    if mode == "regex":
        return re.search(pattern, line) is not None
    raise ValueError(f"不支持的匹配模式: {mode}")


def _apply_transform_rule(text: str, rule: dict) -> tuple[str, int, list[dict]]:
    operation = rule.get("operation")
    mode = rule.get("match_mode", "literal")
    pattern = str(rule.get("pattern", ""))
    if not pattern:
        raise ValueError("转换规则 pattern 不能为空")
    if len(pattern) > MAX_REGEX_LENGTH:
        raise ValueError("转换规则表达式过长")
    samples: list[dict] = []

    if operation == "delete_line":
        lines = text.splitlines(keepends=True)
        output = []
        count = 0
        for line in lines:
            if _line_matches(line, mode, pattern):
                count += 1
                if len(samples) < 5:
                    samples.append({"before": line.rstrip("\n"), "after": ""})
            else:
                output.append(line)
        return "".join(output), count, samples

    if operation in {"literal_replace", "regex_replace"}:
        replacement = str(rule.get("replacement", ""))
        if operation == "literal_replace":
            count = text.count(pattern)
            if count:
                pos = text.find(pattern)
                samples.append({
                    "before": text[max(0, pos - 100) : pos + len(pattern) + 100],
                    "after": text[max(0, pos - 100) : pos] + replacement
                    + text[pos + len(pattern) : pos + len(pattern) + 100],
                })
            return text.replace(pattern, replacement), count, samples
        regex = re.compile(pattern, re.MULTILINE)
        # 同时接受 Agent 常用的 ${name} 与 Python re 原生 \g<name>。
        replacement = re.sub(
            r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}",
            r"\\g<\1>",
            replacement,
        )
        for match in list(regex.finditer(text))[:5]:
            samples.append({
                "before": text[max(0, match.start() - 100) : min(len(text), match.end() + 100)],
                "after": match.expand(replacement),
            })
        output, count = regex.subn(replacement, text)
        return output, count, samples

    if operation == "delete_between":
        end_pattern = str(rule.get("end_pattern", ""))
        if not end_pattern:
            raise ValueError("delete_between 需要 end_pattern")
        if mode == "literal":
            regex = re.compile(re.escape(pattern) + r".*?" + re.escape(end_pattern), re.DOTALL)
        else:
            regex = re.compile(pattern + r".*?" + end_pattern, re.DOTALL | re.MULTILINE)
        for match in list(regex.finditer(text))[:5]:
            samples.append({"before": match.group(0)[:500], "after": ""})
        output, count = regex.subn("", text)
        return output, count, samples

    raise ValueError(f"不支持的转换操作: {operation}")


def transform_novel_text(
    job_id: str,
    rules: list[dict],
    source_version: str = "active",
    preview: bool = True,
) -> dict:
    if not rules:
        raise ValueError("至少需要一条转换规则")
    if len(rules) > 100:
        raise ValueError("单次最多执行100条转换规则")
    db = _get_db()
    try:
        job, source = _get_job_version(db, job_id, source_version)
        text, _ = _read_version_text(source)
        original_chars = len(text)
        reports = []
        for idx, rule in enumerate(rules):
            text, count, samples = _apply_transform_rule(text, rule)
            reports.append({
                "id": rule.get("id") or f"rule_{idx + 1}",
                "operation": rule.get("operation"),
                "matches": count,
                "samples": samples,
            })
        result = {
            "preview": preview,
            "source_version_id": source.id,
            "characters_before": original_chars,
            "characters_after": len(text),
            "characters_changed": len(text) - original_chars,
            "rules": reports,
        }
        if preview:
            return result
        row = _create_version(
            db,
            job,
            source,
            text,
            {"operation": "transform", "rules": rules, "report": reports},
        )
        db.commit()
        result.update({"version_id": row.id, "version_number": row.version_number})
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


_CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3,
    "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}


def _parse_section_number(raw: str | None) -> int | None:
    if not raw:
        return None
    raw = raw.strip()
    if raw.isdigit():
        return int(raw)
    total = number = 0
    for char in raw:
        if char in _CN_DIGITS:
            number = _CN_DIGITS[char]
        elif char in "十百千":
            total += (number or 1) * {"十": 10, "百": 100, "千": 1000}[char]
            number = 0
        else:
            return None
    return total + number


def _classify_lines(text: str, classifiers: list[dict]) -> list[dict]:
    if not classifiers:
        raise ValueError("classifiers 不能为空")
    compiled = []
    for classifier in classifiers:
        pattern = str(classifier.get("pattern", ""))
        if not pattern or len(pattern) > MAX_REGEX_LENGTH:
            raise ValueError("分类器 pattern 为空或过长")
        compiled.append((classifier, re.compile(pattern)))

    matches = []
    char_pos = 0
    for line_no, line in enumerate(text.splitlines(keepends=True), start=1):
        value = line.rstrip("\r\n")
        for classifier, regex in compiled:
            mode = classifier.get("mode", "regex_line")
            match = regex.match(value) if mode == "regex_line" else regex.search(value)
            if not match:
                continue
            groups = match.groupdict()
            raw_number = groups.get("number")
            matches.append({
                "type": classifier.get("name", "section"),
                "number": _parse_section_number(raw_number),
                "number_raw": raw_number,
                "title": (groups.get("title") or "").strip(),
                "heading": match.group(0).strip(),
                "line": line_no,
                "char_start": char_pos + match.start(),
                "char_heading_end": char_pos + match.end(),
                "classifier": classifier,
            })
        char_pos += len(line)
    matches.sort(key=lambda item: (item["char_start"], item["type"]))
    for idx, item in enumerate(matches):
        item["char_end"] = (
            matches[idx + 1]["char_start"] if idx + 1 < len(matches) else len(text)
        )
        item["content_chars"] = max(0, item["char_end"] - item["char_heading_end"])
    return matches


def _profile_from_matches(text: str, matches: list[dict]) -> dict:
    by_type: dict[str, list[dict]] = {}
    for item in matches:
        by_type.setdefault(item["type"], []).append(item)
    categories = {}
    for section_type, rows in by_type.items():
        numbers = [row["number"] for row in rows if row["number"] is not None]
        duplicates = sorted({n for n in numbers if numbers.count(n) > 1})
        missing = []
        if numbers and max(numbers) - min(numbers) <= 20_000:
            present = set(numbers)
            missing = [n for n in range(min(numbers), max(numbers) + 1) if n not in present]
        lengths = [row["content_chars"] for row in rows]
        categories[section_type] = {
            "count": len(rows),
            "number_min": min(numbers) if numbers else None,
            "number_max": max(numbers) if numbers else None,
            "missing_numbers": missing[:300],
            "duplicate_numbers": duplicates[:300],
            "length_min": min(lengths) if lengths else None,
            "length_median": int(statistics.median(lengths)) if lengths else None,
            "length_mean": round(statistics.mean(lengths)) if lengths else None,
            "length_max": max(lengths) if lengths else None,
                "samples": [
                    {
                        key: row.get(key)
                        for key in ("number", "title", "heading", "line", "content_chars")
                    }
                for row in rows[:12]
            ],
        }
    anomalies = [
        {
            "type": row["type"],
            "number": row["number"],
            "heading": row["heading"],
            "line": row.get("line"),
            "content_chars": row["content_chars"],
        }
        for row in matches
        if row["content_chars"] < 100 or row["content_chars"] > 15_000
    ][:200]
    return {
        "characters": len(text),
        "lines": text.count("\n") + 1,
        "total_sections": len(matches),
        "categories": categories,
        "anomalies": anomalies,
        "unclassified_prefix_chars": matches[0]["char_start"] if matches else len(text),
    }


def get_book_profile(
    job_id: str,
    classifiers: list[dict],
    version: str = "active",
) -> dict:
    db = _get_db()
    try:
        _, row = _get_job_version(db, job_id, version)
        text, _ = _read_version_text(row)
        matches = _classify_lines(text, classifiers)
        result = _profile_from_matches(text, matches)
        result["version_id"] = row.id
        return result
    finally:
        db.close()


def normalize_novel_sections(
    job_id: str,
    classifiers: list[dict],
    source_version: str = "active",
    blank_lines_before: int = 1,
    blank_lines_after: int = 1,
) -> dict:
    """按 Agent 给出的分类器规范标题换行，并创建稳定章节索引。"""
    db = _get_db()
    try:
        job, source = _get_job_version(db, job_id, source_version)
        text, _ = _read_version_text(source)
        compiled = [
            (classifier, re.compile(str(classifier["pattern"])))
            for classifier in classifiers
        ]
        output_parts: list[str] = []
        sections: list[dict] = []
        output_length = 0
        before = "\n" * max(0, min(int(blank_lines_before), 3))
        after = "\n" * max(1, min(int(blank_lines_after) + 1, 4))

        for line in text.splitlines():
            value = line.strip()
            classified = None
            for classifier, regex in compiled:
                match = regex.match(value) if classifier.get("mode", "regex_line") == "regex_line" else regex.search(value)
                if match:
                    classified = (classifier, match)
                    break
            if classified:
                classifier, match = classified
                groups = match.groupdict()
                template_text = classifier.get("output_template")
                safe_groups = {
                    key: "" if value is None else value
                    for key, value in groups.items()
                }
                heading = (
                    string.Template(str(template_text)).safe_substitute(safe_groups)
                    if template_text
                    else match.group(0).strip()
                )
                if output_length and before:
                    output_parts.append(before)
                    output_length += len(before)
                char_start = output_length
                output_parts.append(heading)
                output_parts.append(after)
                output_length += len(heading) + len(after)
                sections.append({
                    "type": classifier.get("name", "section"),
                    "number": _parse_section_number(groups.get("number")),
                    "number_raw": groups.get("number"),
                    "title": (groups.get("title") or "").strip(),
                    "heading": heading,
                    "char_start": char_start,
                    "char_heading_end": char_start + len(heading),
                })
            else:
                part = line + "\n"
                output_parts.append(part)
                output_length += len(part)
        output = "".join(output_parts).strip() + "\n"
        for idx, section in enumerate(sections):
            section["char_end"] = (
                sections[idx + 1]["char_start"] if idx + 1 < len(sections) else len(output)
            )
            section["content_chars"] = section["char_end"] - section["char_heading_end"]
        row = _create_version(
            db,
            job,
            source,
            output,
            {
                "operation": "normalize_sections",
                "classifiers": classifiers,
                "blank_lines_before": blank_lines_before,
                "blank_lines_after": blank_lines_after,
            },
            index=sections,
        )
        db.commit()
        profile = _profile_from_matches(output, sections)
        return {
            "version_id": row.id,
            "version_number": row.version_number,
            "index_path": row.index_path,
            "profile": profile,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def edit_novel_text(
    job_id: str,
    operations: list[dict],
    source_version: str = "active",
    preview: bool = True,
) -> dict:
    if not operations:
        raise ValueError("operations 不能为空")
    db = _get_db()
    try:
        job, source = _get_job_version(db, job_id, source_version)
        text, _ = _read_version_text(source)
        original = text
        reports = []
        for operation in operations:
            op = operation.get("operation")
            expected = str(operation.get("expected_text", ""))
            if not expected:
                raise ValueError("每个编辑操作都必须提供 expected_text")
            occurrences = text.count(expected)
            if occurrences != 1:
                raise ValueError(
                    f"expected_text 必须唯一命中，当前命中 {occurrences} 次"
                )
            new_text = str(operation.get("new_text", ""))
            if op == "replace":
                text = text.replace(expected, new_text, 1)
            elif op == "delete":
                text = text.replace(expected, "", 1)
            elif op == "insert_before":
                text = text.replace(expected, new_text + expected, 1)
            elif op == "insert_after":
                text = text.replace(expected, expected + new_text, 1)
            else:
                raise ValueError(f"不支持的编辑操作: {op}")
            reports.append({
                "operation": op,
                "expected_preview": expected[:300],
                "new_preview": new_text[:300],
            })
        result = {
            "preview": preview,
            "source_version_id": source.id,
            "characters_before": len(original),
            "characters_after": len(text),
            "operations": reports,
        }
        if preview:
            result["diff"] = "\n".join(list(difflib.unified_diff(
                original.splitlines(),
                text.splitlines(),
                fromfile="before",
                tofile="after",
                lineterm="",
            ))[:300])
            return result
        row = _create_version(
            db,
            job,
            source,
            text,
            {"operation": "edit", "operations": operations},
        )
        db.commit()
        result.update({"version_id": row.id, "version_number": row.version_number})
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def diff_novel_versions(job_id: str, old_version: str, new_version: str) -> dict:
    db = _get_db()
    try:
        _, old = _get_job_version(db, job_id, old_version)
        _, new = _get_job_version(db, job_id, new_version)
        old_text, _ = _read_version_text(old)
        new_text, _ = _read_version_text(new)
        matcher = difflib.SequenceMatcher(
            None, old_text.splitlines(), new_text.splitlines(), autojunk=False
        )
        inserted = deleted = replaced = 0
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "insert":
                inserted += j2 - j1
            elif tag == "delete":
                deleted += i2 - i1
            elif tag == "replace":
                replaced += max(i2 - i1, j2 - j1)
        diff_lines = list(difflib.unified_diff(
            old_text.splitlines(),
            new_text.splitlines(),
            fromfile=f"v{old.version_number}",
            tofile=f"v{new.version_number}",
            lineterm="",
            n=2,
        ))
        return {
            "old_version_id": old.id,
            "new_version_id": new.id,
            "characters_changed": len(new_text) - len(old_text),
            "inserted_lines": inserted,
            "deleted_lines": deleted,
            "replaced_lines": replaced,
            "diff_truncated": len(diff_lines) > 400,
            "diff": "\n".join(diff_lines[:400]),
        }
    finally:
        db.close()


def read_novel_sections(
    job_id: str,
    version: str = "active",
    section_type: str = "chapter",
    start_number: int | None = None,
    end_number: int | None = None,
    numbers: list[int] | None = None,
    mode: str = "full",
    per_section_chars: int = 3000,
    max_chars: int = 40_000,
) -> dict:
    db = _get_db()
    try:
        _, row = _get_job_version(db, job_id, version)
        if not row.index_path or not Path(row.index_path).is_file():
            raise ValueError("当前版本没有章节索引，请先调用 normalize_novel_sections")
        index = json.loads(Path(row.index_path).read_text(encoding="utf-8"))
        text, _ = _read_version_text(row)
        wanted = set(numbers or [])
        selected = []
        for section in index:
            if section.get("type") != section_type:
                continue
            number = section.get("number")
            if wanted and number not in wanted:
                continue
            if start_number is not None and (number is None or number < start_number):
                continue
            if end_number is not None and (number is None or number > end_number):
                continue
            selected.append(section)
        if not selected:
            raise ValueError("没有找到符合条件的分段")
        per_section_chars = max(400, min(int(per_section_chars), 20_000))
        max_chars = max(1_000, min(int(max_chars), MAX_TOOL_TEXT))
        output = []
        used = 0
        truncated = False
        for section in selected:
            raw = text[section["char_start"] : section["char_end"]].strip()
            if mode == "head":
                shown = raw[:per_section_chars]
            elif mode == "tail":
                shown = raw[-per_section_chars:]
            elif mode == "head_tail":
                half = per_section_chars // 2
                shown = raw if len(raw) <= per_section_chars else raw[:half] + "\n…\n" + raw[-half:]
            elif mode == "full":
                shown = raw
            else:
                raise ValueError(f"不支持的读取模式: {mode}")
            if used + len(shown) > max_chars:
                remaining = max_chars - used
                if remaining <= 0:
                    truncated = True
                    break
                shown = shown[:remaining]
                truncated = True
            output.append({
                "type": section["type"],
                "number": section.get("number"),
                "title": section.get("title"),
                "heading": section.get("heading"),
                "char_start": section["char_start"],
                "char_end": section["char_end"],
                "text": shown,
                "section_truncated": len(shown) < len(raw),
            })
            used += len(shown)
            if used >= max_chars:
                break
        return {
            "version_id": row.id,
            "selected_count": len(output),
            "truncated": truncated or len(output) < len(selected),
            "sections": output,
        }
    finally:
        db.close()


def create_research_directory(
    job_id: str,
    relative_path: str,
    parents: bool = True,
) -> dict:
    """在任务工作区创建目录；不允许访问原始版和整理版目录。"""
    root, target = _resolve_workspace_path(job_id, relative_path)
    existed = target.exists()
    if target.exists() and not target.is_dir():
        raise ValueError("目标路径已存在且不是目录")
    target.mkdir(parents=parents, exist_ok=True)
    return {
        "success": True,
        "path": _workspace_relative(root, target),
        "created": not existed,
    }


def write_research_file(
    job_id: str,
    relative_path: str,
    content: str,
    mode: str = "create",
    create_parents: bool = False,
) -> dict:
    """在任务工作区创建、覆盖或追加 UTF-8 文本文件。"""
    if len(content) > MAX_WORKSPACE_WRITE_CHARS:
        raise ValueError(
            f"单次写入不能超过 {MAX_WORKSPACE_WRITE_CHARS} 个字符"
        )
    if mode not in {"create", "overwrite", "append"}:
        raise ValueError(f"不支持的写入模式: {mode}")
    root, target = _resolve_workspace_path(job_id, relative_path)
    if target.exists() and target.is_dir():
        raise ValueError("目标路径是目录")
    if create_parents:
        target.parent.mkdir(parents=True, exist_ok=True)
    elif not target.parent.is_dir():
        raise ValueError("父目录不存在，请先创建目录或设置 create_parents=true")
    if mode == "create" and target.exists():
        raise ValueError("文件已存在；如需修改请明确使用 overwrite 或 append")
    if mode == "append":
        with target.open("a", encoding="utf-8", newline="") as stream:
            stream.write(content)
    else:
        target.write_text(content, encoding="utf-8", newline="")
    data = target.read_bytes()
    return {
        "success": True,
        "path": _workspace_relative(root, target),
        "mode": mode,
        "characters": len(target.read_text(encoding="utf-8")),
        "bytes": len(data),
        "sha256": _sha256(data),
    }


def list_research_files(
    job_id: str,
    relative_path: str = ".",
    glob_pattern: str = "*",
    recursive: bool = False,
    include_directories: bool = True,
    limit: int = 500,
) -> dict:
    """列出任务工作区中的文件与目录。"""
    root, directory = _resolve_workspace_path(
        job_id,
        relative_path,
        allow_root=True,
    )
    if not directory.exists():
        raise ValueError("目录不存在")
    if not directory.is_dir():
        raise ValueError("relative_path 必须是目录")
    pattern = _validate_workspace_glob(glob_pattern)
    limit = max(1, min(int(limit), MAX_WORKSPACE_FILES))
    iterator = directory.rglob(pattern) if recursive else directory.glob(pattern)
    entries = []
    total = 0
    for path in sorted(iterator, key=lambda item: item.as_posix()):
        resolved = path.resolve()
        if resolved != root and root not in resolved.parents:
            continue
        if resolved.is_dir() and not include_directories:
            continue
        total += 1
        if len(entries) >= limit:
            continue
        stat = resolved.stat()
        entries.append({
            "path": _workspace_relative(root, resolved),
            "kind": "directory" if resolved.is_dir() else "file",
            "bytes": stat.st_size if resolved.is_file() else None,
        })
    return {
        "directory": _workspace_relative(root, directory)
        if directory != root else ".",
        "total": total,
        "truncated": total > limit,
        "entries": entries,
    }


def _select_workspace_files(
    job_id: str,
    relative_paths: list[str] | None,
    glob_pattern: str | None,
    max_files: int,
) -> tuple[Path, list[Path]]:
    root = _workspace_root(job_id)
    selected: dict[str, Path] = {}
    for value in relative_paths or []:
        _, path = _resolve_workspace_path(job_id, value)
        if not path.is_file():
            raise ValueError(f"工作区文件不存在: {value}")
        selected[_workspace_relative(root, path)] = path
    if glob_pattern:
        pattern = _validate_workspace_glob(glob_pattern)
        for path in root.glob(pattern):
            resolved = path.resolve()
            if resolved.is_file() and root in resolved.parents:
                selected[_workspace_relative(root, resolved)] = resolved
    if not selected:
        raise ValueError("请提供 relative_paths 或能够匹配文件的 glob_pattern")
    max_files = max(1, min(int(max_files), MAX_WORKSPACE_FILES))
    ordered = [selected[key] for key in sorted(selected)]
    if len(ordered) > max_files:
        raise ValueError(f"匹配到 {len(ordered)} 个文件，超过 max_files={max_files}")
    return root, ordered


def read_research_files(
    job_id: str,
    relative_paths: list[str] | None = None,
    glob_pattern: str | None = None,
    start_char: int = 0,
    max_chars_per_file: int = 20_000,
    max_total_chars: int = 80_000,
    max_files: int = 50,
) -> dict:
    """读取一个、多个或 glob 匹配的工作区 UTF-8 文本文件。"""
    root, files = _select_workspace_files(
        job_id,
        relative_paths,
        glob_pattern,
        max_files,
    )
    start = max(0, int(start_char))
    per_file = max(200, min(int(max_chars_per_file), MAX_TOOL_TEXT))
    total_limit = max(1_000, min(int(max_total_chars), MAX_TOOL_TEXT))
    output = []
    used = 0
    for path in files:
        text = path.read_text(encoding="utf-8")
        remaining = total_limit - used
        if remaining <= 0:
            break
        shown = text[start : start + min(per_file, remaining)]
        output.append({
            "path": _workspace_relative(root, path),
            "characters": len(text),
            "char_start": min(start, len(text)),
            "char_end": min(len(text), start + len(shown)),
            "truncated": start + len(shown) < len(text),
            "content": shown,
        })
        used += len(shown)
    return {
        "matched_files": len(files),
        "read_files": len(output),
        "truncated": len(output) < len(files)
        or any(item["truncated"] for item in output),
        "files": output,
    }


def grep_research_files(
    job_id: str,
    query: str,
    relative_paths: list[str] | None = None,
    glob_pattern: str | None = None,
    mode: str = "literal",
    context_before: int = 120,
    context_after: int = 200,
    limit: int = 100,
    max_files: int = 1_000,
    count_only: bool = False,
) -> dict:
    """在一个、多个或 glob 匹配的工作区文件中搜索。"""
    if not query:
        raise ValueError("搜索内容不能为空")
    if len(query) > MAX_REGEX_LENGTH:
        raise ValueError("搜索表达式过长")
    if mode not in {"literal", "regex"}:
        raise ValueError(f"不支持的搜索模式: {mode}")
    root, files = _select_workspace_files(
        job_id,
        relative_paths,
        glob_pattern,
        max_files,
    )
    pattern = re.compile(
        re.escape(query) if mode == "literal" else query,
        re.MULTILINE,
    )
    before = max(0, min(int(context_before), 2_000))
    after = max(0, min(int(context_after), 4_000))
    limit = max(1, min(int(limit), 500))
    total = 0
    matched_file_count = 0
    matches = []
    per_file_counts = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        file_count = 0
        for match in pattern.finditer(text):
            total += 1
            file_count += 1
            if not count_only and len(matches) < limit:
                matches.append({
                    "path": _workspace_relative(root, path),
                    "line": text.count("\n", 0, match.start()) + 1,
                    "char_start": match.start(),
                    "char_end": match.end(),
                    "before": text[max(0, match.start() - before) : match.start()],
                    "matched": match.group(0),
                    "after": text[
                        match.end() : min(len(text), match.end() + after)
                    ],
                })
        if file_count:
            matched_file_count += 1
            per_file_counts.append({
                "path": _workspace_relative(root, path),
                "matches": file_count,
            })
    return {
        "searched_files": len(files),
        "matched_files": matched_file_count,
        "total_matches": total,
        "truncated": not count_only and total > limit,
        "per_file_counts": per_file_counts[:500],
        "matches": matches,
    }


def split_novel_sections_to_files(
    job_id: str,
    version: str = "active",
    target_directory: str | None = None,
    section_types: list[str] | None = None,
    start_number: int | None = None,
    end_number: int | None = None,
    numbers: list[int] | None = None,
    filename_template: str = "{index:04d}-{type}-{number}-{title}.txt",
    metadata_extractors: list[dict] | None = None,
    include_heading: bool = True,
    overwrite: bool = False,
) -> dict:
    """按版本索引将分段确定性地拆成工作区内的独立 UTF-8 文件。"""
    db = _get_db()
    try:
        _, row = _get_job_version(db, job_id, version)
        if not row.index_path or not Path(row.index_path).is_file():
            raise ValueError("当前版本没有章节索引，请先调用 normalize_novel_sections")
        index = json.loads(Path(row.index_path).read_text(encoding="utf-8"))
        text, _ = _read_version_text(row)
    finally:
        db.close()

    extractors = {}
    for extractor in metadata_extractors or []:
        section_type = str(extractor.get("name") or "")
        pattern = str(extractor.get("pattern") or "")
        if not section_type or not pattern or len(pattern) > MAX_REGEX_LENGTH:
            raise ValueError("metadata_extractors 的 name/pattern 为空或过长")
        extractors[section_type] = (
            re.compile(pattern),
            extractor.get("mode", "regex_line"),
        )

    wanted_types = set(section_types or ["chapter"])
    wanted_numbers = set(numbers or [])
    selected = []
    for position, section in enumerate(index, start=1):
        if wanted_types and section.get("type") not in wanted_types:
            continue
        enriched = dict(section)
        extractor = extractors.get(str(enriched.get("type") or ""))
        if extractor and (
            enriched.get("number") is None or not enriched.get("title")
        ):
            regex, extractor_mode = extractor
            heading = str(enriched.get("heading") or "")
            match = (
                regex.match(heading)
                if extractor_mode == "regex_line"
                else regex.search(heading)
            )
            if match:
                groups = match.groupdict()
                if enriched.get("number") is None:
                    enriched["number_raw"] = groups.get("number")
                    enriched["number"] = _parse_section_number(
                        groups.get("number")
                    )
                if not enriched.get("title"):
                    enriched["title"] = (groups.get("title") or "").strip()
        number = enriched.get("number")
        if wanted_numbers and number not in wanted_numbers:
            continue
        if start_number is not None and (number is None or number < start_number):
            continue
        if end_number is not None and (number is None or number > end_number):
            continue
        selected.append((position, enriched))
    if not selected:
        raise ValueError("没有找到符合条件的分段")
    if len(selected) > MAX_WORKSPACE_FILES:
        raise ValueError(f"单次最多拆分 {MAX_WORKSPACE_FILES} 个分段")

    if not target_directory:
        if len(wanted_types) == 1:
            only_type = next(iter(wanted_types))
            target_directory = {
                "chapter": "chapters",
                "extra": "extras",
                "volume": "volumes",
            }.get(only_type, f"{only_type}-sections")
        else:
            target_directory = "sections"
    root, directory = _resolve_workspace_path(job_id, target_directory)
    if directory.exists() and not directory.is_dir():
        raise ValueError("target_directory 已存在且不是目录")
    manifest_path = directory / "manifest.tsv"
    if manifest_path.exists() and not overwrite:
        raise ValueError(
            f"清单已存在: {_workspace_relative(root, manifest_path)}；"
            "如需重新拆分请设置 overwrite=true 或使用新目录"
        )
    previous_files = []
    if manifest_path.exists() and overwrite:
        for line in manifest_path.read_text(encoding="utf-8").splitlines()[1:]:
            relative = line.split("\t", 1)[0].strip()
            if not relative:
                continue
            _, previous = _resolve_workspace_path(job_id, relative)
            if previous.is_file():
                previous_files.append(previous)
    prepared = []
    seen_names = set()
    for position, section in selected:
        values = {
            "index": position,
            "type": section.get("type") or "section",
            "number": section.get("number")
            if section.get("number") is not None else "",
            "number_raw": section.get("number_raw") or "",
            "title": section.get("title") or "",
            "heading": section.get("heading") or "",
        }
        try:
            rendered = filename_template.format(**values)
        except (KeyError, ValueError) as exc:
            raise ValueError(f"filename_template 无效: {exc}") from exc
        filename = _safe_section_filename(rendered)
        if filename in seen_names:
            raise ValueError(
                f"filename_template 产生重复文件名 {filename!r}，请加入 {{index}}"
            )
        seen_names.add(filename)
        path = directory / filename
        if path.exists() and not overwrite:
            raise ValueError(
                f"文件已存在: {_workspace_relative(root, path)}；"
                "如需重新拆分请设置 overwrite=true 或使用新目录"
            )
        char_start = (
            section.get("char_start", 0)
            if include_heading
            else section.get("char_heading_end", section.get("char_start", 0))
        )
        content = text[char_start : section["char_end"]].strip() + "\n"
        prepared.append((path, content, section, position))

    directory.mkdir(parents=True, exist_ok=True)
    for previous in previous_files:
        previous.unlink()
    manifest_lines = [
        "file\ttype\tnumber\ttitle\theading\tcharacters"
    ]
    total_characters = 0
    file_rows = []
    for path, content, section, position in prepared:
        path.write_text(content, encoding="utf-8", newline="")
        total_characters += len(content)
        relative = _workspace_relative(root, path)
        file_rows.append({
            "path": relative,
            "type": section.get("type"),
            "number": section.get("number"),
            "title": section.get("title"),
            "heading": section.get("heading"),
            "characters": len(content),
            "index": position,
        })
        manifest_lines.append("\t".join(
            str(value or "").replace("\t", " ").replace("\n", " ")
            for value in (
                relative,
                section.get("type"),
                section.get("number"),
                section.get("title"),
                section.get("heading"),
                len(content),
            )
        ))
    manifest_path.write_text(
        "\n".join(manifest_lines) + "\n",
        encoding="utf-8",
        newline="",
    )
    return {
        "success": True,
        "version_id": row.id,
        "version_number": row.version_number,
        "target_directory": _workspace_relative(root, directory),
        "manifest_path": _workspace_relative(root, manifest_path),
        "file_count": len(file_rows),
        "total_characters": total_characters,
        "files_truncated": len(file_rows) > 100,
        "files": file_rows[:100],
    }
