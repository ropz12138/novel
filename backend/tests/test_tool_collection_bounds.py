import pytest
from pydantic import ValidationError

from services.agents.tools.character_relation_tools import QueryCharacterRelationsInput
from services.agents.tools.node_tools import BatchCreateEdgesInput, BatchCreateNodesInput
from services.agents.tools.node_reference_tools import CreateNodeReferencesInput
from services.agents.tools.query_tools import (
    CanvasIndexInput,
    ListUserCanvasActionsInput,
    QueryEdgesInput,
    QueryNodesInput,
)
from services.agents.tools.research_tools import (
    ListResearchArtifactsInput,
    ReadResearchArtifactsInput,
)


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        (QueryNodesInput, {"limit": 51}),
        (QueryEdgesInput, {"limit": 51}),
        (CanvasIndexInput, {"node_limit": 51}),
        (CanvasIndexInput, {"edge_limit": 51}),
        (ListUserCanvasActionsInput, {"limit": 51}),
        (QueryCharacterRelationsInput, {"limit": 51}),
        (ListResearchArtifactsInput, {"limit": 51}),
        (ReadResearchArtifactsInput, {"artifact_ids": [str(i) for i in range(6)]}),
        (BatchCreateNodesInput, {"nodes_data": []}),
        (BatchCreateEdgesInput, {"edges_data": [{} for _ in range(21)]}),
        (CreateNodeReferencesInput, {"references": [{"node_id": str(i), "quote": "x"} for i in range(11)]}),
    ],
)
def test_collection_tools_reject_requests_outside_declared_bounds(schema, payload):
    with pytest.raises(ValidationError):
        schema.model_validate(payload)


def test_canvas_index_exposes_explicit_pagination():
    data = CanvasIndexInput.model_validate({})
    assert data.node_offset == 0
    assert data.node_limit == 50
    assert data.edge_offset == 0
    assert data.edge_limit == 50
