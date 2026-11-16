function lineStart(source, index) {
  return index === 0 || source[index - 1] === "\n";
}

function consumeFence(source, index) {
  if (!lineStart(source, index)) return 0;
  const opening = /^( {0,3})(`{3,}|~{3,})[^\n]*\n?/.exec(source.slice(index));
  if (!opening) return 0;
  const marker = opening[2][0];
  const size = opening[2].length;
  let cursor = index + opening[0].length;
  const closing = new RegExp(`^ {0,3}${marker}{${size},}[ \\t]*$`);
  while (cursor < source.length) {
    const next = source.indexOf("\n", cursor);
    const line = source.slice(cursor, next === -1 ? source.length : next);
    if (closing.test(line)) return (next === -1 ? source.length : next + 1) - index;
    if (next === -1) return source.length - index;
    cursor = next + 1;
  }
  return source.length - index;
}

function consumeInlineCode(source, index) {
  let ticks = 0;
  while (source[index + ticks] === "`") ticks += 1;
  const closer = "`".repeat(ticks);
  const end = source.indexOf(closer, index + ticks);
  if (end < 0) return 0;
  return end + ticks - index;
}

/** 把正文里的字面量 \\n 交给 Markdown：连续换行分段，单个换行作硬换行。代码片段保持原样。 */
export function renderLiteralNewlines(markdown) {
  const source = String(markdown ?? "");
  let result = "";
  let index = 0;
  while (index < source.length) {
    const fence = consumeFence(source, index);
    if (fence) {
      result += source.slice(index, index + fence);
      index += fence;
      continue;
    }
    if (source[index] === "`") {
      const inline = consumeInlineCode(source, index);
      if (inline) {
        result += source.slice(index, index + inline);
        index += inline;
        continue;
      }
    }
    if (source.startsWith("\\n", index)) {
      let count = 0;
      while (source.startsWith("\\n", index)) {
        count += 1;
        index += 2;
      }
      result += count > 1 ? "\n".repeat(count) : "  \n";
      continue;
    }
    result += source[index];
    index += 1;
  }
  return result;
}

export function remarkHtmlBreaks() {
  return (tree) => {
    const visit = (node) => {
      if (!Array.isArray(node?.children)) return;
      node.children = node.children.map((child) => {
        if (child?.type === "html" && /^<br\s*\/?\s*>$/i.test(child.value.trim())) {
          return { type: "break" };
        }
        visit(child);
        return child;
      });
    };
    visit(tree);
  };
}
