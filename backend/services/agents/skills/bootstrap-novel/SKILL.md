---
name: bootstrap-novel
description: 根据灵感或梗概从零创建作品骨架，包括创作定位、世界观、核心角色、总纲与初始故事结构。
---

# 初始化小说

## 完成标准

- 真实节点覆盖作品定位、世界规则、核心角色、总纲和首层故事结构。
- 结构节点通过真实 UUID 建立父子连线，同级顺序明确。
- 节点内容已写入并完成回读。

## 执行流程

1. 读取当前画布和用户完整要求，确定所需节点类型、标题、顺序及层级。
2. 使用 `create_node` 建立真实节点，记录返回的 UUID；已有节点沿用其 UUID。
3. 使用 `create_edge` 按真实 UUID 建立 outline→volume→plot→chapter 的父子连线。
4. 调用 `develop_existing_nodes`，specialty=`architecture`，传入本轮节点 UUID 与用户完整要求，由专职 Agent 直接写入节点内容。
5. 读取画布核对节点、连线和内容；如需修改，继续更新同一真实节点。
