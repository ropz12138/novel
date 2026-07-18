"""启动前自动迁移入口（幂等）。

start_canvas_prod/dev.sh 在启动后端前调用本模块，保证 DB schema 与当前
model 一致，避免"代码先于迁移"导致的线上 500（如 nodes.scope /
users.primary_model 缺列）。

新增 schema 变更时：编写幂等的 migrate_xxx.py，并在 MIGRATIONS 列表
按历史顺序追加一行即可，无需改启动脚本。
"""
from migrate_add_work_id import migrate as migrate_work_id
from migrate_drop_chapter_number import migrate as migrate_drop_chapter_number
from migrate_add_layer import migrate as migrate_layer
from migrate_drop_manually_positioned import migrate as migrate_drop_manually_positioned
from migrate_add_scope import migrate as migrate_scope
from migrate_character_role import migrate as migrate_character_role
from migrate_add_model_pref import migrate as migrate_model_pref
from migrate_character_relations import migrate as migrate_character_relations
from migrate_todo_items import migrate as migrate_todo_items
from migrate_chapter_illustrations import migrate as migrate_chapter_illustrations
from migrate_canvas_checkpoints import migrate as migrate_canvas_checkpoints
from migrate_node_locked import migrate as migrate_node_locked

# (说明, migrate 函数) —— 按历史顺序；每个 migrate 必须幂等
MIGRATIONS = [
    ("nodes.work_id / edges.work_id", migrate_work_id),
    ("chapters.chapter_number 下线 + FK 补齐", migrate_drop_chapter_number),
    ("nodes.layer + 三纲合并为 outline", migrate_layer),
    ("nodes.manually_positioned 下线", migrate_drop_manually_positioned),
    ("nodes.scope", migrate_scope),
    ("character 角色分类(local→minor)", migrate_character_role),
    ("users.primary_model / fallback_model", migrate_model_pref),
    ("character_relations 表", migrate_character_relations),
    ("todo_items 表", migrate_todo_items),
    ("chapter_illustrations 表", migrate_chapter_illustrations),
    ("canvas_checkpoints 表", migrate_canvas_checkpoints),
    ("nodes.locked", migrate_node_locked),
]


def run_all():
    for name, fn in MIGRATIONS:
        print(f"\n== 迁移: {name} ==")
        fn()


if __name__ == "__main__":
    run_all()
    print("\n全部迁移完成。")
