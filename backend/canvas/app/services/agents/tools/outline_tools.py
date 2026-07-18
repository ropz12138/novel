"""大纲工具 - 三层大纲架构（宏观/中纲/小纲）"""
import json
import uuid
import asyncio
import logging
import re
import threading
from typing import Optional
from functools import partial

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models.node import Node
from app.models.edge import Edge

logger = logging.getLogger(__name__)


def _get_db():
    """获取数据库会话"""
    from app.database import SessionLocal
    return SessionLocal()


def _get_current_work_id():
    """获取当前work_id"""
    try:
        from app.services.agents.supervisor import get_context
        return get_context().get("work_id")
    except:
        return None


def _get_emit():
    """获取事件发射函数"""
    try:
        from app.services.agents.supervisor import get_context
        return get_context().get("emit")
    except:
        return None


def _get_work_title(db, work_id):
    """获取作品标题"""
    from app.models.work import CanvasWork
    work = db.query(CanvasWork).filter_by(id=work_id).first()
    return work.title if work else "未命名作品"


# ========== 输入Schema ==========

class CreateMacroOutlineInput(BaseModel):
    titles: list[str] = Field(description="宏观阶段标题列表，按顺序")
    description: str = Field(default="", description="小说的整体描述（题材、主题、主要角色等）")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class CreateMesoOutlineInput(BaseModel):
    parent_id: str = Field(description="父宏观节点ID")
    titles: list[str] = Field(description="中纲标题列表，按顺序")
    description: str = Field(default="", description="该阶段的简要描述")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class CreateMicroOutlineInput(BaseModel):
    parent_id: str = Field(description="父中纲节点ID")
    titles: list[str] = Field(description="小纲标题列表，按顺序")
    description: str = Field(default="", description="该场景的简要描述")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class CreateOutlineSequenceInput(BaseModel):
    node_ids: list[str] = Field(description="节点ID列表（按顺序）")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class UpdateOutlineNodeInput(BaseModel):
    node_id: str = Field(description="节点ID")
    title: Optional[str] = Field(default=None, description="新标题")
    content: Optional[str] = Field(default=None, description="新内容")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class DeleteOutlineNodeInput(BaseModel):
    node_id: str = Field(description="节点ID")
    delete_children: bool = Field(default=True, description="是否删除子节点")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class ExpandMacroNodeInput(BaseModel):
    macro_node_id: str = Field(description="要展开的宏观节点ID")
    description: str = Field(default="", description="该阶段的简要描述，用于生成中纲标题")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class ExpandMesoNodeInput(BaseModel):
    meso_node_id: str = Field(description="要展开的中纲节点ID")
    description: str = Field(default="", description="该场景的简要描述，用于生成小纲标题")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


# ========== 同步实现 ==========

async def _generate_titles_with_llm(node_type: str, parent_title: str, parent_content: str, description: str, work_title: str) -> list[str]:
    """使用 LLM 生成子节点标题列表"""
    from app.services.agents.llm import get_llm
    from langchain_core.messages import HumanMessage, SystemMessage

    prompts = {
        "meso_outline": f"""你是一个专业的小说大纲策划师。请为以下宏观大纲阶段生成中纲标题列表。

作品标题：{work_title}
宏观阶段：{parent_title}
阶段内容：{parent_content[:500]}
补充描述：{description}

请生成 3-6 个中纲标题，按顺序排列。每个标题应该简洁明了（10字以内），体现该阶段的关键发展。

【输出格式】直接输出 JSON 数组，不要包含其他文本。
示例：["标题1", "标题2", "标题3"]""",

        "micro_outline": f"""你是一个专业的小说大纲策划师。请为以下中纲场景生成小纲标题列表。

作品标题：{work_title}
中纲场景：{parent_title}
场景内容：{parent_content[:500]}
补充描述：{description}

请生成 3-6 个小纲标题，按顺序排列。每个标题应该简洁明了（10字以内），体现具体的情节点。

【输出格式】直接输出 JSON 数组，不要包含其他文本。
示例：["标题1", "标题2", "标题3"]"""
    }

    prompt = prompts.get(node_type, prompts["meso_outline"])

    llm = get_llm(temperature=0.7)
    messages = [
        SystemMessage(content="你是一个专业的网络小说大纲策划师。"),
        HumanMessage(content=prompt),
    ]

    response = await llm.ainvoke(messages)
    content = response.content.strip()

    # 解析 JSON
    import re
    if "```" in content:
        match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", content, re.DOTALL)
        if match:
            content = match.group(1)

    try:
        titles = json.loads(content)
        if isinstance(titles, list):
            return [t.strip() for t in titles if t.strip()]
    except json.JSONDecodeError:
        pass

    # 如果解析失败，返回默认标题
    if node_type == "meso_outline":
        return [f"{parent_title} - 阶段{i+1}" for i in range(3)]
    else:
        return [f"{parent_title} - 场景{i+1}" for i in range(3)]


