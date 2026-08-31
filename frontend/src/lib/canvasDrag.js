/** Ctrl + 拖拽框选（marquee）修饰键，与 React Flow selectionKeyCode 一致。 */
export const CANVAS_MARQUEE_KEY_CODE = "Control";

/** 选中变化时是否应关闭详情抽屉（拖拽过程中忽略）。 */
export function shouldClearDrawerOnSelection(selectedCount, isDragging) {
  if (isDragging) return false;
  return selectedCount === 0 || selectedCount > 1;
}
