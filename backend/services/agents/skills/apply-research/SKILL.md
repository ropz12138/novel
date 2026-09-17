---
name: apply-research
description: 将已有小说研究成果转化为当前作品可用的写作技法约束，并保留来源和作品隔离边界。
---

# 应用研究成果

## 完成标准

- 使用完整研究成果正文，来源 ID 可追踪。
- 产物明确适用环节、可借鉴技法和当前作品中的实现方式。
- 技法只迁移方法，保持当前作品事实。

## 执行流程

1. 先列出并选择与任务直接相关的研究成果。
2. `resolve_research_context` 按成果 ID 读取全文并保存研究上下文产物。
3. `assemble_work_context` 装配当前作品完整资料。
4. `apply_research_techniques` 生成技法应用产物。
5. `review_artifact_quality` 检查来源、作品隔离和可执行性。
6. 将通过的技法产物作为后续规划、写作或修订 Agent 的输入；独立调用时只汇报技法建议。
