"""工具分组的累计审阅快照，文本及位置使用关系字段保存。"""
from sqlalchemy import Column, ForeignKey, Integer, String, Text
from database import Base


class NodeAgentDiffState(Base):
    __tablename__ = "node_agent_diff_states"
    node_id = Column(String(36), ForeignKey("nodes.id", ondelete="CASCADE"), primary_key=True)
    baseline_content = Column(Text, nullable=False)


class NodeAgentDiffGroup(Base):
    __tablename__ = "node_agent_diff_groups"
    node_id = Column(String(36), ForeignKey("node_agent_diff_states.node_id", ondelete="CASCADE"), primary_key=True)
    group_index = Column(Integer, primary_key=True)
    start_offset = Column(Integer, nullable=False)
    old_text = Column(Text, nullable=False)
    new_text = Column(Text, nullable=False)
