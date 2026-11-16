"""Install the audiobook media plugin into the generated Android project."""
from pathlib import Path
import shutil

root = Path(__file__).resolve().parent.parent
android = root / "frontend/android/app/src/main"
java = android / "java/com/liyicheng/novel"
shutil.copyfile(root / "frontend/android-native/AudiobookMediaPlugin.java", java / "AudiobookMediaPlugin.java")

activity = java / "MainActivity.java"
text = activity.read_text(encoding="utf-8")
registration = "        registerPlugin(AudiobookMediaPlugin.class);"
if registration not in text:
    marker = "        super.onCreate(savedInstanceState);"
    if marker not in text:
        raise RuntimeError("MainActivity 缺少插件注册位置")
    text = text.replace(marker, registration + "\n" + marker, 1)
    activity.write_text(text, encoding="utf-8")

manifest = android / "AndroidManifest.xml"
text = manifest.read_text(encoding="utf-8")
receiver = '<receiver android:name=".AudiobookMediaPlugin$ActionReceiver" android:exported="false" />'
if receiver not in text:
    marker = "    </application>"
    if marker not in text:
        raise RuntimeError("AndroidManifest 缺少 application 节点")
    text = text.replace(marker, "        " + receiver + "\n" + marker, 1)
    manifest.write_text(text, encoding="utf-8")
