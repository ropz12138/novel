# 问题记录：统筹 Agent 无法一次完成「改设定 + 改大纲/角色 + 改正文」

**记录日期**：2026-05-11  
**背景**：用户在统筹 Agent（Supervisor）中发送指令，期望修改男女主设定后，系统依次更新大纲、角色卡与第一章正文；实际仅更新了第一章（或等价地只执行了单一写作/编辑链路）。

---

## 1. 用户预期

1. 修改大纲中与男女主相关的设定（若有结构化呈现）；  
2. 更新角色卡（`characters` 表）；  
3. 基于新设定重写或修改第一章正文。

即：**复合、多步骤任务**，涉及多种资源（大纲 JSON、角色实体、章节正文）。

---

## 2. 实际行为（现象）

意图被归类为单一任务（例如 `write_chapter` / `edit_chapter`），后续只走章节写作或章节编辑子流程，**未串行执行**「改大纲 → 改角色 → 改正文」。

---

## 3. 根因分析（架构与设计）

### 3.1 意图分类器：单一意图输出

- 配置见：`backend/app/services/supervisor/prompts/classify_intent.txt`  
- 输出 JSON 中 `intent` 为 **互斥枚举**：`create_outline | edit_outline | write_chapter | edit_chapter | chat`。  
- **不存在**「多意图」「步骤列表」「pipeline」等表达形式，模型必须在多项任务中 **择一**。

### 3.2 Supervisor 调度：一对一硬路由

- 实现见：`backend/app/services/supervisor/supervisor_agent.py` 中 `_dispatch`。  
- 每个 `intent` **仅对应一个** `_handle_*` 分支，执行完毕后直接返回，**不会**自动串联 `edit_outline` → `write_chapter` 等多步流程。

### 3.3 章节写作 Graph：大纲可变但角色卡不在链路内

- `ChapterAgentGraph` + `thinking_node`（`backend/app/services/agent/nodes.py`）可根据构思输出 `outline_changes_needed` / `outline_change_operations`，经 `outline_edit_node` 写回 **作品的 `outline_tree`**。  
- 构思 Prompt：`backend/app/services/prompt_templates/agent_thinking.txt`，上下文主要为 `story_info`、`outline_tree`、`chapter_outline`、`previous_chapters` 等，**不包含角色卡列表作为一等公民**。  
- **没有**节点根据用户指令直接更新 **characters 表**（角色卡与大纲、章节写作链路未打通）。

### 3.4 小结表

| 环节           | 限制说明                                       |
|----------------|------------------------------------------------|
| 意图识别       | 只能输出单一意图，无法表达复合步骤             |
| 调度层         | 一对一分发，无内置多步流水线                   |
| 章节 Agent     | 可提议改大纲结构；不覆盖角色卡更新               |
| 角色数据       | 独立存储；当前 Agent 流程未纳入「改设定→落角色卡」 |

---

## 4. 若要满足预期的可能方向（备忘，非本期承诺）

1. **意图层**：扩展 `IntentResult` / 分类 Prompt，支持 `steps[]` 或多意图序列，或新增显式 `composite` 意图类型。  
2. **调度层**：Supervisor 根据步骤列表顺序调用 `_handle_edit_outline`、角色更新 API、`ChapterAgentGraph` 等。  
3. **角色层**：为「按指令更新角色」提供独立子 Agent 或工具调用，并在 composite 流程中插入一步。  
4. **章节构思**：在 `agent_thinking` 上下文中注入角色摘要/全文，并明确 Prompt：何时必须同步角色卡（若仍坚持由模型驱动，则需配套工具与校验）。

---

## 5. 相关代码索引

| 模块           | 路径 |
|----------------|------|
| 意图分类 Prompt | `backend/app/services/supervisor/prompts/classify_intent.txt` |
| 意图分类实现   | `backend/app/services/supervisor/intent_classifier.py` |
| Supervisor 调度 | `backend/app/services/supervisor/supervisor_agent.py` |
| 构思节点与大纲提案 | `backend/app/services/agent/nodes.py`（`thinking_node`、`outline_edit_node`） |
| 章节 Graph 编排 | `backend/app/services/agent/graph.py` |
| 构思 Prompt    | `backend/app/services/prompt_templates/agent_thinking.txt` |

---

*本文档用于留存问题背景与根因，便于后续需求评审与改造设计。*
