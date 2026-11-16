"""系统级朗读描述：原样保存到配置文件，更新当前进程的合成参数。"""
import json
import os
import stat
import tempfile
import threading
from pathlib import Path

import config
from schemas.tts_settings import TtsSettings

_lock = threading.Lock()


def read_tts_settings() -> TtsSettings:
    with _lock:
        data = json.loads(config.CONFIG_PATH.read_text(encoding="utf-8"))["tts"]
        return TtsSettings(
            mimo_tts={"style": data["mimo_tts"]["style"]},
            mimo_voicedesign={"voice_description": data["mimo_voicedesign"]["voice_description"]},
        )


def save_tts_settings(payload: TtsSettings) -> TtsSettings:
    with _lock:
        path = config.CONFIG_PATH
        data = json.loads(path.read_text(encoding="utf-8"))
        data["tts"]["mimo_tts"]["style"] = payload.mimo_tts.style
        data["tts"]["mimo_voicedesign"]["voice_description"] = payload.mimo_voicedesign.voice_description
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix=".tts-settings-", delete=False) as fp:
                temporary = Path(fp.name)
                json.dump(data, fp, ensure_ascii=False, indent=2)
                fp.write("\n")
                fp.flush()
                os.fsync(fp.fileno())
            temporary.chmod(stat.S_IMODE(path.stat().st_mode))
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        config.settings.tts_style = payload.mimo_tts.style
        config.settings.tts_voice_description = payload.mimo_voicedesign.voice_description
        return payload
