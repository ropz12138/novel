# Novel

画布小说创作系统，Supervisor 直接编写章节，Reviewer 与情节参考保持独立子 Agent。

## Supervisor 直接写章

Supervisor 完成需求理解、构思、章节正文和故事记忆，阅读评审通过 `run_review_agent`，
参考检索通过 `run_reference_agent`。章节正文用 `update_node` 保存：首次写入和整章重写使用
overwrite，局部修改使用 replace，并携带本次读取的 `content_sha256`。保存后回读验收。
沿用项目 `DeepAgentChatModel / BaseLLMProvider` 和用户的模型配置。
通用 Deep Agents `task` 保持关闭，评审与参考通过有明确输入契约的业务工具调用。

当前版本场景、世界事实、人物已知信息及来源、叙述视角、完整作者要求和修改范围留在
Supervisor 当前上下文。作者提出“计划后推”时，Supervisor 将其转为当前版本的时间安排后写进正文。

正文保存继续走节点更新、画布 diff、章节同步与版本记录。用户手动编辑接口保持原样。
评审与参考子 Agent 的流不会混入主对话回复。

Reviewer 提交一次完整报告。提交工具的参数校验或证据校验失败时，完整任务、失败提交和工具错误保留在同一上下文中，最多追加两次纠错；成功立即结束。模型接口故障与中断直接上报，章节正文版本冲突沿用 `expected_content_sha256` 校验。局部修订的失败保留原范围，范围扩大由作者决定。

`load_workflow_skill` 加载 11 个创作流程，`read_skill_reference` 按阶段完整读取写作规则；规则读取本身不调用模型。写章、改章和自然化由 Supervisor 在对应阶段完整读取 `chapter_writer.txt` 与操作规则。Reviewer 自动完整加载对应视角规则。

细节与数字按其对行动、人物、代价、风物及阅读体验的作用安排精度和篇幅；有效数字与作者明确要求完整保留。故事规划笔记和章节笔记使用紧凑条目记录有效结论、条件及关键因果，完整输入照常读取，精简发生在新生成记录的组织与措辞中。

作者可在现有 `note` 节点记录正文写作要求。Supervisor 每轮读取最新笔记，按条目内容与适用范围直接写正文。Reviewer 从当前笔记生成带来源的评审准则。评审问题应包含具体原文、阅读影响、修改方向和需要保留的信息。

`reviewer_note` 是独立的「评审笔记」节点，Supervisor 有读写权限，Reviewer 只读。Supervisor 集中维护本作品的评审标准；每次评审时运行时按作品读取节点最新全文，与普通笔记、章节笔记一起放入评审任务，无需临时指定。前端「角色与设定」侧栏可查看、编辑，新增节点菜单也可创建评审笔记。

写章前由 Supervisor 加载 `plan-chapter-scenes`，规划承接的读者期待、主要回报、有效阻力、人物目的与场景因果，按需选用局部技巧。完整计划留在当前任务说明中，具体台词、动作反应与句段节奏由 Supervisor 写入正文。单独请求规划时，计划保存到章节笔记的创作设计部分，待写内容明确标记为计划。

章节笔记通过 `save_chapter_notes` 保存，使用 `read_node_content` 返回的
`content_sha256` 校验正文版本，正文变化后重新整理笔记。场景计划、评审和修订决定
在当前任务中执行，不写入 `workflow_artifacts`。

评审使用 `run_review_agent` 统一入口，注册 `tired_reader` 与 `ai_taste`。
`tired_reader` 是上了一天班的劳累读者，关注阅读负担、投入感、题材适合的情绪回报和继续阅读意愿。
`ai_taste` 评审机械感、模板感和不自然表达。Reviewer 使用独立运行时和项目模型适配层，只提供 `submit_review` 报告工具。
目标章节和参考资料完整加载，各视角共享一次读取的正文快照；报告返回正文哈希、
阅读结论以及带原文证据的问题。报告不会写入小说正文。

视角在 `review_agent_tools.REVIEW_PERSPECTIVES` 注册独立提示词，统一调用支持多个
视角并行执行，分别返回成功报告与失败原因。Supervisor 的评审入口统一为 `run_review_agent`。
评审强度保持低/中/高三个选项：低档完成写作、回读和摘要，明确要求时执行评审；
中档每个视角检查一次并汇总修改；高档对实际修改后的最新正文复检。
实际质量和执行完整性需要用真实写章实验判断。

