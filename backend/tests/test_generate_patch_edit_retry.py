"""Tests for generate_patch_edit JSON parsing and retry behavior."""

import pytest


class _Chunk:
    def __init__(self, content: str):
        self.content = content


class _FakePatchChain:
    def __init__(self, outputs: list[str]):
        self.outputs = list(outputs)
        self.calls = 0

    async def astream(self, inputs):
        output = self.outputs[self.calls]
        self.calls += 1
        yield _Chunk(output)


def test_parse_patch_json_valid():
    from app.services.supervisor.edit_chapter_tools import _parse_patch_json

    ops = _parse_patch_json(
        """```json
        {"edits": [{"type": "replace", "search": "旧句子", "content": "新句子"}]}
        ```"""
    )

    assert ops == [
        {
            "type": "replace",
            "search": "旧句子",
            "after": "",
            "content": "新句子",
        }
    ]


def test_parse_patch_json_invalid_raises_patchparseerror():
    from app.services.supervisor.edit_chapter_tools import PatchParseError, _parse_patch_json

    with pytest.raises(PatchParseError):
        _parse_patch_json('{"edits": [{"type": "replace", "search": "旧", "content": "新"}')


@pytest.mark.asyncio
async def test_patch_retry_recovers():
    from app.services.supervisor.edit_chapter_tools import _generate_patch_ops_with_retry

    emitted = []
    chain = _FakePatchChain([
        '{"edits": [{"type": "replace", "search": "旧", "content": "新"}',
        '{"edits": [{"type": "replace", "search": "旧", "content": "新"}]}',
    ])

    ops = await _generate_patch_ops_with_retry(
        chain=chain,
        base_inputs={"user_message": "替换一句话"},
        emit=lambda event, data: emitted.append((event, data)),
    )

    assert chain.calls == 2
    assert ops[0]["content"] == "新"
    retry_events = [event for event, _ in emitted if event == "edit_chapter_patch_retry"]
    assert len(retry_events) == 1


@pytest.mark.asyncio
async def test_patch_retry_exhausted():
    from app.services.supervisor.edit_chapter_tools import (
        MAX_PATCH_ATTEMPTS,
        PatchParseError,
        _generate_patch_ops_with_retry,
    )

    emitted = []
    chain = _FakePatchChain(["{bad json"] * MAX_PATCH_ATTEMPTS)

    with pytest.raises(PatchParseError):
        await _generate_patch_ops_with_retry(
            chain=chain,
            base_inputs={"user_message": "替换一句话"},
            emit=lambda event, data: emitted.append((event, data)),
        )

    assert chain.calls == MAX_PATCH_ATTEMPTS
    retry_events = [event for event, _ in emitted if event == "edit_chapter_patch_retry"]
    assert len(retry_events) == MAX_PATCH_ATTEMPTS
