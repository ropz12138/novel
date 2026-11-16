import sys
from pathlib import Path

from services.xtts_engine import XttsEngine


def test_worker_protocol_returns_pcm_for_one_line():
    fake = Path(__file__).resolve().parent / "fake_xtts_worker.py"
    engine = XttsEngine(command=[sys.executable, str(fake)], env={}, cwd=str(Path(__file__).parent))
    try:
        assert engine.synthesize("AB") == b"PCM:AB"
    finally:
        engine.close()


def test_worker_protocol_surfaces_engine_error():
    fake = Path(__file__).resolve().parent / "fake_xtts_worker.py"
    engine = XttsEngine(command=[sys.executable, str(fake)], env={}, cwd=str(Path(__file__).parent))
    try:
        try:
            engine.synthesize("失败")
        except RuntimeError as exc:
            assert str(exc) == "合成失败"
        else:
            raise AssertionError("expected RuntimeError")
    finally:
        engine.close()


def test_engine_uses_configured_vendor_directory_for_libraries_and_workdir(tmp_path):
    from types import SimpleNamespace
    sdk = tmp_path / 'vendor' / 'iflytek_xtts'
    (sdk / 'libs').mkdir(parents=True)
    worker = tmp_path / 'xtts_worker'
    worker.touch()
    engine = XttsEngine.from_settings(SimpleNamespace(
        tts_sdk_dir=str(sdk), tts_worker_path=str(worker),
        tts_app_id='app', tts_api_key='key', tts_api_secret='secret',
        tts_vcn='xiaoyan', tts_language=1,
    ))
    assert engine._cwd == str(sdk)
    assert engine._env['XTTS_WORK_DIR'] == str(sdk)
    assert engine._env['LD_LIBRARY_PATH'].split(':')[0] == str(sdk / 'libs')
