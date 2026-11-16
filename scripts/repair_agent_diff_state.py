#!/usr/bin/env python3
"""Check agent diff state; --apply reconciles metadata without changing node text."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))


def main():
    from database import SessionLocal
    import models.user
    import models.work
    import models.chapter
    import models.edge
    import models.user_canvas_action
    from models.node import Node
    from models.node_agent_diff import NodeAgentDiffState, NodeAgentDiffGroup
    from services.agent_diff_groups import apply_groups
    from services.node_agent_diff import repair_inconsistent_snapshot
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-id', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    with SessionLocal() as db:
        nodes = db.query(Node).join(NodeAgentDiffState, NodeAgentDiffState.node_id == Node.id).filter(Node.work_id == args.work_id).order_by(Node.id).all()
        count = 0
        for node in nodes:
            state = db.get(NodeAgentDiffState, node.id)
            rows = db.query(NodeAgentDiffGroup.start_offset, NodeAgentDiffGroup.old_text, NodeAgentDiffGroup.new_text).filter(NodeAgentDiffGroup.node_id == node.id).order_by(NodeAgentDiffGroup.group_index).all()
            groups = [{'start_offset': r.start_offset, 'old_text': r.old_text, 'new_text': r.new_text} for r in rows]
            recorded = apply_groups(state.baseline_content, groups)
            current = node.content or ''
            if recorded == current:
                continue
            count += 1
            print(f'{node.id} {node.title}: diff结果 {len(recorded)} 字，当前正文 {len(current)} 字')
            if args.apply:
                repair_inconsistent_snapshot(db, node)
        if args.apply:
            db.commit()
        print(f'{"已修复" if args.apply else "发现"} {count} 个不一致节点；节点正文与标题保持原样。')
        if not args.apply and count:
            print('检查后，追加 --apply 执行修复。')


if __name__ == '__main__':
    main()
