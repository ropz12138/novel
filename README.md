# Novel

画布小说创作系统，Supervisor 编排与独立 Writer、Reviewer 子 Agent 协作。

## Supervisor + Writer 子 Agent

Supervisor 完成需求理解、构思、评审决策和故事记忆，通过 `run_writing_agent` 委派
Writer 写作、重写、局部修订及自然化。Writer 使用隔离的任务提交运行时，沿用
项目 `DeepAgentChatModel / BaseLLMProvider` 和用户的模型配置，每次使用新上下文。
通用 Deep Agents `task` 保持关闭，子 Agent 通过有明确输入契约的业务工具调用。

交接的 `brief` 分别表达当前版本场景、世界事实、人物已知信息及来源、叙述视角、
完整作者要求和修改范围。运行时从数据库完整读取所选前章、角色、世界观正文，
父会话历史、编辑过程及混合章节笔记留在 Supervisor。作者提出“计划后推”时，
Supervisor 将其转为当前版本的时间安排，再交给 Writer。

Writer 用 `submit_writing` 提交完整正文或精确替换；运行时核对正文哈希后保存，
保留现有画布 diff、章节同步与版本记录。Supervisor 的节点工具只创建空章、
编辑章节元数据，文学正文统一经 Writer；用户手动编辑接口保持原样。
失败或中断返回失败状态，不切回 Supervisor 代写。子 Agent 流不会混入主对话回复。

Writer、Reviewer 正常只进行一次模型调用与结果提交。提交工具的参数校验、原文
匹配或证据校验失败时，完整任务、失败提交和工具错误保留在同一上下文中，最多
追加两次纠错；成功立即结束。模型接口故障与中断直接上报，正文版本冲突沿用
既有保存校验。局部修订的失败返回保留原操作和范围，范围扩大由作者决定。

`load_workflow_skill` 加载 12 个创作流程，`read_skill_reference` 按阶段完整读取
写作规则；规则读取本身不调用模型。Writer、Reviewer 自动完整加载相应规则。

写章前由 Supervisor 加载 `plan-chapter-scenes`，规划承接的读者期待、主要回报、
有效阻力、人物目的与场景因果，按需选用局部技巧。完整计划通过 `brief.scene_plan`
交接给 Writer，具体台词、动作反应与句段节奏由 Writer 实现。单独请求规划时，
计划保存到章节笔记的创作设计部分，待写内容明确标记为计划。

章节笔记通过 `save_chapter_notes` 保存，使用 `read_node_content` 返回的
`content_sha256` 校验正文版本，正文变化后重新整理笔记。场景计划、评审和修订决定
在当前任务中执行，不写入 `workflow_artifacts`。

评审使用 `run_review_agent` 统一入口，当前仅注册 `tired_reader`：上了一天班的劳累
读者，关注阅读负担、投入感、题材适合的情绪回报和继续阅读意愿。Reviewer 使用与
Writer 相同的独立运行时和项目模型适配层，只提供 `submit_review` 报告工具。
目标章节和参考资料完整加载，各视角共享一次读取的正文快照；报告返回正文哈希、
阅读感受、所需元素以及带原文证据的问题。报告不会写入小说正文。

视角在 `review_agent_tools.REVIEW_PERSPECTIVES` 注册独立提示词，统一调用支持多个
视角并行执行，分别返回成功报告与失败原因。旧评审参考规则与既有代码保留，
Supervisor 的评审入口统一为 `run_review_agent`。
评审强度保持低/中/高三个选项：低档完成写作、回读和摘要，明确要求时执行评审；
中档每个视角检查一次并汇总修改；高档对实际修改后的最新正文复检。
实际质量和执行完整性需要用真实写章实验判断。

验证命令：`backend/.venv/bin/pytest backend/tests -q`。
正文局部修改按工具提交的每个 `old/new` 替换项分组，Writer 和非章节节点编辑共用这一协议。
节点读取后端持久化的累计分组，对话卡片保留本次调用的原始分组；重叠修改按精确字符范围累计。
提示词引导按完整原段落分组，新增段落与相邻原段落一起提交，跨段落重构按完整组审阅。
整章写入展示一个完整正文组；提交完成后显示 diff。历史仅有整稿基线的状态按完整正文对照恢复。
分组使用 `node_agent_diff_states`、`node_agent_diff_groups` 的文本及整数列保存，后端启动时自动建表。
隔离回归测试：`backend/.venv/bin/pytest backend/tests/test_writing_subagent.py -q`。
手动试验建议使用开发服务的新会话，重放“计划后推”的修改要求，检查 Writer 的
trace 输入只有独立任务，正文呈现当前安排，人物判断依据当面听闻；再检查一次
局部修改、整章重写及中断。自动化测试验证隔离和写入契约，文学效果需真实生成验收。

## Structure

- `frontend`: React 前端（Canvas 画布 + Supervisor 聊天）
- `backend`: FastAPI 后端（画布 API + Supervisor / Writer）
- `scripts`: 开发/生产启动脚本
- `docs`: 设计文档

## Quick Start (Dev)

```bash
./scripts/start_canvas_dev.sh
./scripts/stop_canvas_dev.sh
```

## Production

```bash
./scripts/start_canvas_prod.sh
./scripts/stop_canvas_prod.sh
```

前端静态文件构建到 `deploy/novel`，供 nginx `/novel/` 路由使用。

## Android App

App 使用 Capacitor 封装现有 React 前端。应用 ID、版本号、API 地址、APK
下载路由和发布路径统一配置在根目录 `config.json` 的 `app.mobile` 中。

安装 Android SDK、JDK 和 Node.js 后执行：

```bash
bash scripts/build_android_apk.sh
```

脚本会创建或同步 Android 工程、写入 `version_name` 与 `version_code`、构建
APK，并将安装包发布到 `apk_publish_path`。默认线上下载地址为
`/novel/novel.apk`，下载文件保留 `.apk` 后缀，避免手机浏览器将其识别为
通用二进制文件。安装包不会写入 `frontend/public`，以免被 Vite 作为静态
资源再次打入下一版 APK。Android 构建使用 `android_java_home` 指定的 JDK，
`android_java_home` 指向 App 构建专用 JDK；当前 Capacitor Android 7.4
使用 Java 21 源码级别，因此配置为 JDK 21。
Android SDK 目录和编译平台分别由 `android_sdk_root`、
`android_compile_sdk` 配置；一键脚本会自动安装缺少的编译平台。

发布新版本时必须同时递增 `version_name` 和整数 `version_code`；App 使用
`version_code` 判断是否存在更新。生产启动脚本会从 `artifacts` 重新发布
APK，避免部署前端时清空线上安装包。App 内点击“下载更新”后由原生插件
下载 APK 并拉起系统安装器，不会跳转到浏览器。

## LangSmith Trace

```bash
python scripts/fetch_latest_trace.py
```
