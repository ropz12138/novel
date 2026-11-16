"""Length-prefixed subprocess client for the offline XTTS worker."""
from __future__ import annotations

import os
import struct
import subprocess
import threading
from pathlib import Path

_ERROR_MARK = 0xFFFFFFFF


class XttsEngine:
    def __init__(self, command: list[str], env: dict[str, str], cwd: str):
        self._command = command
        self._env = env
        self._cwd = cwd
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    @classmethod
    def from_settings(cls, settings) -> "XttsEngine":
        sdk_dir = Path(settings.tts_sdk_dir)
        worker = Path(settings.tts_worker_path)
        if not worker.is_file():
            raise RuntimeError(f"xtts worker is missing: {worker}")
        if not sdk_dir.is_dir():
            raise RuntimeError(f"xtts sdk dir is missing: {sdk_dir}")
        libs = str(sdk_dir / "libs")
        env = os.environ.copy()
        previous = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = libs if not previous else f"{libs}:{previous}"
        env["XTTS_APP_ID"] = settings.tts_app_id
        env["XTTS_API_KEY"] = settings.tts_api_key
        env["XTTS_API_SECRET"] = settings.tts_api_secret
        env["XTTS_WORK_DIR"] = str(sdk_dir)
        env["XTTS_VCN"] = settings.tts_vcn
        env["XTTS_LANGUAGE"] = str(settings.tts_language)
        return cls([str(worker)], env, str(sdk_dir))

    def synthesize(self, text: str) -> bytes:
        if text == "":
            raise ValueError("text is empty")
        payload = text.encode("utf-8")
        if len(payload) > 1_000_000:
            raise ValueError("text is too long")
        with self._lock:
            proc = self._ensure()
            try:
                proc.stdin.write(struct.pack("<I", len(payload)) + payload)
                proc.stdin.flush()
                size = struct.unpack("<I", self._read_exact(proc, 4))[0]
                if size == _ERROR_MARK:
                    err_len = struct.unpack("<I", self._read_exact(proc, 4))[0]
                    message = self._read_exact(proc, err_len).decode("utf-8")
                    raise RuntimeError(message)
                pcm = self._read_exact(proc, size)
            except Exception:
                self.close()
                raise
        if len(pcm) == 0 or len(pcm) % 2 != 0:
            raise RuntimeError("XTTS returned invalid pcm")
        return pcm

    def close(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None or proc.poll() is not None:
            if proc is not None:
                proc.wait(timeout=1)
            return
        try:
            proc.stdin.write(struct.pack("<I", 0))
            proc.stdin.flush()
            proc.wait(timeout=3)
        except Exception:
            proc.kill()
            proc.wait(timeout=3)

    def _ensure(self) -> subprocess.Popen:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        self._proc = subprocess.Popen(
            self._command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=self._env or None,
            cwd=self._cwd,
        )
        return self._proc

    def _read_exact(self, proc: subprocess.Popen, size: int) -> bytes:
        chunks = []
        remaining = size
        while remaining:
            chunk = proc.stdout.read(remaining)
            if not chunk:
                raise RuntimeError("xtts worker exited")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)


_engine: XttsEngine | None = None
_engine_lock = threading.Lock()


def synthesize_speech(text: str) -> bytes:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                from config import settings
                _engine = XttsEngine.from_settings(settings)
    return _engine.synthesize(text)
