import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import NodeDetailDrawer from './NodeDetailDrawer';

describe('chapter short drama entry', () => {
  it('links the chapter detail to its scoped workbench', () => {
    render(<NodeDetailDrawer workId='work-1' node={{ id: 'chapter-1', type: 'chapter', label: '第一章', content: '正文' }} onClose={vi.fn()} />);
    expect(screen.getByRole('link', { name: '生成短剧' }).getAttribute('href')).toBe('/novel/short-drama/work-1/chapter-1');
  });
  it('opens the storyboard inside the current app', () => {
    render(<MemoryRouter initialEntries={['/']}><Routes>
      <Route path='/' element={<NodeDetailDrawer workId='work-1' node={{ id: 'chapter-1', type: 'chapter', label: '第一章', content: '正文' }} onClose={vi.fn()} />} />
      <Route path='/short-drama/:workId/:chapterId' element={<div>分镜工作台</div>} />
    </Routes></MemoryRouter>);
    fireEvent.click(screen.getByRole('link', { name: '生成短剧' }));
    expect(screen.getByText('分镜工作台')).toBeTruthy();
  });
  it('does not offer chapter generation for character nodes', () => {
    render(<NodeDetailDrawer workId='work-1' node={{ id: 'role-1', type: 'character', label: '林雨' }} onClose={vi.fn()} />);
    expect(screen.queryByRole('link', { name: '生成短剧' })).toBeNull();
  });
});
