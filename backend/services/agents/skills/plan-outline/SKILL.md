---
name: plan-outline
description: 新建、反推、续写或修改小说总纲与分卷方向。
---

# 规划总纲

## 完成标准

- 总纲明确核心承诺、主要矛盾、阶段升级和最终变化。
- create、reverse、continue、revise 模式保留对应的既有事实边界。
- 真实节点已写入并完成层级核对。

## 执行流程

1. 读取全部结构节点、章节和用户完整要求。
2. 新总纲或分卷先用 `create_node` 建立真实节点；已有节点沿用真实 UUID。
3. 使用 `create_edge` 按真实 UUID 建立总纲与分卷的父子连线。
4. 调用 `develop_existing_nodes`，specialty=`outline`，直接完善目标节点。
5. 回读检查因果、升级、题材承诺及既有正文兼容性；修订时更新原节点。
