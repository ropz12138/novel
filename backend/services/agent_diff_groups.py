"""按精确字符范围维护工具分组；重叠修改沿已有分组累计。"""


def apply_groups(baseline, groups):
    current = baseline
    for group in reversed(groups):
        start = group["start_offset"]
        old = group["old_text"]
        if start < 0 or start + len(old) > len(current):
            raise ValueError("分组位置超出正文范围")
        if current[start:start + len(old)] != old:
            raise ValueError("分组原文与正文位置不一致")
        current = current[:start] + group["new_text"] + current[start + len(old):]
    return current


def compose_groups(baseline, groups, replacements):
    segments = []
    cursor = 0
    for group in groups:
        start = group["start_offset"]
        if start > cursor:
            text = baseline[cursor:start]
            segments.append({"old": text, "new": text})
        segments.append({"old": group["old_text"], "new": group["new_text"]})
        cursor = start + len(group["old_text"])
    if cursor < len(baseline):
        text = baseline[cursor:]
        segments.append({"old": text, "new": text})

    for replacement in replacements:
        start = replacement["start_offset"]
        old, new = replacement["old_text"], replacement["new_text"]
        end = start + len(old)
        current = "".join(s["new"] for s in segments)
        if current[start:end] != old or start < 0 or end > len(current):
            raise ValueError("替换分组与当前正文不一致")
        # 仅切分未修改文本；已有分组作为完整原子保留。
        split = []
        position = 0
        for segment in segments:
            length = len(segment["new"])
            if segment["old"] == segment["new"]:
                cuts = sorted({0, length, *[p - position for p in (start, end) if position < p < position + length]})
                for left, right in zip(cuts, cuts[1:]):
                    text = segment["new"][left:right]
                    split.append({"old": text, "new": text})
            else:
                split.append(segment)
            position += length
        segments = split
        positions = []
        position = 0
        for index, segment in enumerate(segments):
            length = len(segment["new"])
            if length and ((position < end and position + length > start)
                           or (start == end and position < start < position + length)):
                positions.append((index, position))
            position += length
        if not positions:
            # 空正文完整写入以及纯插入，以精确字符边界定位。
            position = 0
            index = 0
            while index < len(segments) and position < start:
                position += len(segments[index]["new"])
                index += 1
            segments.insert(index, {"old": old, "new": new})
            continue
        first, expanded_start = positions[0]
        last = positions[-1][0]
        selected = segments[first:last + 1]
        selected_new = "".join(s["new"] for s in selected)
        relative = start - expanded_start
        segments[first:last + 1] = [{
            "old": "".join(s["old"] for s in selected),
            "new": selected_new[:relative] + new + selected_new[relative + len(old):],
        }]

    result = []
    offset = 0
    for segment in segments:
        old, new = segment["old"], segment["new"]
        if old != new:
            result.append({"start_offset": offset, "old_text": old, "new_text": new,
                           "type": "replace" if old and new else "delete" if old else "insert_after",
                           "paragraph_index": baseline[:offset].count("\n\n") + (1 if old else 0)})
        offset += len(old)
    return [] if "".join(segment["old"] for segment in segments) == "".join(segment["new"] for segment in segments) else result
