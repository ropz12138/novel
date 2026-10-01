"""Apply the one-time chapters.status removal using this project's database config."""

from pathlib import Path
import sys

from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from database import engine  # noqa: E402


def main() -> None:
    statement = (ROOT / "scripts" / "drop_chapters_status.sql").read_text(encoding="utf-8")
    with engine.begin() as connection:
        connection.execute(text(statement))
    print("已删除 chapters.status")


if __name__ == "__main__":
    main()
