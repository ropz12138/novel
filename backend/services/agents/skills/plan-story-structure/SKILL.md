---
name: plan-story-structure
description: 拆分或调整卷、情节和章节结构。
---

# 规划故事结构

本技能由 Supervisor 亲自执行。参考规则通过 `read_skill_reference` 按阶段完整加载，工具仅负责读取与保存。
参考文件中的结构化输出格式用于组织工作记录；结构节点使用节点工具保存，章节正文交给 `run_writing_agent`，用户回复使用 `respond_to_user`。

## 完成标准

层级及同级顺序清晰，每层承担相应目标，规划与已有正文兼容。

## 执行流程

1. 读取当前结构、相关章节正文和用户要求；确定新增、插入或续推的范围。
2. 用 `read_skill_reference` 加载 `story_structure.txt`；逐章规划时加载 `chapter_plan.txt`，亲自完成目标、冲突、因果和阶段变化设计。
3. 用 `create_node`、`create_edge` 建立所需结构；已有结构节点的 `content` 局部调整使用 `update_node(mode="replace", replacements=[...])`，整体重构才使用 `mode="overwrite"`；`sort_order` 通过对应参数单独更新。
4. 已有正文的章节保留 `content`，将新的章节计划写入 `chapter_elements`，逐章调用 `read_chapter_context` 核对前文的数量收支、能力、伤势与时间地点。用 `save_chapter_notes(chapter_node_id, notes=完整章节笔记, expected_content_sha256=回读值)` 保存作者要求、设计与需要延续的连续性事实。
5. 回读检查层级、节奏和因果；需要改动既有正文时先明确用户授权范围，再执行修改章节技能。
