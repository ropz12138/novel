"""需求文档 REST 更新接口测试。"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.work_service import WorkService

client = TestClient(app)


def test_requirements_doc_update_route_registered():
    response = client.post("/api/works/requirements-doc/update", json={})
    assert response.status_code != 404


class TestWorkServiceUpdateRequirementsDoc:
    def test_update_requirements_doc_persists_content(self):
        service = WorkService()
        mock_db = MagicMock()
        mock_work = MagicMock()
        mock_work.requirements_doc = "旧内容"
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_work

        result = service.update_requirements_doc(
            "work-1",
            "用户要求：第三人称叙事",
            mock_db,
            user_id="user-1",
        )

        assert mock_work.requirements_doc == "用户要求：第三人称叙事"
        mock_db.commit.assert_called_once()
        assert result == {"content": "用户要求：第三人称叙事"}

    def test_update_requirements_doc_work_not_found(self):
        from fastapi import HTTPException

        service = WorkService()
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        with pytest.raises(HTTPException) as exc:
            service.update_requirements_doc("missing", "x", mock_db, user_id="user-1")
        assert exc.value.status_code == 404
