"""Tests for work user isolation: users can only access their own resources."""
import sys
sys.path.insert(0, "/root/Novel/backend")

from unittest.mock import MagicMock, patch

from app.core.auth import create_access_token


def _make_user(user_id, username="test"):
    user = MagicMock()
    user.id = user_id
    user.username = username
    return user


def _make_work(work_id, user_id, title="测试作品"):
    work = MagicMock()
    work.id = work_id
    work.user_id = user_id
    work.title = title
    work.genre = "玄幻"
    work.idea = ""
    work.tags = []
    work.outline_tree = {}
    work.status = "草稿"
    return work


class TestWorkListIsolation:
    """list_works should only return the current user's works."""

    def test_user_a_cannot_see_user_b_works(self):
        from app.services.work_service import WorkService

        user_a_id = "user-a-001"
        work_a = _make_work("work-a", user_a_id, "A 的作品")
        work_b = _make_work("work-b", "user-b-001", "B 的作品")

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = [work_a]

        service = WorkService()
        results = service.list_works(user_a_id, mock_db)

        assert len(results) == 1
        mock_db.query.return_value.filter_by.assert_called_with(user_id=user_a_id)

    def test_list_works_filters_by_user_id(self):
        from app.services.work_service import WorkService

        user_id = "user-123"
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = []

        service = WorkService()
        service.list_works(user_id, mock_db)

        mock_db.query.return_value.filter_by.assert_called_with(user_id=user_id)


class TestWorkAccessIsolation:
    """get_work / delete_work should verify work belongs to current user."""

    def test_get_work_belongs_to_user(self):
        from app.services.work_service import WorkService

        user_id = "user-123"
        work = _make_work("work-1", user_id)

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = work
        # get_work also queries characters, so set up chained mocks
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = []

        service = WorkService()
        result = service.get_work("work-1", user_id, mock_db)

        assert result.id == "work-1"

    def test_get_work_not_belong_to_user_raises_404(self):
        from app.services.work_service import WorkService
        from fastapi import HTTPException

        user_a_id = "user-a-001"
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        service = WorkService()
        try:
            service.get_work("work-belong-to-b", user_a_id, mock_db)
            assert False, "Should have raised 404"
        except HTTPException as exc:
            assert exc.status_code == 404

    def test_delete_work_not_belong_to_user_raises_404(self):
        from app.services.work_service import WorkService
        from fastapi import HTTPException

        user_a_id = "user-a-001"
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        service = WorkService()
        try:
            service.delete_work("work-belong-to-b", user_a_id, mock_db)
            assert False, "Should have raised 404"
        except HTTPException as exc:
            assert exc.status_code == 404

    def test_delete_work_belong_to_user_succeeds(self):
        from app.services.work_service import WorkService

        user_id = "user-123"
        work = _make_work("work-1", user_id)

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = work

        service = WorkService()
        service.delete_work("work-1", user_id, mock_db)

        mock_db.delete.assert_called_once_with(work)
        mock_db.commit.assert_called_once()


class TestWorkCreateIsolation:
    """generate_outline should associate work with the requesting user."""

    def test_generate_outline_signature_accepts_user_id(self):
        """Verify that generate_outline accepts user_id as keyword argument."""
        from app.services.work_service import WorkService
        import inspect

        sig = inspect.signature(WorkService.generate_outline)
        params = sig.parameters
        assert "user_id" in params, "generate_outline should accept user_id parameter"

    def test_generate_outline_stream_signature_accepts_user_id(self):
        """Verify that generate_outline_stream accepts user_id as keyword argument."""
        from app.services.work_service import WorkService
        import inspect

        sig = inspect.signature(WorkService.generate_outline_stream)
        params = sig.parameters
        assert "user_id" in params, "generate_outline_stream should accept user_id parameter"


class TestChapterIsolation:
    """Chapter operations should verify work ownership."""

    def test_list_chapters_verifies_work_ownership(self):
        from app.services.work_service import WorkService
        from fastapi import HTTPException

        user_id = "user-123"
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        service = WorkService()
        try:
            service.list_chapters("work-1", mock_db, user_id=user_id)
            assert False, "Should have raised 404"
        except HTTPException as exc:
            assert exc.status_code == 404


class TestNoDemoUser:
    """DEMO_USER should be completely removed."""

    def test_no_demo_user_constant(self):
        """DEMO_USER_ID should not exist in work_service."""
        import app.services.work_service as ws

        assert not hasattr(ws, "DEMO_USER_ID"), "DEMO_USER_ID should be removed"

    def test_no_ensure_demo_user(self):
        """_ensure_demo_user function should be removed."""
        import app.services.work_service as ws

        assert not hasattr(ws, "_ensure_demo_user"), "_ensure_demo_user should be removed"
