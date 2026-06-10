"""按 enable_todolist / enable_evaluation 组装 Supervisor 与子 Agent 提示词。"""

from __future__ import annotations

from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompt_templates"
FRAGMENTS_DIR = PROMPT_DIR / "fragments"


def _read(name: str) -> str:
    return (FRAGMENTS_DIR / name).read_text(encoding="utf-8").strip()


def _read_template(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def inject_evaluation_prompt_sections(template: str, *, enabled: bool) -> str:
    tools = _read("child_todolist_tools.txt") if enabled else ""
    workflow = _read(
        "evaluation_workflow_steps_enabled.txt" if enabled else "evaluation_workflow_steps_disabled.txt"
    )
    child_rules = _read("evaluation_child_rules.txt") if enabled else ""
    return (
        template.replace("{child_todolist_tools}", tools)
        .replace("{evaluation_workflow_steps}", workflow)
        .replace("{evaluation_child_rules}", child_rules)
    )


def inject_child_todolist_sections(template: str, *, enabled: bool, outline_auto: bool = False) -> str:
    tools = _read("child_todolist_tools.txt") if enabled else ""
    workflow = _read("child_todolist_workflow.txt") if enabled else ""
    outline_create = _read(
        "outline_create_steps_enabled.txt" if enabled else "outline_create_steps_disabled.txt"
    )
    if outline_auto:
        outline_edit = _read(
            "outline_edit_steps_enabled_auto.txt" if enabled else "outline_edit_steps_disabled_auto.txt"
        )
    else:
        outline_edit = _read(
            "outline_edit_steps_enabled.txt" if enabled else "outline_edit_steps_disabled.txt"
        )
    outline_child_rules = _read("outline_child_rules.txt") if enabled else ""
    return (
        template.replace("{child_todolist_tools}", tools)
        .replace("{child_todolist_workflow}", workflow)
        .replace("{outline_create_steps}", outline_create)
        .replace("{outline_edit_steps}", outline_edit)
        .replace("{outline_child_rules}", outline_child_rules)
        .replace("{child_todolist_workflow_create}", "")
        .replace("{child_todolist_workflow_edit}", "")
    )


def build_supervisor_system_prompt(
    *,
    enable_todolist: bool,
    enable_evaluation: bool,
    work_context: str,
    requirements_doc: str,
) -> str:
    base = _read_template("supervisor_base.txt")

    if enable_todolist:
        mode_role = _read("supervisor_todolist_role_header.txt")
        tools = _read("supervisor_todolist_tools.txt")
        rules = _read("supervisor_todolist_rules.txt")
        if enable_evaluation:
            rules += "\n" + _read("supervisor_evaluation_rules.txt")
        else:
            rules += "\n" + _read("supervisor_todolist_evaluation_disabled.txt")
    else:
        mode_role = ""
        direct = _read("supervisor_direct_dispatch.txt")
        eval_tool = _read("supervisor_direct_evaluation_tool.txt") if enable_evaluation else ""
        eval_action = _read("supervisor_direct_evaluation_action.txt") if enable_evaluation else ""
        eval_dispatch = _read("supervisor_direct_evaluation_dispatch.txt") if enable_evaluation else ""
        eval_disabled = "" if enable_evaluation else _read("supervisor_evaluation_disabled.txt")
        tools = (
            direct.replace("{dispatch_evaluation_tool}", eval_tool)
            .replace("{evaluation_action}", eval_action)
            .replace("{evaluation_dispatch}", eval_dispatch)
            .replace("{evaluation_disabled_rule}", eval_disabled)
        )
        rules = ""

    return base.format(
        mode_specific_role=mode_role,
        mode_specific_tools=tools,
        mode_specific_rules=rules,
        work_context=work_context,
        requirements_doc=requirements_doc,
    )


def build_requirements_planner_prompt(*, enable_evaluation: bool) -> str:
    base = _read_template("requirements_planner.txt")
    if enable_evaluation:
        return base
    return base + "\n\n" + _read("requirements_planner_no_evaluation.txt")
