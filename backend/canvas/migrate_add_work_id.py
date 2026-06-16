"""数据库迁移脚本 - 添加 work_id 列"""
from sqlalchemy import create_engine, text
from app.config import settings


def build_database_url() -> str:
    return (
        f"postgresql+psycopg2://{settings.db_user}:{settings.db_password}"
        f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    )


def migrate():
    engine = create_engine(build_database_url())
    
    with engine.connect() as conn:
        # 检查 canvas_works 表是否存在
        result = conn.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'canvas_works'
            )
        """))
        canvas_works_exists = result.scalar()
        
        if not canvas_works_exists:
            print("创建 canvas_works 表...")
            conn.execute(text("""
                CREATE TABLE canvas_works (
                    id VARCHAR(36) PRIMARY KEY,
                    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    title VARCHAR(200) NOT NULL DEFAULT '未命名作品',
                    description VARCHAR(500) DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("CREATE INDEX ix_canvas_works_user_id ON canvas_works(user_id)"))
            print("canvas_works 表创建成功")
        
        # 检查 nodes 表是否有 work_id 列
        result = conn.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.columns 
                WHERE table_name = 'nodes' AND column_name = 'work_id'
            )
        """))
        nodes_has_work_id = result.scalar()
        
        if not nodes_has_work_id:
            print("添加 nodes.work_id 列...")
            # 先创建一个默认作品（如果有用户的话）
            result = conn.execute(text("SELECT id FROM users LIMIT 1"))
            user = result.fetchone()
            
            if user:
                user_id = user[0]
                # 检查是否已有作品
                result = conn.execute(text("SELECT id FROM canvas_works LIMIT 1"))
                work = result.fetchone()
                
                if not work:
                    import uuid
                    work_id = str(uuid.uuid4())
                    conn.execute(text("""
                        INSERT INTO canvas_works (id, user_id, title, description)
                        VALUES (:id, :user_id, '默认作品', '自动创建的默认作品')
                    """), {"id": work_id, "user_id": user_id})
                    print(f"创建默认作品: {work_id}")
                else:
                    work_id = work[0]
                
                # 添加 work_id 列（先允许 NULL）
                conn.execute(text("ALTER TABLE nodes ADD COLUMN work_id VARCHAR(36)"))
                # 更新现有节点
                conn.execute(text("UPDATE nodes SET work_id = :work_id"), {"work_id": work_id})
                # 设置 NOT NULL
                conn.execute(text("ALTER TABLE nodes ALTER COLUMN work_id SET NOT NULL"))
                # 添加索引
                conn.execute(text("CREATE INDEX ix_nodes_work_id ON nodes(work_id)"))
                # 添加外键
                conn.execute(text("""
                    ALTER TABLE nodes 
                    ADD CONSTRAINT fk_nodes_work_id 
                    FOREIGN KEY (work_id) REFERENCES canvas_works(id) ON DELETE CASCADE
                """))
                print("nodes.work_id 列添加成功")
            else:
                print("警告：没有用户，跳过 nodes 迁移")
        
        # 检查 edges 表是否有 work_id 列
        result = conn.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.columns 
                WHERE table_name = 'edges' AND column_name = 'work_id'
            )
        """))
        edges_has_work_id = result.scalar()
        
        if not edges_has_work_id:
            print("添加 edges.work_id 列...")
            # 获取默认作品
            result = conn.execute(text("SELECT id FROM canvas_works LIMIT 1"))
            work = result.fetchone()
            
            if work:
                work_id = work[0]
                # 添加 work_id 列
                conn.execute(text("ALTER TABLE edges ADD COLUMN work_id VARCHAR(36)"))
                # 更新现有连线
                conn.execute(text("UPDATE edges SET work_id = :work_id"), {"work_id": work_id})
                # 设置 NOT NULL
                conn.execute(text("ALTER TABLE edges ALTER COLUMN work_id SET NOT NULL"))
                # 添加索引
                conn.execute(text("CREATE INDEX ix_edges_work_id ON edges(work_id)"))
                # 添加外键
                conn.execute(text("""
                    ALTER TABLE edges 
                    ADD CONSTRAINT fk_edges_work_id 
                    FOREIGN KEY (work_id) REFERENCES canvas_works(id) ON DELETE CASCADE
                """))
                print("edges.work_id 列添加成功")
            else:
                print("警告：没有作品，跳过 edges 迁移")
        
        conn.commit()
        print("迁移完成！")
    
    engine.dispose()


if __name__ == "__main__":
    migrate()
