# Novel Agent E2E Quality Checklist

## Execution Evidence

Collect:

- Test script output.
- Work ID and supervisor session ID.
- Backend log lines around supervisor start/resume.
- Latest LangSmith trace from `scripts/fetch_latest_trace.py`.
- Full chapter text for at least the first two generated chapters.

## Agent Process Checks

Good signs:

- Reads work context and outline before writing.
- Uses `analyze_requirements` to create a todolist.
- Executes chapter tasks through `execute_todo_task`.
- Saves chapters with expected chapter numbers.
- Evaluates or revises when the todolist requires it.
- Does not reopen terminal failed/completed tasks to bypass the workflow.

Risk signs:

- Writes without reading outline or existing chapters.
- Changes requested chapter numbers without confirmation.
- Treats an existing chapter as permission to create the next chapter.
- Calls outline/chapter tools when no work is bound.
- Produces final text but does not save a chapter.
- Backend reloads or process death interrupt streaming.

## Chapter Continuity

Check:

- The second chapter starts from the prior chapter's ending state or explains the transition.
- Character goals, injuries, knowledge, inventory, relationships, and location remain consistent.
- New conflicts grow from previous events instead of resetting the story.
- Foreshadowed items remain visible without being prematurely forgotten.

Rate:

- Strong: continuity is explicit and useful for long-form progression.
- Adequate: no contradiction, but some transitions are generic.
- Weak: chapter feels standalone or contradicts prior facts.

## Outline Adherence

Check:

- Identify which timeline node each chapter implements.
- Identify branch and foreshadowing elements used.
- Confirm core premise, genre, protagonist arc, and major supporting characters match the outline.
- Note any invented direction that conflicts with the outline.

Rate:

- Strong: chapter dramatizes outline nodes while adding scene-level detail.
- Adequate: broadly follows outline but misses some branch/foreshadowing opportunities.
- Weak: mostly ignores outline, changes major premise, or advances wrong plot stage.

## Prose And Long-Form Quality

Check:

- Opening hook has concrete scene pressure.
- Scenes contain action, decision, consequence, and sensory grounding.
- Dialogue reveals conflict or character, not just exposition.
- The protagonist solves problems in a way consistent with the premise.
- Ending creates a next-chapter vector.
- Avoids repetitive sentence patterns, empty grandeur, and summary-heavy pacing.

## Report Template

```markdown
**Run**
- Script:
- API:
- Work:
- Session:
- Result:

**Generated Content**
- Chapters:
- Lengths:

**Execution Quality**
- Trace/tool summary:
- Failures or warnings:

**Fiction Quality**
- Continuity:
- Outline adherence:
- Prose/scene quality:

**Verdict**
- Pass/needs rerun/needs fix:
- Next step:
```
