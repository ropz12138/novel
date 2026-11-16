import { describe, expect, it } from 'vitest';
import { buildGenerationRequests, chapterDramaPath, formatDramaDuration, previewStoryboardArguments, resolveInputMode, videoTiming } from './shortDrama';

describe('short drama generation contract', () => {
  it('formats the combined episode duration without floating point noise', () => {
    expect(formatDramaDuration(0)).toBe('0 秒');
    expect(formatDramaDuration(265)).toBe('4 分 25 秒（265 秒）');
    expect(formatDramaDuration(60)).toBe('1 分 0 秒（60 秒）');
    expect(formatDramaDuration(0.1 + 0.2)).toBe('0.3 秒');
  });
  it('preserves full prompts and maps inputs to the video script contract', () => {
    const prompt = '完整原文\n' + '细节'.repeat(20000);
    const request = buildGenerationRequests({ width: 960, height: 544, portraits: [{ id: 'p1', imagePath: '/local/person.png' }, { id: 'p2', imagePath: '/local/scene.png' }], shots: [{ id: 's1', prompt, duration: 5, seed: 42, mode: 'turbo', inputMode: 'reference', referencePaths: 'refs/obsolete.png', roles: [{ roleId: 'r2', portraitId: 'p2' }, { roleId: 'r1', portraitId: 'p1' }] }] })[0];
    expect(request.prompt).toBe(prompt);
    expect(request.reference_images).toEqual(['/local/person.png', '/local/scene.png']);
    expect(request.steps).toBe(8);
    expect(request.output_path).toBe('outputs/short_drama/s1.mp4');
    expect(request.first_frame).toBeNull();
  });
  it('derives the generation mode from selected portraits and the first-frame source', () => {
    expect(resolveInputMode({ roles: [], firstFrameShotId: '' })).toBe('text');
    expect(resolveInputMode({ roles: [{ roleId: 'r1', portraitId: null }], firstFrameShotId: '' })).toBe('text');
    expect(resolveInputMode({ roles: [{ roleId: 'r1', portraitId: 'p1' }], firstFrameShotId: '' })).toBe('reference');
    expect(resolveInputMode({ roles: [], firstFrameShotId: 's0' })).toBe('first_lock');
    expect(resolveInputMode({ roles: [{ roleId: 'r1', portraitId: 'p1' }], firstFrameShotId: 's0' })).toBe('conflict');
    const request = buildGenerationRequests({ width: 960, height: 544, portraits: [{ id: 'p1', imagePath: '/local/person.png' }], shots: [{ id: 's1', prompt: '画面', inputMode: 'text', roles: [{ roleId: 'r1', portraitId: 'p1' }], duration: 5, seed: 1, mode: 'turbo' }] })[0];
    expect(request.reference_images).toEqual(['/local/person.png']);
  });
  it('does not send manual frame paths for first-frame lock', () => {
    const request = buildGenerationRequests({ width: 960, height: 544, shots: [{ id: 's1', prompt: '画面', inputMode: 'first_lock', firstFrameShotId: 's0', referencePaths: 'refs/old.png', firstFrame: 'refs/start.png', lastFrame: 'refs/end.png', duration: 5, seed: 4, mode: 'base' }] })[0];
    expect(request.reference_images).toEqual([]);
    expect(request.first_frame).toBeNull();
    expect(request.last_frame).toBeNull();
    expect(request.steps).toBe(20);
  });
  it('reads partial storyboard tool arguments as readable fields', () => {
    const partial = '{"message":"已设计一个镜头\\n保留对白","expected_revision":0,"shots":[{"id":null,"title":"推门","prompt":"电影写实，林雨说\\"进来\\"","duration":6,"roles":[{"roleId":"role-1","portraitId":null}],"sourceQuote":"林雨推门而入。"},{"title":"特写","prompt":"眼';
    const preview = previewStoryboardArguments(partial);
    expect(preview.message).toBe('已设计一个镜头\n保留对白');
    expect(preview.shots[0]).toMatchObject({ title: '推门', prompt: '电影写实，林雨说"进来"', duration: 6, sourceQuote: '林雨推门而入。', roles: [{ roleId: 'role-1', portraitId: null }] });
    expect(preview.shots[1]).toMatchObject({ title: '特写', prompt: '眼' });
    expect(previewStoryboardArguments('{"updates":[{"id":"shot-1","prompt":"中文提示词"}]}').shots[0]).toMatchObject({ id: 'shot-1', prompt: '中文提示词' });
    expect(previewStoryboardArguments('{"message":"已完成回复"}').message).toBe('已完成回复');
  });
  it('encodes route identifiers', () => {
    expect(chapterDramaPath('w/a', 'c b')).toBe('/short-drama/w%2Fa/c%20b');
  });
});

describe('videoTiming', () => {
  it('matches the server frame lattice and python half-to-even midpoints', () => {
    const cases = [
      [1, 22, 0.917],
      [5, 124, 5.167],
      [7, 175, 7.292],
      [15, 362, 15.083],
      [47.5 / 24, 39, 1.625],
      [64.5 / 24, 73, 3.042],
      [1.9791666566666668, 39, 1.625],
      [1.9791666766666667, 56, 2.333],
    ];
    for (const [duration, frames, actualDuration] of cases) {
      expect(videoTiming(duration)).toEqual({ frames, actualDuration });
    }
  });
});
