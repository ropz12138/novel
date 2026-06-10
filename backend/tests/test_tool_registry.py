"""测试 Supervisor / 子 Agent 工具工厂 — enable_todolist & enable_evaluation 开关"""

import sys

sys.path.insert(0, "/root/Novel/backend")


class TestBuildSupervisorTools:
    QUERY_TOOLS = {
        "query_characters",
        "query_chapters",
        "count_chapter_words",
        "query_chapter_meta",
        "grep_chapter_meta",
        "grep",
        "read_outline",
        "query_outline_related_chapters",
        "read_chapter",
        "query_characters_by_chapter",
        "grep_in_chapter",
        "query_macro_outline",
        "query_meso_outline",
        "query_micro_outline",
        "query_previous_chapters",
        "read_work_context",
        "read_chat_history",
        "read_requirements_doc",
        "update_requirements_doc",
    }

    TODOLIST_TOOLS = {
        "analyze_requirements",
        "update_task_status",
        "update_todolist_readiness",
        "edit_todolist",
        "execute_todo_task",
        "read_todolist",
    }

    DISPATCH_TOOLS = {
        "dispatch_outline",
        "dispatch_chapter",
        "dispatch_evaluation",
    }

    def _names(self, **kwargs):
        from app.services.supervisor.tool_registry import build_supervisor_tools

        return {t.name for t in build_supervisor_tools(**kwargs)}

    def test_default_both_off_uses_direct_dispatch_without_evaluation(self):
        names = self._names(enable_todolist=False, enable_evaluation=False)
        assert self.QUERY_TOOLS <= names
        assert "dispatch_outline" in names
        assert "dispatch_chapter" in names
        assert "dispatch_evaluation" not in names
        assert not (self.TODOLIST_TOOLS & names)
        assert not (self.DISPATCH_TOOLS - {"dispatch_outline", "dispatch_chapter"} & names - self.QUERY_TOOLS)

    def test_direct_with_evaluation(self):
        names = self._names(enable_todolist=False, enable_evaluation=True)
        assert "dispatch_evaluation" in names
        assert "dispatch_outline" in names
        assert not (self.TODOLIST_TOOLS & names)

    def test_todolist_without_evaluation(self):
        names = self._names(enable_todolist=True, enable_evaluation=False)
        assert self.TODOLIST_TOOLS <= names
        assert not (self.DISPATCH_TOOLS & names)

    def test_todolist_with_evaluation(self):
        names = self._names(enable_todolist=True, enable_evaluation=True)
        assert self.TODOLIST_TOOLS <= names
        assert not (self.DISPATCH_TOOLS & names)

    def test_tool_names_unique(self):
        from app.services.supervisor.tool_registry import build_supervisor_tools

        for kwargs in (
            {"enable_todolist": False, "enable_evaluation": False},
            {"enable_todolist": False, "enable_evaluation": True},
            {"enable_todolist": True, "enable_evaluation": False},
            {"enable_todolist": True, "enable_evaluation": True},
        ):
            tools = build_supervisor_tools(**kwargs)
            names = [t.name for t in tools]
            assert len(names) == len(set(names)), kwargs


class TestChildTodoTools:
    CHILD_TODO = {"create_child_todolist", "read_child_todolist", "update_child_task_status"}

    def test_outline_tools_respect_child_todo_flag(self):
        from app.services.supervisor.tool_registry import build_outline_tools

        off = {t.name for t in build_outline_tools(auto_mode=True, enable_child_todolist=False)}
        on = {t.name for t in build_outline_tools(auto_mode=True, enable_child_todolist=True)}
        assert not (self.CHILD_TODO & off)
        assert self.CHILD_TODO <= on

    def test_chapter_tools_respect_child_todo_flag(self):
        from app.services.supervisor.tool_registry import build_chapter_agent_tools

        off = {t.name for t in build_chapter_agent_tools(enable_child_todolist=False)}
        on = {t.name for t in build_chapter_agent_tools(enable_child_todolist=True)}
        assert not (self.CHILD_TODO & off)
        assert self.CHILD_TODO <= on

    def test_evaluation_tools_respect_child_todo_flag(self):
        from app.services.supervisor.tool_registry import build_evaluation_tools

        off = {t.name for t in build_evaluation_tools(enable_child_todolist=False)}
        on = {t.name for t in build_evaluation_tools(enable_child_todolist=True)}
        assert not (self.CHILD_TODO & off)
        assert self.CHILD_TODO <= on


class TestPromptBuilder:
    def test_direct_mode_excludes_todolist_rules(self):
        from app.services.supervisor.prompt_builder import build_supervisor_system_prompt

        prompt = build_supervisor_system_prompt(
            enable_todolist=False,
            enable_evaluation=False,
            work_context="测试",
            requirements_doc="无",
        )
        assert "execute_todo_task" not in prompt
        assert "dispatch_outline" in prompt
        assert "analyze_requirements" not in prompt

    def test_todolist_mode_includes_execute_todo_task(self):
        from app.services.supervisor.prompt_builder import build_supervisor_system_prompt

        prompt = build_supervisor_system_prompt(
            enable_todolist=True,
            enable_evaluation=True,
            work_context="测试",
            requirements_doc="无",
        )
        assert "execute_todo_task" in prompt
        assert "analyze_requirements" in prompt

    def test_evaluation_disabled_note_in_direct_mode(self):
        from app.services.supervisor.prompt_builder import build_supervisor_system_prompt

        prompt = build_supervisor_system_prompt(
            enable_todolist=False,
            enable_evaluation=False,
            work_context="测试",
            requirements_doc="无",
        )
        assert "评估功能未启用" in prompt

    def test_child_todolist_fragment_injected(self):
        from app.services.supervisor.prompt_builder import inject_child_todolist_sections

        with_todo = inject_child_todolist_sections("HEAD\n{child_todolist_tools}\nTAIL", enabled=True)
        without_todo = inject_child_todolist_sections("HEAD\n{child_todolist_tools}\nTAIL", enabled=False)
        assert "create_child_todolist" in with_todo
        assert "create_child_todolist" not in without_todo
