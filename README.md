# Novel

画布单 Agent 小说创作系统。

## Structure

- `frontend`: React 前端（Canvas 画布 + Supervisor 聊天）
- `backend`: FastAPI 后端（画布 API + 单 Agent Supervisor）
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
