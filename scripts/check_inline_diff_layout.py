"""在真实 Chromium 中验证多行 diff 的阅读顺序及段内基线。

用法：python scripts/check_inline_diff_layout.py --output-dir /tmp/novel-diff-layout
需要测试环境安装 playwright；使用本机 Chrome 和临时 Vite 进程。
"""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "frontend/src/components/__fixtures__/inlineDiffMultiline.json"

CHARACTER_GEOMETRY = r"""() => {
  const root = document.querySelector('[data-testid="inline-diff-new"]');
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const characters = [];
  let node;
  while ((node = walker.nextNode())) {
    if (node.parentElement.closest('button[aria-label="删除新增文本"], button[aria-label="查看已删除文本"]')) continue;
    let offset = 0;
    for (const character of node.textContent) {
      if (!/\s/u.test(character)) {
        const range = document.createRange();
        range.setStart(node, offset);
        range.setEnd(node, offset + character.length);
        const rect = range.getBoundingClientRect();
        characters.push({ character, x: rect.left, y: rect.top, height: rect.height });
      }
      offset += character.length;
    }
  }
  return characters;
}"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="/tmp/novel-diff-layout")
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}/novel/tests/inline-diff-layout.html"
    cases = [
        ("actual", fixture),
        ("insertion", {"oldText": "前文。结尾。", "newText": "前文。\n\n“我呢？”\n\n“背着弓还能怎么说？”\n\n结尾。"}),
        ("replacement", {"oldText": "前文旧段落结尾。", "newText": "前文新的第一行。\n\n新的第二行。结尾。"}),
    ]
    failures = []
    with tempfile.TemporaryFile(mode="w+") as log:
        server = subprocess.Popen(["node", "node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", str(port), "--strictPort"],
                                  cwd=ROOT / "frontend", stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 30
            while True:
                if server.poll() is not None:
                    log.seek(0)
                    raise RuntimeError(log.read())
                try:
                    with urlopen(url, timeout=1):
                        break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("测试用 Vite 启动超时")
                    time.sleep(0.1)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path="/opt/google/chrome/chrome", args=["--no-sandbox"])
                page = browser.new_page()
                page.goto(url)
                page.wait_for_function("typeof window.renderDiff === 'function'")
                for width in (390, 1080):
                    page.set_viewport_size({"width": width, "height": 900})
                    for editable in (False, True):
                        for name, texts in cases:
                            page.evaluate("args => window.renderDiff(args)", {**texts, "editable": editable})
                            page.wait_for_function("document.querySelector('[data-testid=inline-diff-new]') !== null")
                            page.wait_for_function("document.querySelector('[data-testid=inline-diff-new]').textContent.includes('结尾')" if name != "actual" else "document.querySelector('[data-testid=inline-diff-new]').textContent.includes('铝锅')")
                            geometry = page.evaluate(CHARACTER_GEOMETRY)
                            label = f"{name}-{width}-{'editable' if editable else 'readonly'}"
                            page.screenshot(path=str(output / f"{label}.png"), full_page=True)
                            visible = "".join(item["character"] for item in geometry)
                            expected = "".join(texts["newText"].split())
                            if visible != expected:
                                failures.append(f"{label}: 可见正文与 newText 不一致")
                            jumps = [(left, right) for left, right in zip(geometry, geometry[1:]) if right["y"] < left["y"] - 2]
                            if jumps:
                                left, right = jumps[0]
                                failures.append(f"{label}: {left['character']} y={left['y']:.1f} → {right['character']} y={right['y']:.1f}，正文发生向上跳行")
                            print(f"{label}: {len(jumps)} 处向上跳行")
                browser.close()
        finally:
            server.terminate()
            server.wait(timeout=10)
    if failures:
        raise AssertionError("\n".join(failures))
    print("12 个浏览器布局用例通过。")


if __name__ == "__main__":
    main()
