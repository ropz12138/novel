from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STYLES_PATH = PROJECT_ROOT / "frontend/android/app/src/main/res/values/styles.xml"
MAIN_ACTIVITY_PATH = (
    PROJECT_ROOT
    / "frontend/android/app/src/main/java/com/liyicheng/novel/MainActivity.java"
)


def replace_once(source: str, old: str, new: str, path: Path) -> str:
    if old not in source:
        raise RuntimeError(f"无法在 {path} 中定位 Android 系统栏配置插入点")
    return source.replace(old, new, 1)


def configure_styles() -> None:
    styles = STYLES_PATH.read_text(encoding="utf-8")
    if "android:windowLightStatusBar" not in styles:
        styles = replace_once(
            styles,
            '        <item name="android:background">@null</item>',
            '        <item name="android:background">@null</item>\n'
            '        <item name="android:statusBarColor">@android:color/transparent</item>\n'
            '        <item name="android:windowLightStatusBar">true</item>\n'
            '        <item name="android:navigationBarColor">@android:color/white</item>\n'
            '        <item name="android:windowLightNavigationBar">true</item>',
            STYLES_PATH,
        )
    if "postSplashScreenTheme" not in styles:
        styles = replace_once(
            styles,
            '        <item name="android:background">@drawable/splash</item>',
            '        <item name="android:background">@drawable/splash</item>\n'
            '        <item name="postSplashScreenTheme">@style/AppTheme.NoActionBar</item>',
            STYLES_PATH,
        )
    STYLES_PATH.write_text(styles, encoding="utf-8")


def configure_main_activity() -> None:
    source = MAIN_ACTIVITY_PATH.read_text(encoding="utf-8")
    if "android.graphics.Color" not in source:
        source = replace_once(
            source,
            "import android.os.Bundle;",
            "import android.graphics.Color;\nimport android.os.Bundle;",
            MAIN_ACTIVITY_PATH,
        )
    if "WindowInsetsControllerCompat" not in source:
        source = replace_once(
            source,
            "import com.getcapacitor.BridgeActivity;",
            "import com.getcapacitor.BridgeActivity;\n\n"
            "import androidx.core.view.WindowCompat;\n"
            "import androidx.core.view.WindowInsetsControllerCompat;",
            MAIN_ACTIVITY_PATH,
        )
    if "setAppearanceLightStatusBars" not in source:
        source = replace_once(
            source,
            "        super.onCreate(savedInstanceState);",
            "        super.onCreate(savedInstanceState);\n\n"
            "        getWindow().setStatusBarColor(Color.TRANSPARENT);\n"
            "        getWindow().setNavigationBarColor(Color.WHITE);\n"
            "        WindowInsetsControllerCompat insetsController = WindowCompat.getInsetsController(\n"
            "            getWindow(),\n"
            "            getWindow().getDecorView()\n"
            "        );\n"
            "        insetsController.setAppearanceLightStatusBars(true);\n"
            "        insetsController.setAppearanceLightNavigationBars(true);",
            MAIN_ACTIVITY_PATH,
        )
    MAIN_ACTIVITY_PATH.write_text(source, encoding="utf-8")


def main() -> None:
    configure_styles()
    configure_main_activity()


if __name__ == "__main__":
    main()