def _get_next_position(db, work_id, node_type, parent_id=None):
    """计算下一个节点位置"""
    if node_type == "macro_outline":
        # 宏观大纲：Y=50，从左到右
        max_node = db.query(Node).filter(
            Node.work_id == work_id,
            Node.type == "macro_outline"
        ).order_by(Node.position_x.desc()).first()
        x = max_node.position_x + 350 if max_node else 50
        return x, 50
    
    elif node_type == "meso_outline":
        # 中纲：Y=250，挂在宏观下方
        parent = db.query(Node).filter(Node.id == parent_id).first()
        if not parent:
            return 50, 250
        
        # 计算该宏观下已有的中纲数量
        existing = db.query(Edge).filter(
            Edge.source_id == parent_id,
            Edge.edge_type == "contains"
        ).count()
        
        # 找到父节点X坐标，然后偏移
        siblings = db.query(Node).join(Edge, Edge.target_id == Node.id).filter(
            Edge.source_id == parent_id,
            Edge.edge_type == "contains"
        ).order_by(Node.position_x).all()
        
        if siblings:
            x = siblings[-1].position_x + 200
        else:
            x = parent.position_x
        
        return x, 250
    
    elif node_type == "micro_outline":
        # 小纲：Y=450，挂在中纲下方
        parent = db.query(Node).filter(Node.id == parent_id).first()
        if not parent:
            return 50, 450
        
        siblings = db.query(Node).join(Edge, Edge.target_id == Node.id).filter(
            Edge.source_id == parent_id,
            Edge.edge_type == "contains"
        ).order_by(Node.position_x).all()
        
        if siblings:
            x = siblings[-1].position_x + 150
        else:
            x = parent.position_x
        
        return x, 450
    
    return 50, 200


async def _generate_content_with_llm(node_type: str, title: str, description: str, work_title: str) -> str:
    """使用 LLM 生成节点的详细内容"""
    from app.services.agents.llm import get_llm
    from langchain_core.messages import HumanMessage, SystemMessage

    prompts = {
        "macro_outline": f"""你是一个专业的小说大纲策划师。请为以下宏观大纲阶段生成详细的内容描述。

作品标题：{work_title}
阶段标题：{title}
整体描述：{description}

请生成该阶段的详细内容，包括：
1. 阶段目标
2. 核心事件（3-5个）
3. 关键发展
4. 伏笔设置
5. 预计章节范围

直接输出内容，不要包含标题。""",

        "meso_outline": f"""你是一个专业的小说大纲策划师。请为以下中纲场景生成详细的内容描述。

作品标题：{work_title}
场景标题：{title}
阶段描述：{description}

请生成该场景的详细内容，包括：
1. 场景设定
2. 主要事件
3. 关键角色
4. 情感基调
5. 伏笔设置

直接输出内容，不要包含标题。""",

        "micro_outline": f"""你是一个专业的小说大纲策划师。请为以下小纲情节点生成详细的内容描述。

作品标题：{work_title}
情节点标题：{title}
场景描述：{description}

请生成该情节点的详细内容，包括：
1. 具体情节
2. 细节描写
3. 角色互动
4. 伏笔设置
5. 章节范围（如果适用）

直接输出内容，不要包含标题。"""
    }

    prompt = prompts.get(node_type, prompts["macro_outline"])

    llm = get_llm(temperature=0.7)
    messages = [
        SystemMessage(content="你是一个专业的网络小说大纲策划师。"),
        HumanMessage(content=prompt),
    ]

    response = await llm.ainvoke(messages)
    return response.content.strip()


async def _generate_contents_async(work_id: str, work_title: str, node_type: str, nodes: list, description: str):
    """异步批量生成节点内容"""
    try:
        for node_info in nodes:
            node_id = node_info["id"]
            title = node_info["title"]

            # 生成内容
            content = await _generate_content_with_llm(
                node_type=node_type,
                title=title,
                description=description,
                work_title=work_title,
            )

            # 更新节点内容
            db = _get_db()
            try:
                node = db.query(Node).filter(Node.id == node_id).first()
                if node:
                    node.content = content
                    if node.type == "chapter":
                        from app.services.chapter_history_service import clear_chapter_summary_on_content_change
                        clear_chapter_summary_on_content_change(db, node)
                    db.commit()
                    logger.info(f"已生成内容: {title}")
            finally:
                db.close()

        # 触发画布更新事件
        emit = _get_emit()
        if emit:
            await emit("nodes_updated", {"action": "content_generated", "node_type": node_type})

    except Exception as e:
        logger.error(f"生成内容失败: {e}")


