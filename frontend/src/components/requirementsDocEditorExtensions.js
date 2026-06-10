import { markdown, markdownLanguage } from "@codemirror/lang-markdown";

export const REQUIREMENTS_DOC_PLACEHOLDER =
  "在此记录长期有效的写作要求，例如：\n\n- 叙事视角：第三人称有限\n- 风格：轻喜剧，避免血腥描写\n- 节奏：每章 3000 字左右，章末留钩子";

/** CodeMirror 6 Markdown 编辑扩展 */
export function buildRequirementsDocExtensions() {
  return [markdown({ base: markdownLanguage })];
}