验证命令：`backend/.venv/bin/pytest backend/tests -q`。
正文局部修改按工具提交的段落替换分组，章节与其他节点编辑共用这一协议。
节点读取后端持久化的累计分组，对话卡片保留本次调用的原始分组；重叠修改按精确字符范围累计。
提示词引导按完整原段落分组，新增段落与相邻原段落一起提交，跨段落重构按完整组审阅。
整章写入展示一个完整正文组；提交完成后显示 diff。历史仅有整稿基线的状态按完整正文对照恢复。
分组使用 `node_agent_diff_states`、`node_agent_diff_groups` 的文本及整数列保存，后端启动时自动建表。
隔离回归测试：`backend/.venv/bin/pytest backend/tests/test_writing_subagent.py -q`。
手动试验建议使用新会话，重放“计划后推”的修改要求，检查正文呈现当前安排，人物判断依据当面听闻；再检查一次局部修改、整章重写及回读。自动化测试验证写入契约，文学效果需真实生成验收。

## Structure

- `frontend`: React 前端（Canvas 画布 + Supervisor 聊天）
- `backend`: FastAPI 后端（画布 API + Supervisor）
- `scripts`: 开发/生产启动脚本
- `docs`: 设计文档

## Quick Start (Dev)

```bash
./scripts/start_canvas_dev.sh
./scripts/stop_canvas_dev.sh
```

开发启动脚本设置 `NOVEL_ENV=development`，首次从 `config.json` 创建权限为
`0600` 的 `config.dev.json`，数据库名增加 `_dev` 后缀；以后保留开发配置的
手动调整。开发服务使用独立的 `backend/.venv-dev` 和 `logs/canvas-dev.log`。
配置检查在停止旧进程之前执行，开发数据库名和端口与生产冲突时直接报错。
首次启动使用空开发库，需单独注册账户；生产数据不会自动复制。
前端开发请求经 Vite 代理到开发配置中的后端端口。

手动启动开发后端时也需设置 `NOVEL_ENV=development`；未指定环境的现有
生产启动方式继续读取 `config.json`。初始化开发配置可单独执行
`python3 scripts/prepare_canvas_dev.py`，该命令只生成配置并打印开发端口。

## 有声小说 TTS 配置

在根目录 `config.json` 的 `tts.provider` 中切换引擎，修改后重启开发服务：

- `mimo_tts`：使用普通 MiMo TTS，默认「茉莉」女声，流式输出 24kHz PCM。
  密钥、接口地址、模型、音色、表演风格和超时分别位于 `tts.mimo_tts.api_key`、
  `base_url`、`model`、`voice`、`style` 和 `timeout_seconds`。模型为 `mimo-v2.5-tts`。
- `mimo_voicedesign`：使用 VoiceDesign，自定义女声音色描述位于
  `tts.mimo_voicedesign.voice_description`，模型位于同级的 `model`
  （`mimo-v2.5-tts-voicedesign`）。该区块独立配置密钥、接口地址和超时。
  关闭正文润色，完整传入原文；接口采用流式兼容模式，整行生成完后返回音频。
- `iflytek_xtts`：使用原有讯飞离线引擎，输出 16kHz PCM。`tts.iflytek_xtts` 下的
  `sdk_dir`、`app_id`、`api_key`、`api_secret`、`vcn`、`language`、
  `sample_rate` 配置继续保留；其中 `sample_rate` 为讯飞的 `16000`。

三个区块分别为 `tts.mimo_tts`、`tts.mimo_voicedesign`、`tts.iflytek_xtts`，
各自包含完整参数，包括 `audio_format` 和 `sample_rate`；运行时只读取选中的区块。
管理员可在前端「账户 → 朗读设置」编辑普通 TTS 的 `style` 和 VoiceDesign 的
`voice_description`。保存会原样写回 `config.json`，新发起的合成请求立即使用
新描述，无需重启；已播放或已预取的音频保持原样。该设置对所有用户生效，
普通用户无法读取或修改此管理接口，接口只返回两个可编辑字段。
讯飞 SDK 位于 `backend/vendor/iflytek_xtts`，原始安装包保留为
`backend/vendor/iflytek_xtts-sdk.zip`。SDK 与授权文件沿用本地忽略规则。
worker 通过所配置 SDK 的 `libs` 加载动态库，并以 SDK 目录为工作目录。
重新构建 worker 时执行以下命令，构建产物使用相对于 worker 的库路径：

