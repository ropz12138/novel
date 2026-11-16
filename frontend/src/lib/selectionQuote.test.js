import { describe, expect, it } from 'vitest';
import { quoteTextFromRange } from './selectionQuote';

describe('quoteTextFromRange', () => {
  it('preserves paragraph boundaries and literal UI words in prose', () => {
    const root = document.createElement('div');
    root.innerHTML = '<button>保留修改</button><p>正文写着“保留修改”。</p><p>第二段<br>下一行</p>';
    const range = document.createRange();
    range.selectNodeContents(root);
    expect(quoteTextFromRange(range)).toBe('正文写着“保留修改”。\n\n第二段\n下一行');
  });
  it('keeps partial text inside a clickable diff span', () => {
    const root = document.createElement('span');
    root.setAttribute('role', 'button');
    root.textContent = '前文新内容后文';
    const range = document.createRange();
    range.setStart(root.firstChild, 2);
    range.setEnd(root.firstChild, 5);
    expect(quoteTextFromRange(range)).toBe('新内容');
  });
  it('does not quote a partial selection inside a toolbar button', () => {
    const root = document.createElement('button');
    root.textContent = '保留修改';
    const range = document.createRange();
    range.selectNodeContents(root);
    expect(quoteTextFromRange(range)).toBe('');
  });
});