def _run_generate_contents_in_background(work_id: str, work_title: str, node_type: str, nodes: list, description: str):
    """在后台线程中运行内容生成任务"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_generate_contents_async(work_id, work_title, node_type, nodes, description))
    except Exception as e:
        logger.error(f"后台生成内容失败: {e}")
    finally:
        loop.close()


def _create_macro_outline_sync(titles: list[str], description: str = "", reason=None):
    """批量创建宏观大纲节点"""
    work_id = _get_current_work_id()
    if not work_id:
        return json.dumps({"error": "未指定作品ID"}, ensure_ascii=False)

    db = _get_db()
    try:
        work_title = _get_work_title(db, work_id)
        created_nodes = []
        prev_node_id = None

        for i, title in enumerate(titles):
            if not title.strip():
                continue

            position_x, position_y = _get_next_position(db, work_id, "macro_outline")

            node = Node(
                id=str(uuid.uuid4()),
                work_id=work_id,
                type="macro_outline",
                title=title.strip(),
                content="",  # 内容由 LLM 异步生成
                extra_data={"order": i + 1},
                position_x=position_x,
                position_y=position_y,
            )
            db.add(node)
            db.flush()  # 获取 ID

            # 与上一个宏观节点建立顺序连线
            if prev_node_id:
                edge = Edge(
                    id=str(uuid.uuid4()),
                    work_id=work_id,
                    source_id=prev_node_id,
                    target_id=node.id,
                    edge_type="inherits",
                    label="顺序"
                )
                db.add(edge)

            created_nodes.append({
                "id": node.id,
                "type": node.type,
                "title": node.title,
                "order": i + 1,
            })
            prev_node_id = node.id

        db.commit()

        # 在后台线程中生成内容（不阻塞返回）
        thread = threading.Thread(
            target=_run_generate_contents_in_background,
            args=(work_id, work_title, "macro_outline", created_nodes, description),
            daemon=True
        )
        thread.start()

        return json.dumps({
            "success": True,
            "message": f"已创建 {len(created_nodes)} 个宏观大纲节点，内容正在后台生成中...",
            "nodes": created_nodes,
            "count": len(created_nodes),
        }, ensure_ascii=False)
    except Exception as e:
        db.rollback()
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    finally:
        db.close()


def _create_meso_outline_sync(parent_id, title, content="", order=0, reason=None):
    """创建中纲节点"""
    work_id = _get_current_work_id()
    if not work_id:
        return json.dumps({"error": "未指定作品ID"}, ensure_ascii=False)
    
    db = _get_db()
    try:
        # 验证父节点
        parent = db.query(Node).filter(
            Node.id == parent_id,
            Node.work_id == work_id,
            Node.type == "macro_outline"
        ).first()
        if not parent:
            return json.dumps({"error": "父节点不存在或不是宏观大纲"}, ensure_ascii=False)
        
        position_x, position_y = _get_next_position(db, work_id, "meso_outline", parent_id)
        
        node = Node(
            id=str(uuid.uuid4()),
            work_id=work_id,
            type="meso_outline",
            title=title,
            content=content,
            extra_data={"order": order, "parent_id": parent_id},
            position_x=position_x,
            position_y=position_y,
        )
        db.add(node)
        db.commit()
        db.refresh(node)
        
        # 建立包含连线（父→子）
        edge = Edge(
            id=str(uuid.uuid4()),
            work_id=work_id,
            source_id=parent_id,
            target_id=node.id,
            edge_type="contains",
            label="包含"
        )
        db.add(edge)
        
        # 与上一个兄弟节点建立顺序连线
        prev_sibling = db.query(Node).join(Edge, Edge.target_id == Node.id).filter(
            Edge.source_id == parent_id,
            Edge.edge_type == "contains",
            Node.id != node.id
        ).order_by(Node.position_x.desc()).first()
        
        if prev_sibling:
            seq_edge = Edge(
                id=str(uuid.uuid4()),
                work_id=work_id,
                source_id=prev_sibling.id,
                target_id=node.id,
                edge_type="inherits",
                label="顺序"
            )
            db.add(seq_edge)
        
        db.commit()
        
        return json.dumps({
            "success": True,
            "node": {
                "id": node.id,
                "type": node.type,
                "title": node.title,
                "content": node.content,
                "position_x": node.position_x,
                "position_y": node.position_y,
                "parent_id": parent_id,
            }
        }, ensure_ascii=False)
    except Exception as e:
        db.rollback()
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    finally:
        db.close()


def _create_meso_outline_sync(parent_id: str, titles: list[str], description: str = "", reason=None):
    """批量创建中纲节点"""
    work_id = _get_current_work_id()
    if not work_id:
        return json.dumps({"error": "未指定作品ID"}, ensure_ascii=False)

    db = _get_db()
    try:
        # 验证父节点
        parent = db.query(Node).filter(
            Node.id == parent_id,
            Node.work_id == work_id,
            Node.type == "macro_outline"
        ).first()
        if not parent:
            return json.dumps({"error": "父节点不存在或不是宏观大纲"}, ensure_ascii=False)

        work_title = _get_work_title(db, work_id)
        created_nodes = []
        prev_node_id = None

        for i, title in enumerate(titles):
            if not title.strip():
                continue

            position_x, position_y = _get_next_position(db, work_id, "meso_outline", parent_id)

            node = Node(
                id=str(uuid.uuid4()),
                work_id=work_id,
                type="meso_outline",
                title=title.strip(),
                content="",  # 内容由 LLM 异步生成
                extra_data={"order": i + 1, "parent_id": parent_id},
                position_x=position_x,
                position_y=position_y,
            )
            db.add(node)
            db.flush()

            # 建立包含连线（父→子）
            edge = Edge(
                id=str(uuid.uuid4()),
                work_id=work_id,
                source_id=parent_id,
                target_id=node.id,
                edge_type="contains",
                label="包含"
            )
            db.add(edge)

            # 与上一个兄弟节点建立顺序连线
            if prev_node_id:
                seq_edge = Edge(
                    id=str(uuid.uuid4()),
                    work_id=work_id,
                    source_id=prev_node_id,
                    target_id=node.id,
                    edge_type="inherits",
                    label="顺序"
                )
                db.add(seq_edge)

            created_nodes.append({
                "id": node.id,
                "type": node.type,
                "title": node.title,
                "order": i + 1,
            })
            prev_node_id = node.id

        db.commit()

        # 在后台线程中生成内容（不阻塞返回）
        thread = threading.Thread(
            target=_run_generate_contents_in_background,
            args=(work_id, work_title, "meso_outline", created_nodes, description or f"属于「{parent.title}」阶段"),
            daemon=True
        )
        thread.start()

        return json.dumps({
            "success": True,
            "message": f"已为「{parent.title}」创建 {len(created_nodes)} 个中纲，内容正在后台生成中...",
            "nodes": created_nodes,
            "count": len(created_nodes),
        }, ensure_ascii=False)
    except Exception as e:
        db.rollback()
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    finally:
        db.close()


def _create_micro_outline_sync(parent_id: str, titles: list[str], description: str = "", reason=None):
    """批量创建小纲节点"""
    work_id = _get_current_work_id()
    if not work_id:
        return json.dumps({"error": "未指定作品ID"}, ensure_ascii=False)

    db = _get_db()
    try:
        # 验证父节点
        parent = db.query(Node).filter(
            Node.id == parent_id,
            Node.work_id == work_id,
            Node.type == "meso_outline"
        ).first()
        if not parent:
            return json.dumps({"error": "父节点不存在或不是中纲"}, ensure_ascii=False)

        work_title = _get_work_title(db, work_id)
        created_nodes = []
        prev_node_id = None

        for i, title in enumerate(titles):
            if not title.strip():
                continue

            position_x, position_y = _get_next_position(db, work_id, "micro_outline", parent_id)

            node = Node(
                id=str(uuid.uuid4()),
                work_id=work_id,
                type="micro_outline",
                title=title.strip(),
                content="",  # 内容由 LLM 异步生成
                extra_data={"order": i + 1, "parent_id": parent_id},
                position_x=position_x,
                position_y=position_y,
            )
            db.add(node)
            db.flush()

            # 建立包含连线
            edge = Edge(
                id=str(uuid.uuid4()),
                work_id=work_id,
                source_id=parent_id,
                target_id=node.id,
                edge_type="contains",
                label="包含"
            )
            db.add(edge)

            # 与上一个兄弟节点建立顺序连线
            if prev_node_id:
                seq_edge = Edge(
                    id=str(uuid.uuid4()),
                    work_id=work_id,
                    source_id=prev_node_id,
                    target_id=node.id,
                    edge_type="inherits",
                    label="顺序"
                )
                db.add(seq_edge)

            created_nodes.append({
                "id": node.id,
                "type": node.type,
                "title": node.title,
                "order": i + 1,
            })
            prev_node_id = node.id

        db.commit()

        # 在后台线程中生成内容（不阻塞返回）
        thread = threading.Thread(
            target=_run_generate_contents_in_background,
            args=(work_id, work_title, "micro_outline", created_nodes, description or f"属于「{parent.title}」场景"),
            daemon=True
        )
        thread.start()

        return json.dumps({
            "success": True,
            "message": f"已为「{parent.title}」创建 {len(created_nodes)} 个小纲，内容正在后台生成中...",
            "nodes": created_nodes,
            "count": len(created_nodes),
        }, ensure_ascii=False)
    except Exception as e:
        db.rollback()
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    finally:
        db.close()


def _create_outline_sequence_sync(node_ids):
    """为节点列表创建顺序连线"""
    work_id = _get_current_work_id()
    if not work_id:
        return json.dumps({"error": "未指定作品ID"}, ensure_ascii=False)
    
    db = _get_db()
    try:
        created = 0
        for i in range(len(node_ids) - 1):
            source_id = node_ids[i]
            target_id = node_ids[i + 1]
            
            # 检查是否已存在
            existing = db.query(Edge).filter(
                Edge.source_id == source_id,
                Edge.target_id == target_id,
                Edge.edge_type == "inherits"
            ).first()
            
            if not existing:
                edge = Edge(
                    id=str(uuid.uuid4()),
                    work_id=work_id,
                    source_id=source_id,
                    target_id=target_id,
                    edge_type="inherits",
                    label="顺序"
                )
                db.add(edge)
                created += 1
        
        db.commit()
        return json.dumps({
            "success": True,
            "created_edges": created,
            "message": f"创建了 {created} 条顺序连线"
        }, ensure_ascii=False)
    except Exception as e:
        db.rollback()
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    finally:
        db.close()


def _update_outline_node_sync(node_id, title=None, content=None):
    """更新大纲节点"""
    db = _get_db()
    try:
        node = db.query(Node).filter(Node.id == node_id).first()
        if not node:
            return json.dumps({"error": "节点不存在"}, ensure_ascii=False)
        
        if title is not None:
            node.title = title
        if content is not None:
            node.content = content
            if node.type == "chapter":
                from app.services.chapter_history_service import clear_chapter_summary_on_content_change
                clear_chapter_summary_on_content_change(db, node)
        
        db.commit()
        db.refresh(node)
        return json.dumps({
            "success": True,
            "node": {"id": node.id, "title": node.title, "content": node.content}
        }, ensure_ascii=False)
    except Exception as e:
        db.rollback()
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    finally:
        db.close()


def _delete_outline_node_sync(node_id, delete_children=True):
    """删除大纲节点"""
    db = _get_db()
    try:
        node = db.query(Node).filter(Node.id == node_id).first()
        if not node:
            return json.dumps({"error": "节点不存在"}, ensure_ascii=False)
        
        if delete_children:
            # 递归删除子节点
            _delete_children_recursive(db, node_id)
        
        # 删除关联的边
        db.query(Edge).filter(
            (Edge.source_id == node_id) | (Edge.target_id == node_id)
        ).delete()
        
        db.delete(node)
        db.commit()
        
        return json.dumps({
            "success": True,
            "message": f"已删除节点: {node.title}"
        }, ensure_ascii=False)
    except Exception as e:
        db.rollback()
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    finally:
        db.close()


def _delete_children_recursive(db, parent_id):
    """递归删除子节点"""
    children = db.query(Node).join(Edge, Edge.target_id == Node.id).filter(
        Edge.source_id == parent_id,
        Edge.edge_type == "contains"
    ).all()
    
    for child in children:
        _delete_children_recursive(db, child.id)
        db.query(Edge).filter(
            (Edge.source_id == child.id) | (Edge.target_id == child.id)
        ).delete()
        db.delete(child)


def _analyze_outline_structure_sync():
    """分析大纲结构"""
    work_id = _get_current_work_id()
    if not work_id:
        return json.dumps({"error": "未指定作品ID"}, ensure_ascii=False)
    
    db = _get_db()
    try:
        macro_nodes = db.query(Node).filter(
            Node.work_id == work_id,
            Node.type == "macro_outline"
        ).order_by(Node.position_x).all()
        
        result = {
            "macro_count": len(macro_nodes),
            "macro_nodes": [],
            "suggestions": []
        }
        
        for macro in macro_nodes:
            meso_count = db.query(Node).join(Edge, Edge.target_id == Node.id).filter(
                Edge.source_id == macro.id,
                Edge.edge_type == "contains"
            ).count()
            
            result["macro_nodes"].append({
                "id": macro.id,
                "title": macro.title,
                "meso_count": meso_count
            })
            
            if meso_count == 0:
                result["suggestions"].append(f"宏观阶段「{macro.title}」还没有中纲")
        
        if len(macro_nodes) == 0:
            result["suggestions"].append("还没有创建宏观大纲，建议先创建故事的整体阶段")
        elif len(macro_nodes) < 3:
            result["suggestions"].append("宏观阶段较少，建议至少包含：开端、发展、高潮")
        
        return json.dumps(result, ensure_ascii=False)
    finally:
        db.close()


def _expand_macro_node_sync(macro_node_id: str, description: str = "", reason=None):
    """展开宏观节点：为其创建中纲子节点（标题由LLM生成）"""
    work_id = _get_current_work_id()
    if not work_id:
        return json.dumps({"error": "未指定作品ID"}, ensure_ascii=False)
    
    db = _get_db()
    try:
        # 验证宏观节点
        macro_node = db.query(Node).filter(
            Node.id == macro_node_id,
            Node.work_id == work_id,
            Node.type == "macro_outline"
        ).first()
        if not macro_node:
            return json.dumps({"error": "宏观节点不存在"}, ensure_ascii=False)
        
        # 检查是否已有中纲
        existing_meso = db.query(Node).join(Edge, Edge.target_id == Node.id).filter(
            Edge.source_id == macro_node_id,
            Edge.edge_type == "contains"
        ).count()
        if existing_meso > 0:
            return json.dumps({"error": "该宏观节点已有中纲，如需重新生成请先删除"}, ensure_ascii=False)
        
        # 使用LLM生成中纲标题
        work_title = _get_work_title(db, work_id)
        
        # 在新的事件循环中运行异步函数
        loop = asyncio.new_event_loop()
        try:
            meso_titles = loop.run_until_complete(
                _generate_titles_with_llm("meso_outline", macro_node.title, macro_node.content, description, work_title)
            )
        finally:
            loop.close()
        
        created_nodes = []
        prev_meso_id = None
        
        for i, title in enumerate(meso_titles):
            if not title.strip():
                continue
            
            position_x, position_y = _get_next_position(db, work_id, "meso_outline", macro_node_id)
            
            meso_node = Node(
                id=str(uuid.uuid4()),
                work_id=work_id,
                type="meso_outline",
                title=title,
                content="",
                extra_data={"order": i + 1, "parent_id": macro_node_id},
                position_x=position_x,
                position_y=position_y,
            )
            db.add(meso_node)
            db.flush()
            
            # 建立包含连线
            contains_edge = Edge(
                id=str(uuid.uuid4()),
                work_id=work_id,
                source_id=macro_node_id,
                target_id=meso_node.id,
                edge_type="contains",
                label="包含"
            )
            db.add(contains_edge)
            
            # 建立顺序连线
            if prev_meso_id:
                seq_edge = Edge(
                    id=str(uuid.uuid4()),
                    work_id=work_id,
                    source_id=prev_meso_id,
                    target_id=meso_node.id,
                    edge_type="inherits",
                    label="顺序"
                )
                db.add(seq_edge)
            
            prev_meso_id = meso_node.id
            created_nodes.append({"id": meso_node.id, "title": title})
        
        db.commit()

        # 在后台线程中生成内容（不阻塞返回）
        thread = threading.Thread(
            target=_run_generate_contents_in_background,
            args=(work_id, work_title, "meso_outline", created_nodes, f"属于「{macro_node.title}」阶段"),
            daemon=True
        )
        thread.start()
        
        return json.dumps({
            "success": True,
            "message": f"已为「{macro_node.title}」创建 {len(created_nodes)} 个中纲，内容正在后台生成中...",
            "nodes": created_nodes,
        }, ensure_ascii=False)
    except Exception as e:
        db.rollback()
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    finally:
        db.close()


def _expand_meso_node_sync(meso_node_id: str, description: str = "", reason=None):
    """展开中纲节点：为其创建小纲子节点（标题由LLM生成）"""
    work_id = _get_current_work_id()
    if not work_id:
        return json.dumps({"error": "未指定作品ID"}, ensure_ascii=False)
    
    db = _get_db()
    try:
        # 验证中纲节点
        meso_node = db.query(Node).filter(
            Node.id == meso_node_id,
            Node.work_id == work_id,
            Node.type == "meso_outline"
        ).first()
        if not meso_node:
            return json.dumps({"error": "中纲节点不存在"}, ensure_ascii=False)
        
        # 检查是否已有小纲
        existing_micro = db.query(Node).join(Edge, Edge.target_id == Node.id).filter(
            Edge.source_id == meso_node_id,
            Edge.edge_type == "contains"
        ).count()
        if existing_micro > 0:
            return json.dumps({"error": "该中纲节点已有小纲，如需重新生成请先删除"}, ensure_ascii=False)
        
        # 使用LLM生成小纲标题
        work_title = _get_work_title(db, work_id)
        
        # 在新的事件循环中运行异步函数
        loop = asyncio.new_event_loop()
        try:
            micro_titles = loop.run_until_complete(
                _generate_titles_with_llm("micro_outline", meso_node.title, meso_node.content, description, work_title)
            )
        finally:
            loop.close()
        
        created_nodes = []
        prev_micro_id = None
        
        for i, title in enumerate(micro_titles):
            if not title.strip():
                continue
            
            position_x, position_y = _get_next_position(db, work_id, "micro_outline", meso_node_id)
            
            micro_node = Node(
                id=str(uuid.uuid4()),
                work_id=work_id,
                type="micro_outline",
                title=title,
                content="",
                extra_data={"order": i + 1, "parent_id": meso_node_id},
                position_x=position_x,
                position_y=position_y,
            )
            db.add(micro_node)
            db.flush()
            
            # 建立包含连线
            contains_edge = Edge(
                id=str(uuid.uuid4()),
                work_id=work_id,
                source_id=meso_node_id,
                target_id=micro_node.id,
                edge_type="contains",
                label="包含"
            )
            db.add(contains_edge)
            
            # 建立顺序连线
            if prev_micro_id:
                seq_edge = Edge(
                    id=str(uuid.uuid4()),
                    work_id=work_id,
                    source_id=prev_micro_id,
                    target_id=micro_node.id,
                    edge_type="inherits",
                    label="顺序"
                )
                db.add(seq_edge)
            
            prev_micro_id = micro_node.id
            created_nodes.append({"id": micro_node.id, "title": title})
        
        db.commit()

        # 在后台线程中生成内容（不阻塞返回）
        thread = threading.Thread(
            target=_run_generate_contents_in_background,
            args=(work_id, work_title, "micro_outline", created_nodes, f"属于「{meso_node.title}」场景"),
            daemon=True
        )
        thread.start()
        
        return json.dumps({
            "success": True,
            "message": f"已为「{meso_node.title}」创建 {len(created_nodes)} 个小纲，内容正在后台生成中...",
            "nodes": created_nodes,
        }, ensure_ascii=False)
    except Exception as e:
        db.rollback()
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    finally:
        db.close()


# ========== 异步包装 ==========

async def _create_macro_outline_async(titles: list[str], description: str = "", reason=None):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, partial(_create_macro_outline_sync, titles, description, reason))
    # 触发画布更新事件
    try:
        data = json.loads(result)
        if data.get("success"):
            emit = _get_emit()
            if emit:
                await emit("nodes_updated", {"action": "create", "node_type": "macro_outline"})
    except:
        pass
    return result


async def _create_meso_outline_async(parent_id: str, titles: list[str], description: str = "", reason=None):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, partial(_create_meso_outline_sync, parent_id, titles, description, reason))
    # 触发画布更新事件
    try:
        data = json.loads(result)
        if data.get("success"):
            emit = _get_emit()
            if emit:
                await emit("nodes_updated", {"action": "create", "node_type": "meso_outline"})
    except:
        pass
    return result


async def _create_micro_outline_async(parent_id: str, titles: list[str], description: str = "", reason=None):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, partial(_create_micro_outline_sync, parent_id, titles, description, reason))
    # 触发画布更新事件
    try:
        data = json.loads(result)
        if data.get("success"):
            emit = _get_emit()
            if emit:
                await emit("nodes_updated", {"action": "create", "node_type": "micro_outline"})
    except:
        pass
    return result


async def _create_outline_sequence_async(node_ids, reason=None):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, partial(_create_outline_sequence_sync, node_ids))
    # 触发画布更新事件
    try:
        data = json.loads(result)
        if data.get("success"):
            emit = _get_emit()
            if emit:
                await emit("nodes_updated", {"action": "edge_create", "edge_type": "inherits"})
    except:
        pass
    return result


async def _update_outline_node_async(node_id, title=None, content=None, reason=None):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, partial(_update_outline_node_sync, node_id, title, content))
    # 触发画布更新事件
    try:
        data = json.loads(result)
        if data.get("success"):
            emit = _get_emit()
            if emit:
                await emit("nodes_updated", {"action": "update", "node_id": node_id})
    except:
        pass
    return result


async def _delete_outline_node_async(node_id, delete_children=True, reason=None):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, partial(_delete_outline_node_sync, node_id, delete_children))
    # 触发画布更新事件
    try:
        data = json.loads(result)
        if data.get("success"):
            emit = _get_emit()
            if emit:
                await emit("nodes_updated", {"action": "delete", "node_id": node_id})
    except:
        pass
    return result


async def _analyze_outline_structure_async():
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _analyze_outline_structure_sync)


async def _expand_macro_node_async(macro_node_id: str, description: str = "", reason=None):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, partial(_expand_macro_node_sync, macro_node_id, description, reason))
    # 触发画布更新事件
    try:
        data = json.loads(result)
        if data.get("success"):
            emit = _get_emit()
            if emit:
                await emit("nodes_updated", {"action": "expand", "node_type": "macro", "count": data.get("count", 0)})
    except:
        pass
    return result


async def _expand_meso_node_async(meso_node_id: str, description: str = "", reason=None):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, partial(_expand_meso_node_sync, meso_node_id, description, reason))
    # 触发画布更新事件
    try:
        data = json.loads(result)
        if data.get("success"):
            emit = _get_emit()
            if emit:
                await emit("nodes_updated", {"action": "expand", "node_type": "meso", "count": data.get("count", 0)})
    except:
        pass
    return result


# ========== 创建工具 ==========

create_macro_outline = StructuredTool.from_function(
    coroutine=_create_macro_outline_async,
    func=_create_macro_outline_sync,
    name="create_macro_outline",
    description="批量创建宏观大纲节点（故事阶段）。传入标题列表，自动建立顺序连线。一次调用即可创建所有宏观阶段。",
    args_schema=CreateMacroOutlineInput,
)

create_meso_outline = StructuredTool.from_function(
    coroutine=_create_meso_outline_async,
    func=_create_meso_outline_sync,
    name="create_meso_outline",
    description="批量创建中纲节点（场景/事件）。传入父宏观节点ID和标题列表，自动建立包含和顺序连线。一次调用即可创建该阶段下的所有中纲。",
    args_schema=CreateMesoOutlineInput,
)

create_micro_outline = StructuredTool.from_function(
    coroutine=_create_micro_outline_async,
    func=_create_micro_outline_sync,
    name="create_micro_outline",
    description="批量创建小纲节点（具体情节）。传入父中纲节点ID和标题列表，自动建立包含和顺序连线。一次调用即可创建该场景下的所有小纲。",
    args_schema=CreateMicroOutlineInput,
)

create_outline_sequence = StructuredTool.from_function(
    coroutine=_create_outline_sequence_async,
    func=_create_outline_sequence_sync,
    name="create_outline_sequence",
    description="为节点列表创建顺序连线。",
    args_schema=CreateOutlineSequenceInput,
)

update_outline_node = StructuredTool.from_function(
    coroutine=_update_outline_node_async,
    func=_update_outline_node_sync,
    name="update_outline_node",
    description="更新大纲节点的标题或内容。",
    args_schema=UpdateOutlineNodeInput,
)

delete_outline_node = StructuredTool.from_function(
    coroutine=_delete_outline_node_async,
    func=_delete_outline_node_sync,
    name="delete_outline_node",
    description="删除大纲节点，可选择是否删除子节点。",
    args_schema=DeleteOutlineNodeInput,
)

analyze_outline_structure = StructuredTool.from_function(
    coroutine=_analyze_outline_structure_async,
    func=_analyze_outline_structure_sync,
    name="analyze_outline_structure",
    description="分析大纲结构并提供建议。",
)

expand_macro_node = StructuredTool.from_function(
    coroutine=_expand_macro_node_async,
    func=_expand_macro_node_sync,
    name="expand_macro_node",
    description="展开宏观节点：自动使用LLM生成中纲标题并创建中纲子节点。只需传入宏观节点ID和可选的描述，工具会自动生成标题、创建节点、建立连线。",
    args_schema=ExpandMacroNodeInput,
)

expand_meso_node = StructuredTool.from_function(
    coroutine=_expand_meso_node_async,
    func=_expand_meso_node_sync,
    name="expand_meso_node",
    description="展开中纲节点：自动使用LLM生成小纲标题并创建小纲子节点。只需传入中纲节点ID和可选的描述，工具会自动生成标题、创建节点、建立连线。",
    args_schema=ExpandMesoNodeInput,
)


# ========== 导出 ==========

outline_tools = [
    create_macro_outline,
    create_meso_outline,
    create_micro_outline,
    create_outline_sequence,
    update_outline_node,
    delete_outline_node,
    analyze_outline_structure,
    expand_macro_node,
    expand_meso_node,
]