```bash
bash scripts/build_xtts_worker.sh
```

切换只需改 `provider`，采样率由所选引擎确定。配置示例见 `config.json.example`；
真实密钥保存在已忽略的 `config.json` 中。MiMo 通过项目 `BaseLLMProvider`
调用，正文完整传入；普通 TTS 音频块经后端流式转发，前端用 Web Audio 边收边播。
所有朗读引擎按正文换行逐段请求，跳过空行和纯标点行。普通 MiMo TTS 使用固定预置
音色并流式播放；VoiceDesign 和讯飞沿用各自合成方式。点击章节播放从章首开始，
点击行内播放从所选段读到章末。超过 2000 字符的单段按完整句子分成若干请求，
这些音频共用该段高亮，原文完整按顺序提交。

后台串行接收音频：一段的响应完全接收后立即请求下一段，持续推进至章末，
不等待播放进度。缓存可覆盖当前章节剩余全部音频，以原始 PCM 存于浏览器内存，
播放完即释放。高亮在实际开始播放每段时切换，暂停与倍速无需估算文字时间。
下一段已有可播放音频时，段间停顿 0.5 秒；同一超长段内的分块不额外停顿。
后续请求核对正文版本，正文变化时提示重新开始。后台失败保留更早段落正常播放，
轮到失败段时上报，不自动重试。停止、切章和关闭阅读器取消请求并释放缓存。
章节播放按钮从本地保存的中断段落开头续播，点击行内播放可指定新起点。进度按作品和
章节分别保存在浏览器，关闭阅读器或刷新后保留，只记录实际播放到的段落，预取不推进
进度。章节播放完成后清除该章位置；记录对应正文行已变化时从章首开始。Android 系统
暂停后继续保留原音频位置。
章节播完后按章节顺序继续播放下一章。
Web Audio 倍速会随速度改变音高。

相关回归测试：

```bash
backend/.venv/bin/pytest backend/tests/test_tts_provider.py backend/tests/test_audiobook_api.py backend/tests/test_audiobook_text.py backend/tests/test_xtts_protocol.py backend/tests/test_llm_base.py backend/tests/test_llm_extra_headers.py backend/tests/test_llm_raw_log.py -q
cd frontend && npm test -- src/lib/audiobook.test.js src/lib/audiobookChunks.test.js src/lib/audiobookPlayback.test.js src/lib/audiobookStream.test.js src/components/nodes/ChapterAudiobook.test.jsx
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

## 任务清单与评审

Supervisor 在本轮上下文中完成需求分析，并用独立 todolist 安排工作。长期要求通过笔记节点保存，一次性修改留在当轮任务中。结构化需求验收、分析产物授权和快照 ID 前置条件已经退出；章节正文保存仍校验内容版本，Reviewer 与评审准则继续生效。历史分析产物保留在库中，不再参与新的执行授权。

## LangSmith Trace

```bash
python scripts/fetch_latest_trace.py
```

## 节点类型与数据清理

支持 `chapter`、`character`、`worldbuilding`、`note`、`reviewer_note` 五种节点。
章节直接归属作品，按作品内 `sort_order` 排序；长期故事方向保存到笔记，逐章设计保存到章节笔记和章节元素。

升级时先停止服务，再手动运行 `backend/.venv/bin/python scripts/remove_structure_nodes.py`，最后按现有方式启动服务。
该命令在单个事务中保留原层级的章节阅读顺序，删除大纲、卷、情节节点、相关连线与操作记录，
清理历史画布快照并更新快照计数，同时移除旧章节结构绑定列。章节正文、笔记与角色资料保留。重复运行不会再次调整章节顺序。
此命令读取当前环境的数据库配置，清理不会在服务启动时自动执行。
