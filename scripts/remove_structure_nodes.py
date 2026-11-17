#!/usr/bin/env python3
"""手动清理大纲、卷、情节及关联数据；读取项目当前环境数据库配置。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def main():
    from database import engine
    from services.structure_node_cleanup import remove_structure_nodes

    with engine.begin() as conn:
        counts = remove_structure_nodes(conn)
    print(json.dumps(counts, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
