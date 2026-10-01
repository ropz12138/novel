import inspect

from models.chapter import Chapter
from services.node_content_write_service import write_node_content


def test_chapter_has_no_status_column():
    assert "status" not in Chapter.__table__.columns


def test_node_content_writer_has_no_chapter_status_argument():
    assert "status" not in inspect.signature(write_node_content).parameters
