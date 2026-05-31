---
name: novel-agent-e2e
description: Run and assess the /root/Novel project's agent-driven novel creation workflow end to end. Use when the user asks Codex to continue prior Novel testing work, test the frontend-equivalent agent conversation flow, create a novel through the backend supervisor, inspect LangSmith traces with scripts/fetch_latest_trace.py, judge chapter coherence and outline adherence, or diagnose failures in the Novel agent writing pipeline.
---

# Novel Agent E2E

## Purpose

Use this skill to execute the Novel project like a real frontend user, then evaluate both execution quality and generated fiction quality. The target project is usually `/root/Novel`.

## Working Rules

- Treat existing uncommitted changes as user work. Inspect them before editing and never revert unrelated changes.
- Do not start with code changes. First reconstruct current state, confirm services, run or resume the E2E flow, then diagnose.
- Prefer evidence from generated chapters, backend logs, and LangSmith traces over assumptions.
- Keep user updates short and factual. Long-running generation can take minutes.

## State Recovery

1. Read the referenced Claude/Codex transcript if provided. Extract the latest user goal, commands run, output files, generated work IDs, session IDs, and failure points.
2. Check `/root/Novel` status:

```bash
git -C /root/Novel status --short
ps -ef | rg 'test_novel|uvicorn|vite|node'
ss -ltnp
```

3. Inspect relevant logs and task outputs before rerunning:

```bash
tail -160 /root/Novel/.run/backend-prod.log
tail -160 /root/Novel/.run/backend-dev.log
find /tmp -path '*-root-Novel*tasks*' -type f -printf '%p %s bytes\n'
```

## E2E Flow

Use the same behavioral flow as the frontend:

1. Ensure backend is serving the API port used by the test script, commonly `9002` for production or `9001` for dev. Confirm with `/health`.
2. Login or register the test user.
3. Generate a new outline through `/api/works/generate-outline-stream`.
4. Start supervisor with `work_id`, `auto_mode=true`, and a writing request such as `请帮我写第一章，根据大纲开始创作`.
5. Resume the same supervisor session for the next chapter, such as `请继续写第二章`.
6. Fetch work details, chapter list, and chapter contents.
7. Run trace inspection with `python scripts/fetch_latest_trace.py` after a meaningful supervisor run.

Prefer existing scripts when present:

```bash
python scripts/test_novel_creation.py
python scripts/test_novel_e2e.py
python scripts/fetch_latest_trace.py
```

If a script disconnects during streaming, inspect backend logs around the timestamp before treating it as an agent failure. A uvicorn reload or child-process restart can produce `Response ended prematurely`.

## Quality Review

Assess generated chapters manually. Focus on:

- Chapter-to-chapter continuity: protagonist state, location, conflict, timing, and unresolved hooks should carry forward.
- Outline adherence: chapter events should map to current timeline nodes, branches, character arcs, and foreshadowing.
- Long-form readiness: avoid isolated set pieces that ignore future structure; look for reusable facts, stakes, and character state.
- Prose quality: scene clarity, pacing, sensory detail, dialogue purpose, repeated phrasing, and genre fit.
- Execution quality: agent should use relevant tools, avoid bypassing todo workflow, save chapters, and evaluate when requested.

For a detailed checklist, read `references/quality-checklist.md`.

## Failure Triage

- API auth failure: register the test user or verify credentials in the script.
- Health check failure: inspect `.run/*.log`, port listeners, and database readiness.
- SSE `Response ended prematurely`: correlate with uvicorn reloads, process death, proxy timeout, or backend exception.
- `work_id 未在 configurable 中提供`: the conversation was not bound to a work; do not judge chapter-writing quality from that run.
- Empty trace: verify `config.json` has LangSmith settings and that a recent supervisor run occurred.
- Test failures that show PostgreSQL `OperationalError`: report environment/database connectivity separately from agent quality.

## Reporting

Final reports should include:

- What was run: commands/scripts, API port, work ID, supervisor session ID when available.
- Whether the E2E flow completed.
- Generated chapter count and chapter lengths.
- Quality judgment with concrete chapter evidence.
- Trace/execution observations: important tool calls, missed tools, retries, errors.
- Clear next action: rerun, fix infra, adjust prompts/tools, or accept current quality.
