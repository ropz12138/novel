#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
CONFIG_FILE="$ROOT_DIR/config.json"

if [ ! -f "$CONFIG_FILE" ]; then
  echo "缺少配置文件: $CONFIG_FILE"
  exit 1
fi

for command_name in node npm java python3; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "缺少打包依赖: $command_name"
    exit 1
  fi
done

mapfile -t APP_VALUES < <(python3 -c '
import json, pathlib
config = json.loads(pathlib.Path("'"$CONFIG_FILE"'").read_text(encoding="utf-8"))
mobile = config["app"]["mobile"]
print(mobile["android_build_variant"])
print(mobile["apk_filename"])
print(mobile["version_name"])
print(mobile["apk_publish_path"])
print(mobile["android_java_home"])
print(mobile["android_sdk_root"])
print(mobile["android_compile_sdk"])
')

BUILD_VARIANT="${APP_VALUES[0]}"
APK_FILENAME="${APP_VALUES[1]}"
VERSION_NAME="${APP_VALUES[2]}"
APK_PUBLISH_PATH="${APP_VALUES[3]}"
ANDROID_JAVA_HOME="${APP_VALUES[4]}"
ANDROID_SDK_ROOT="${APP_VALUES[5]}"
ANDROID_COMPILE_SDK="${APP_VALUES[6]}"

if [ ! -x "$ANDROID_JAVA_HOME/bin/java" ]; then
  echo "config.json 中的 android_java_home 无效: $ANDROID_JAVA_HOME"
  exit 1
fi

export JAVA_HOME="$ANDROID_JAVA_HOME"
export PATH="$JAVA_HOME/bin:$PATH"

SDKMANAGER="$ANDROID_SDK_ROOT/cmdline-tools/latest/bin/sdkmanager"
if [ ! -x "$SDKMANAGER" ]; then
  echo "config.json 中的 android_sdk_root 无效: $ANDROID_SDK_ROOT"
  exit 1
fi

export ANDROID_HOME="$ANDROID_SDK_ROOT"
export ANDROID_SDK_ROOT
export PATH="$ANDROID_SDK_ROOT/platform-tools:$ANDROID_SDK_ROOT/cmdline-tools/latest/bin:$PATH"

if [ ! -d "$ANDROID_SDK_ROOT/platforms/android-$ANDROID_COMPILE_SDK" ]; then
  echo "安装 Android SDK Platform $ANDROID_COMPILE_SDK..."
  "$SDKMANAGER" "platforms;android-$ANDROID_COMPILE_SDK"
fi

python3 -c '
import json, pathlib
root = pathlib.Path("'"$ROOT_DIR"'")
project = json.loads((root / "config.json").read_text(encoding="utf-8"))
mobile = project["app"]["mobile"]
capacitor = {
    "appId": mobile["app_id"],
    "appName": mobile["app_name"],
    "webDir": "dist",
    "android": {"allowMixedContent": False},
}
(root / "frontend" / "capacitor.config.json").write_text(
    json.dumps(capacitor, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
'

case "$BUILD_VARIANT" in
  debug)
    GRADLE_TASK="assembleDebug"
    GENERATED_APK="$FRONTEND_DIR/android/app/build/outputs/apk/debug/app-debug.apk"
    ;;
  release)
    GRADLE_TASK="assembleRelease"
    GENERATED_APK="$FRONTEND_DIR/android/app/build/outputs/apk/release/app-release.apk"
    ;;
  *)
    echo "android_build_variant 只允许 debug 或 release"
    exit 1
    ;;
esac

cd "$FRONTEND_DIR"

# public 目录会被 Vite 原样复制进 App。这里清除旧版本遗留的安装包，
# 避免 APK 被再次打包进新 APK，导致每次构建后体积递归增长。
rm -f \
    "$FRONTEND_DIR/public/download" \
    "$FRONTEND_DIR/public/$APK_FILENAME" \
    "$FRONTEND_DIR/dist/download" \
    "$FRONTEND_DIR/dist/$APK_FILENAME" \
    "$FRONTEND_DIR/android/app/src/main/assets/public/download" \
    "$FRONTEND_DIR/android/app/src/main/assets/public/$APK_FILENAME"

npm install
npm run build:app

if [ ! -d "$FRONTEND_DIR/android" ]; then
  npx cap add android
fi

printf 'sdk.dir=%s\n' "$ANDROID_SDK_ROOT" > "$FRONTEND_DIR/android/local.properties"

python3 "$ROOT_DIR/scripts/configure_android_version.py"
python3 "$ROOT_DIR/scripts/generate_android_icons.py"
npx cap sync android
python3 "$ROOT_DIR/scripts/configure_android_app_name.py"
python3 "$ROOT_DIR/scripts/configure_android_system_bars.py"

cd "$FRONTEND_DIR/android"
./gradlew "$GRADLE_TASK"

if [ ! -f "$GENERATED_APK" ]; then
  echo "Android 构建完成，但未找到 APK: $GENERATED_APK"
  exit 1
fi

mkdir -p "$FRONTEND_DIR/public" "$FRONTEND_DIR/dist" "$ROOT_DIR/deploy/novel" "$ROOT_DIR/artifacts"
install -m 0644 "$GENERATED_APK" "$FRONTEND_DIR/dist/$APK_FILENAME"
install -m 0644 "$GENERATED_APK" "$ROOT_DIR/deploy/novel/$APK_FILENAME"
install -m 0644 "$GENERATED_APK" "$ROOT_DIR/artifacts/$APK_FILENAME"
mkdir -p "$(dirname "$APK_PUBLISH_PATH")"
install -m 0644 "$GENERATED_APK" "$APK_PUBLISH_PATH"

echo "APK 打包完成"
echo "版本: $VERSION_NAME"
echo "产物: $GENERATED_APK"
echo "下载路由文件: $ROOT_DIR/deploy/novel/$APK_FILENAME"
echo "线上发布文件: $APK_PUBLISH_PATH"
