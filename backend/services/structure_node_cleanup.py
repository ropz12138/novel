"""一次性删除旧结构节点；由命令显式调用，事务由调用方控制。"""
from sqlalchemy import text


def _chapter_orders(nodes, edges):
    """把旧层级中的章节阅读顺序展开，独立章节排在其后。"""
    by_id = {row["node_id"]: row for row in nodes}
    next_type = {"outline": "volume", "volume": "plot", "plot": "chapter"}
    parents = {}
    for edge in edges:
        source, target = by_id.get(edge["source_id"]), by_id.get(edge["target_id"])
        if source and target and next_type.get(source["type"]) == target["type"]:
            parents[target["node_id"]] = source["node_id"]
    keyed = []
    for row in nodes:
        if row["type"] != "chapter":
            continue
        path = [(row["sort_order"], row["node_id"])]
        current = row
        while current["node_id"] in parents:
            current = by_id[parents[current["node_id"]]]
            path.append((current["sort_order"], current["node_id"]))
        key = (current["type"] != "outline", tuple(reversed(path)))
        keyed.append((key, row))
    return [(row["id"], order) for order, (_, row) in enumerate(sorted(keyed, key=lambda item: item[0]), 1)]


def remove_structure_nodes(conn) -> dict:
    removed = "('outline', 'volume', 'plot')"
    counts = {}
    # 仅对仍含旧结构的作品和快照重编号，重复执行保持现有章节顺序。
    for node_table, edge_table, group_field, id_field in (
        ("nodes", "edges", "work_id", "id"),
        ("canvas_checkpoint_nodes", "canvas_checkpoint_edges", "checkpoint_id", "node_id"),
    ):
        groups = conn.execute(text(
            f"SELECT DISTINCT {group_field} FROM {node_table} WHERE type IN {removed}"
        )).scalars().all()
        for group in groups:
            nodes = conn.execute(text(
                f"SELECT id, {id_field} AS node_id, type, sort_order FROM {node_table} WHERE {group_field} = :group"
            ), {"group": group}).mappings().all()
            edges = conn.execute(text(
                f"SELECT source_id, target_id FROM {edge_table} WHERE {group_field} = :group"
            ), {"group": group}).mappings().all()
            orders = [{"id": node_id, "sort_order": order} for node_id, order in _chapter_orders(nodes, edges)]
            if orders:
                conn.execute(text(f"UPDATE {node_table} SET sort_order = :sort_order WHERE id = :id"), orders)

    # 保存即将删除的 ID，包含已从当前画布删除但仍在快照中的节点。
    conn.execute(text(f"""
        CREATE TEMP TABLE removed_structure_node_ids ON COMMIT DROP AS
        SELECT id AS node_id FROM nodes WHERE type IN {removed}
        UNION SELECT node_id FROM canvas_checkpoint_nodes WHERE type IN {removed}
    """))
    conn.execute(text("""
        DELETE FROM user_canvas_actions WHERE target_id IN (SELECT node_id FROM removed_structure_node_ids)
        OR target_type IN ('outline', 'volume', 'plot')
        OR target_id IN (SELECT id FROM edges WHERE source_id IN (SELECT node_id FROM removed_structure_node_ids)
                        OR target_id IN (SELECT node_id FROM removed_structure_node_ids))
    """))
    conn.execute(text("""
        DELETE FROM supervisor_messages WHERE meta->>'type' = 'chapter_content_diff_card'
        AND COALESCE(meta->'chapterContentDiffCard'->>'node_id',
                     meta->'chapterContentDiffCard'->>'chapter_node_id')
            IN (SELECT node_id FROM removed_structure_node_ids)
    """))
    for table in ("edges", "canvas_checkpoint_edges"):
        counts[f"{table}_deleted"] = conn.execute(text(f"""
            DELETE FROM {table} WHERE source_id IN (SELECT node_id FROM removed_structure_node_ids)
            OR target_id IN (SELECT node_id FROM removed_structure_node_ids)
        """)).rowcount
    # 清除章节上已经失效的历史结构绑定，章节正文与笔记保持原值。
    conn.execute(text("ALTER TABLE chapters DROP COLUMN IF EXISTS outline_binding_id"))
    for table in ("nodes", "canvas_checkpoint_nodes"):
        counts[f"{table}_deleted"] = conn.execute(text(f"DELETE FROM {table} WHERE type IN {removed}")).rowcount
    conn.execute(text("""
        UPDATE canvas_checkpoints SET
        node_count = (SELECT count(*) FROM canvas_checkpoint_nodes n WHERE n.checkpoint_id = canvas_checkpoints.id),
        edge_count = (SELECT count(*) FROM canvas_checkpoint_edges e WHERE e.checkpoint_id = canvas_checkpoints.id)
    """))
    return counts
