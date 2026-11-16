"""章节原文的物理行号；空行参与计数，原始文本保持完整。"""
def numbered_source(source):
    return '\n'.join(f'{index} | {line}' for index, line in enumerate(source.split('\n'), 1))


def source_quote(source, start, end):
    lines = source.split('\n')
    if not 1 <= start <= end <= len(lines):
        raise ValueError(f'起止行号需要满足 1 ≤ 起始行 ≤ 结束行 ≤ {len(lines)}')
    return '\n'.join(lines[start - 1:end])
