---
name: plan-story-structure
description: 将总纲拆卷、卷拆情节、情节拆章节，并处理插入、续写和后续结构调整。
---

# 规划故事结构

## 完成标准

- outline、volume、plot、chapter 层级清楚且同级顺序连续。
- 每个阶段只承担对应层级的目标、冲突与变化。
- 已有正文保持原内容，结构调整的影响范围明确。

## 执行流程

1. 读取现有结构、章节正文和用户完整要求。
2. 新卷、情节或章节先用 `create_node` 建立真实节点；已有节点沿用真实 UUID。
3. 使用 `create_edge` 按真实 UUID 建立父子连线，核对顺序。
4. 卷与情节调用 `develop_existing_nodes`，specialty=`structure`；逐章规划使用 specialty=`chapters`，直接完善目标节点。
5. 回读检查节奏、因果和层级；影响既有正文的结构修改由用户决定，其余修订继续更新原节点。
