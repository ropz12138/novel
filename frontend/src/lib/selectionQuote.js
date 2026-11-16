// 按 DOM 结构排除界面控件，正文里出现同名词语仍应完整保留。
const EXCLUDED = 'button, svg, [aria-hidden="true"], [data-quote-ignore]';
const BLOCKS = new Set(['DIV', 'P', 'SECTION', 'LI', 'BLOCKQUOTE', 'H1', 'H2', 'H3', 'H4', 'PRE']);

export function quoteTextFromRange(range) {
  const ancestor = range.commonAncestorContainer;
  const element = ancestor.nodeType === 1 ? ancestor : ancestor.parentElement;
  if (element?.closest(EXCLUDED)) return '';
  const fragment = range.cloneContents();
  fragment.querySelectorAll(EXCLUDED).forEach((node) => node.remove());
  const read = (node) => {
    if (node.nodeType === 3) return node.textContent;
    if (node.nodeName === 'BR') return '\n';
    const text = Array.from(node.childNodes, read).join('');
    return text && BLOCKS.has(node.nodeName) ? `\n${text}\n` : text;
  };
  return read(fragment).replace(/\n{3,}/g, '\n\n').trim();
}
