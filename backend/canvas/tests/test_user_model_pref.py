"""用户模型偏好对 LLM 的影响测试 — TDD。

- get_llm(primary=, fallback=) 覆盖 config 默认
- get_llm 未传偏好时回退 config 默认
- SupervisorAgent._load_model_pref 从 user 表读取偏好
- SupervisorAgent._build_graph 把偏好传给 get_llm
"""
import importlib

from app import database
from app.config import settings
from app.models.user import User
from app.models.work import CanvasWork

llm_mod = importlib.import_module("app.services.agents.llm")
supervisor_mod = importlib.import_module("app.services.agents.supervisor")


def _make_user(db, **kw):
    user = User(username="u", email="u@u.u", password_hash="x", **kw)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ---------- get_llm 覆盖 ----------

def test_get_llm_uses_config_defaults_when_no_pref():
    llm = llm_mod.get_llm(temperature=0.1, streaming=False)
    assert llm_mod.settings.default_model in (llm._primary.model_name, llm.model_name)


def test_get_llm_user_primary_overrides_default():
    target = next(m for m in settings.available_models if m != settings.default_model)
    llm = llm_mod.get_llm(temperature=0.1, streaming=False, primary=target)
    assert llm._primary.model_name == target


def test_get_llm_user_fallback_overrides_default():
    primary = settings.available_models[0]
    fallback = settings.available_models[1]
    llm = llm_mod.get_llm(temperature=0.1, streaming=False,
                          primary=primary, fallback=fallback)
    assert llm._fallback.model_name == fallback


def test_get_llm_null_fallback_falls_back_to_config():
    primary = settings.available_models[0]
    # fallback=None（未设置）→ 用 config 默认备模型
    llm = llm_mod.get_llm(temperature=0.1, streaming=False, primary=primary, fallback=None)
    assert llm._fallback.model_name == settings.fallback_model


# ---------- SupervisorAgent 偏好读取 ----------

def test_supervisor_load_model_pref_reads_user():
    db = database.SessionLocal()
    try:
        user = _make_user(db, primary_model="mimo-v2.5-pro", fallback_model="deepseek-v4-flash")
        agent = supervisor_mod.SupervisorAgent()
        pref = agent._load_model_pref(user.id)
        assert pref == {"primary": "mimo-v2.5-pro", "fallback": "deepseek-v4-flash"}
    finally:
        db.close()


def test_supervisor_load_model_pref_none_when_unset():
    db = database.SessionLocal()
    try:
        user = _make_user(db)
        agent = supervisor_mod.SupervisorAgent()
        pref = agent._load_model_pref(user.id)
        assert pref == {"primary": None, "fallback": None}
    finally:
        db.close()


def test_supervisor_build_graph_passes_pref_to_get_llm(monkeypatch):
    captured = {}

    def fake_get_llm(temperature=0.5, streaming=True, model_name=None, primary=None, fallback=None):
        captured["primary"] = primary
        captured["fallback"] = fallback
        # 返回真实 get_llm 保证后续构建不报错
        return llm_mod.get_llm(temperature=temperature, streaming=streaming,
                               model_name=model_name, primary=primary, fallback=fallback)

    monkeypatch.setattr(supervisor_mod, "get_llm", fake_get_llm)

    agent = supervisor_mod.SupervisorAgent()
    agent._build_graph(model_pref={"primary": "deepseek-v4-pro", "fallback": "deepseek-v4-flash"})

    assert captured["primary"] == "deepseek-v4-pro"
    assert captured["fallback"] == "deepseek-v4-flash"


def test_context_model_pref_kwargs_reads_supervisor_context():
    supervisor_mod.set_context({
        "model_pref": {"primary": "mimo-v2.5-pro", "fallback": "deepseek-v4-flash"},
    })
    try:
        kw = llm_mod.context_model_pref_kwargs()
        assert kw == {"primary": "mimo-v2.5-pro", "fallback": "deepseek-v4-flash"}
    finally:
        supervisor_mod.set_context({})


def test_context_model_pref_kwargs_empty_when_unset():
    supervisor_mod.set_context({})
    try:
        assert llm_mod.context_model_pref_kwargs() == {}
    finally:
        supervisor_mod.set_context({})


def test_supervisor_build_graph_no_pref_passes_none(monkeypatch):
    captured = {}

    def fake_get_llm(temperature=0.5, streaming=True, model_name=None, primary=None, fallback=None):
        captured["primary"] = primary
        captured["fallback"] = fallback
        return llm_mod.get_llm(temperature=temperature, streaming=streaming)

    monkeypatch.setattr(supervisor_mod, "get_llm", fake_get_llm)

    agent = supervisor_mod.SupervisorAgent()
    agent._build_graph(model_pref=None)

    assert captured["primary"] is None
    assert captured["fallback"] is None
