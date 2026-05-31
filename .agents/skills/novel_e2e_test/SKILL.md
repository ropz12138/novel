# 小说创作端到端测试 Skill

## 概述

这个skill用于测试AI小说创作系统的端到端流程，包括：
- 用户认证
- 大纲生成
- 小说创作（通过supervisor agent）
- 小说质量验证

## 测试目标

### 主要关注点
1. **长篇小说场景下的连贯性**
   - 章节之间的连贯性
   - 情节发展的逻辑性
   - 角色性格的一致性

2. **小说正文与大纲的关联性**
   - 正文是否遵循大纲结构
   - 主线节点是否按计划展开
   - 支线和伏笔是否按设计实现

3. **执行质量**
   - 通过LangSmith trace查看agent中间过程
   - 工具调用的准确性
   - 错误处理和恢复能力

## 测试流程

### 1. 环境准备

```bash
# 确保后端服务运行在端口9002
netstat -tlnp | grep 9002

# 确保数据库正常运行
# 确保LLM API可用
```

### 2. 用户认证

```python
# 登录API
POST /api/auth/login
{
    "email": "test@example.com",
    "password": "test123456"
}

# 注册API（如果需要）
POST /api/auth/register
{
    "username": "test_user",
    "email": "test@example.com",
    "password": "test123456"
}
```

### 3. 大纲生成

```python
# 生成大纲（SSE流）
POST /api/works/generate-outline-stream
{
    "idea": "一个现代都市青年意外穿越到修仙世界...",
    "tags": ["穿越", "修仙", "都市"]
}

# 监听事件
- outline_status: 大纲生成进度
- outline_tree_progress: 大纲树节点生成
- outline_done: 大纲生成完成，包含work_id
```

### 4. 小说创作

```python
# 启动supervisor会话
POST /api/supervisor/start
{
    "message": "请帮我写第一章，根据大纲开始创作",
    "work_id": "<work_id>",
    "auto_mode": true
}

# 监听事件
- session_created: 会话创建
- stage_start: 阶段开始
- saved: 章节保存
- supervisor_done: 完成

# 恢复supervisor会话（创作后续章节）
POST /api/supervisor/resume
{
    "session_id": "<session_id>",
    "message": "请继续写第二章"
}
```

### 5. 获取小说内容

```python
# 获取作品信息
GET /api/works/<work_id>

# 获取章节列表
GET /api/works/<work_id>/chapters

# 获取单个章节
GET /api/works/<work_id>/chapters/<chapter_number>
```

### 6. 质量验证

#### 连贯性验证
```python
# 检查章节之间的连贯性
# 1. 第一章结尾和第二章开头的逻辑连接
# 2. 角色状态的延续性
# 3. 情节发展的合理性
```

#### 大纲关联性验证
```python
# 检查正文与大纲的对应关系
# 1. 主线节点是否按计划展开
# 2. 支线是否按设计实现
# 3. 伏笔是否按计划埋设和回收
```

#### 执行质量验证
```bash
# 使用LangSmith trace查看agent中间过程
python scripts/fetch_latest_trace.py

# 检查内容
# 1. 工具调用的准确性
# 2. LLM决策的合理性
# 3. 错误处理和恢复
```

## 测试脚本

### 快速测试脚本

```bash
# 运行端到端测试
python scripts/test_novel_e2e.py
```

### 脚本功能
1. 自动登录/注册
2. 生成大纲
3. 创作前两章
4. 获取并显示内容
5. 验证连贯性和大纲关联性

## 评估标准

### 优秀 (90-100分)
- 章节之间连贯性极佳
- 完全遵循大纲结构
- 角色性格一致
- 无明显逻辑错误

### 良好 (70-89分)
- 章节之间基本连贯
- 大部分遵循大纲
- 角色性格基本一致
- 少量逻辑问题

### 一般 (50-69分)
- 存在一些连贯性问题
- 部分偏离大纲
- 角色性格有不一致
- 有明显逻辑问题

### 差 (<50分)
- 连贯性差
- 严重偏离大纲
- 角色性格混乱
- 逻辑错误多

## 常见问题

### 1. 登录失败
- 检查用户是否存在
- 检查密码是否正确
- 检查数据库连接

### 2. 大纲生成失败
- 检查LLM API是否可用
- 检查API密钥是否有效
- 查看后端日志

### 3. 小说创作失败
- 检查supervisor agent是否正常
- 查看LangSmith trace
- 检查工具调用是否成功

### 4. 内容获取失败
- 检查work_id是否正确
- 检查章节是否已生成
- 检查数据库连接

## 扩展测试

### 长篇小说测试
```python
# 创作更多章节（如10章）
for i in range(3, 11):
    client.resume_supervisor(f"请继续写第{i}章")
```

### 不同题材测试
```python
# 测试不同类型的小说
ideas = [
    ("科幻", "一个程序员意外获得超能力...", ["科幻", "都市"]),
    ("历史", "穿越到三国时期...", ["历史", "穿越"]),
    ("悬疑", "一个侦探破解连环案件...", ["悬疑", "推理"]),
]
```

### 并发测试
```python
# 同时创作多部小说
# 测试系统的并发处理能力
```

## 监控和日志

### LangSmith监控
- 访问 https://smith.langchain.com
- 查看Novel项目
- 分析trace和性能

### 后端日志
```bash
# 查看后端日志
tail -f backend/backend-dev.log
```

### 数据库监控
```sql
-- 查看作品
SELECT * FROM works ORDER BY created_at DESC LIMIT 10;

-- 查看章节
SELECT * FROM chapters ORDER BY work_id, chapter_number;

-- 查看supervisor会话
SELECT * FROM supervisor_sessions ORDER BY created_at DESC LIMIT 10;
```

## 最佳实践

1. **测试前准备**
   - 确保所有服务正常运行
   - 清理测试数据（如果需要）
   - 准备测试用例

2. **测试过程中**
   - 记录每一步的结果
   - 截图或保存关键输出
   - 记录错误信息

3. **测试后分析**
   - 分析LangSmith trace
   - 评估小说质量
   - 记录改进建议

4. **持续改进**
   - 根据测试结果优化系统
   - 更新测试用例
   - 完善评估标准
