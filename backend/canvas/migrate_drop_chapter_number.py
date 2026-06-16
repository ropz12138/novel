"""数据库迁移脚本 - 删除 chapters.chapter_number 列与相关约束，
并补齐 chapters.node_id -> nodes.id 的外键约束。

背景:
    `generate_chapter_content` 工具创建 Chapter 时未显式赋值 chapter_number,
    回落默认值 0, 触发 uq_work_chapter 唯一约束冲突。chapter_number 在
    canvas 版无业务消费方, 故根除该列; 同时 ORM 声明的 node_id 外键从未
    真正应用到数据库 (init_db 用 create_all 不迁移已有表), 在此一并补齐。
"""
from sqlalchemy import create_engine, text

from app.config import settings


def build_database_url() -> str:
    return (
        f"postgresql+psycopg2://{settings.db_user}:{settings.db_password}"
        f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    )


def _exists(conn, sql, **params):
    return conn.execute(text(sql), params).scalar()


def migrate():
    engine = create_engine(build_database_url())
    with engine.begin() as conn:
        # 1) 删除 uq_work_chapter 唯一约束
        has_uq = _exists(
            conn,
            "SELECT 1 FROM pg_constraint WHERE conname = 'uq_work_chapter'",
        )
        if has_uq:
            print("删除约束 uq_work_chapter ...")
            conn.execute(text("ALTER TABLE chapters DROP CONSTRAINT uq_work_chapter"))
        else:
            print("约束 uq_work_chapter 不存在，跳过")

        # 2) 清理 Bug 留下的脏数据 (chapter_number=0 的种子记录)
        has_col = _exists(
            conn,
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'chapters' AND column_name = 'chapter_number'
            """,
        )
        if has_col:
            dirty_count = _exists(
                conn,
                "SELECT COUNT(*) FROM chapters WHERE chapter_number = 0",
            )
            if dirty_count:
                print(f"清理 {dirty_count} 条 chapter_number=0 的脏数据 ...")
                conn.execute(text("DELETE FROM chapters WHERE chapter_number = 0"))
            else:
                print("无 chapter_number=0 的脏数据")

        # 3) 删除 chapter_number 列
        if has_col:
            print("删除列 chapters.chapter_number ...")
            conn.execute(text("ALTER TABLE chapters DROP COLUMN chapter_number"))
        else:
            print("列 chapter_number 不存在，跳过")

        # 4) 补齐 chapters.node_id -> nodes.id 外键 (ON DELETE SET NULL)
        has_fk = _exists(
            conn,
            """
            SELECT 1 FROM pg_constraint
            WHERE conrelid = 'chapters'::regclass
              AND conname = 'chapters_node_id_fkey'
            """,
        )
        if not has_fk:
            # 清理引用了不存在 node 的孤儿行 (否则 ADD CONSTRAINT 会失败)
            orphan_count = _exists(
                conn,
                """
                SELECT COUNT(*) FROM chapters c
                WHERE c.node_id IS NOT NULL
                  AND NOT EXISTS (SELECT 1 FROM nodes n WHERE n.id = c.node_id)
                """,
            )
            if orphan_count:
                print(f"清理 {orphan_count} 条 node_id 指向不存在节点的孤儿 chapter 行 ...")
                conn.execute(
                    text(
                        """
                        DELETE FROM chapters
                        WHERE node_id IS NOT NULL
                          AND NOT EXISTS (
                            SELECT 1 FROM nodes n WHERE n.id = chapters.node_id
                          )
                        """
                    )
                )
            print("添加外键 chapters_node_id_fkey ...")
            conn.execute(
                text(
                    """
                    ALTER TABLE chapters
                    ADD CONSTRAINT chapters_node_id_fkey
                    FOREIGN KEY (node_id) REFERENCES nodes(id)
                    ON DELETE SET NULL
                    """
                )
            )
        else:
            print("外键 chapters_node_id_fkey 已存在，跳过")

    engine.dispose()
    print("迁移完成！")


if __name__ == "__main__":
    migrate()
