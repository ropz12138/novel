/** flex 列布局中可滚动区域须带 min-h-0，否则子项会被内容撑开而无法在视口内滚动 */
export const WORK_DETAIL_BODY_FLEX_CLASS = "flex flex-1 min-h-0 overflow-hidden";
export const WORK_DETAIL_CONTENT_ROW_CLASS = "flex min-h-0 min-w-0 flex-1 overflow-hidden";
export const WORK_DETAIL_SCROLL_PANE_CLASS =
  "pretty-scrollbar min-h-0 min-w-0 flex-1 overflow-auto px-4 pb-4 pt-4 sm:px-6 sm:pb-4 sm:pt-6";

export function hasFlexScrollMinHeight(className = "") {
  return /\bmin-h-0\b/.test(className);
}
