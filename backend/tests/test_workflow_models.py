from sqlalchemy import inspect

import database
from models.workflow import WorkflowArtifact, WorkflowRun


def test_workflow_tables_use_relational_columns_without_json_types():
    inspector = inspect(database.engine)
    assert "workflow_runs" in inspector.get_table_names()
    assert "workflow_artifacts" in inspector.get_table_names()

    for table in (WorkflowRun.__table__, WorkflowArtifact.__table__):
        type_names = {type(column.type).__name__.lower() for column in table.columns}
        assert "json" not in type_names
        assert "jsonb" not in type_names

