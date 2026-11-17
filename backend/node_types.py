"""Canvas 节点类型与作用域(scope)的统一定义。

节点类型（仅以下 5 种合法，创建/更新节点时强制校验）：
  正文节点：chapter(章节)，按作品内 sort_order 排序
  关联节点：character(角色) — 完整实体，不在画布上显示；章节通过 extra_data.characters 引用
  全局节点：worldbuilding(世界观)、note(笔记)、reviewer_note(评审笔记)

作用域 scope（5 值，按类型受限）：
  global — 全局（worldbuilding/note/reviewer_note 固定；character 表示主角）
  local  — 章节（chapter 固定）
  major  — 主要配角（仅 character）
  minor  — 次要配角（仅 character，默认）
  temp   — 临时角色（仅 character）
character 不允许 local（已废弃），默认 minor。
"""

STANDARD_NODE_TYPES = frozenset({
    "character",
    "chapter",
    "worldbuilding",
    "note",
    "reviewer_note",
})


def validate_node_type(node_type: str) -> str:
    normalized = (node_type or "").strip()
    if normalized not in STANDARD_NODE_TYPES:
        allowed = ", ".join(sorted(STANDARD_NODE_TYPES))
        raise ValueError(f"不支持的节点类型: {node_type!r}。可用类型: {allowed}")
    return normalized


# ---- 作用域 scope ----

SCOPE_GLOBAL = "global"
SCOPE_LOCAL = "local"
SCOPE_MAJOR = "major"
SCOPE_MINOR = "minor"
SCOPE_TEMP = "temp"

STANDARD_SCOPES = frozenset({
    SCOPE_GLOBAL, SCOPE_LOCAL, SCOPE_MAJOR, SCOPE_MINOR, SCOPE_TEMP,
})

# 固定为 global 的类型：worldbuilding/note/reviewer_note（全局节点）
GLOBAL_LOCKED_TYPES = frozenset({"worldbuilding", "note", "reviewer_note"})
# 固定为 local 的类型：章节 chapter
LOCAL_LOCKED_TYPES = frozenset({"chapter"})
# character 允许的 scope（角色分类：主角/主要配角/次要配角/临时）
CHARACTER_SCOPES = frozenset({SCOPE_GLOBAL, SCOPE_MAJOR, SCOPE_MINOR, SCOPE_TEMP})


def validate_scope(scope: str) -> str:
    normalized = (scope or "").strip()
    if normalized not in STANDARD_SCOPES:
        allowed = ", ".join(sorted(STANDARD_SCOPES))
        raise ValueError(f"不支持的作用域: {scope!r}。可用作用域: {allowed}")
    return normalized


def allowed_scopes_for_type(node_type: str) -> frozenset:
    """返回某节点类型允许的 scope 集合。"""
    if node_type in GLOBAL_LOCKED_TYPES:
        return frozenset({SCOPE_GLOBAL})
    if node_type in LOCAL_LOCKED_TYPES:
        return frozenset({SCOPE_LOCAL})
    if node_type == "character":
        return CHARACTER_SCOPES
    return frozenset({SCOPE_LOCAL})


def default_scope_for_type(node_type: str) -> str:
    """按类型返回默认 scope：worldbuilding/note/reviewer_note→global，character→minor，章节→local。"""
    if node_type in GLOBAL_LOCKED_TYPES:
        return SCOPE_GLOBAL
    if node_type == "character":
        return SCOPE_MINOR
    return SCOPE_LOCAL


def resolve_scope(node_type: str, proposed_scope):
    """创建节点时按类型解析最终作用域。

    - proposed_scope 为 None：取类型默认值；
    - proposed_scope 非空：先校验合法性，再校验该类型是否允许此值。
    """
    validate_node_type(node_type)
    if proposed_scope is None:
        return default_scope_for_type(node_type)
    scope = validate_scope(proposed_scope)
    allowed = allowed_scopes_for_type(node_type)
    if scope not in allowed:
        raise ValueError(
            f"{node_type} 不支持作用域 {scope!r}，可用: {sorted(allowed)}"
        )
    return scope


def resolve_update_scope(old_type, old_scope, new_type, proposed_scope):
    """更新节点时解析最终作用域（纯函数，供 router 与工具复用）。

    - 显式传 scope：校验合法性 + 该类型是否允许；
    - 未传 scope 但改了类型(new_type 非空)：按新类型默认值重置；
    - 未传 scope 且未改类型：保持 old_scope。
    """
    final_type = new_type or old_type
    if new_type is not None:
        validate_node_type(new_type)
    if proposed_scope is not None:
        scope = validate_scope(proposed_scope)
        allowed = allowed_scopes_for_type(final_type)
        if scope not in allowed:
            raise ValueError(
                f"{final_type} 不支持作用域 {scope!r}，可用: {sorted(allowed)}"
            )
        return scope
    if new_type is not None:
        return default_scope_for_type(final_type)
    return old_scope


NODE_TYPES_RULES_TEXT = (
    "支持 5 种节点：chapter（章节）、character（角色）、worldbuilding（世界观）、note（笔记）、reviewer_note（评审笔记）。"
    "章节直接归属作品，按 sort_order 排序。长期故事规划保存到 note，逐章计划保存到章节笔记。"
    "reviewer_note 由 Supervisor 维护，其最新全文自动注入 Reviewer 系统提示词。"
    "出场角色使用 characters 参数，每项含角色 id 与 name。"
    "角色发展线使用 storylines 参数，每项含 name、description、body 字符串列表。"
)

EDGE_ENDPOINT_RULES_TEXT = (
    "章节顺序通过 sort_order 表达，章节出场角色通过 chapter.extra_data.characters 表达。"
    "worldbuilding、note、reviewer_note 是全局资料，character 是章节引用的角色资料。"
)

EDGE_CONNECTION_RULES_TEXT = "连接点由程序按节点相对位置自动计算。"

NODE_LAYOUT_RULES_TEXT = (
    "章节位置由前端自动布局，sort_order 决定作品内的章节顺序。"
    "节点工具负责保存内容与顺序。"
)

NODE_SORT_ORDER_RULES_TEXT = (
    "sort_order 是必填整数，决定作品内同类型节点的显示顺序。"
    "章节按叙事先后依次使用 1、2、3……，调整章节顺序时更新 sort_order。"
)

MISSING_SORT_ORDER_ERROR = (
    "创建节点必须提供 sort_order（同级显示顺序，整数）。"
    "同一作品内同类型节点按它从小到大排列，请按叙事先后依次给出 1、2、3……"
)


def validate_edge_endpoints(source_type: str, target_type: str, source_scope: str = "", target_scope: str = "") -> str | None:
    """校验连线端点限制。返回错误消息或 None（合法）。规则见 EDGE_ENDPOINT_RULES_TEXT。"""
    if source_type == "character" or target_type == "character":
        return (
            "角色不是画布连线端点。章节出场角色请写入 extra_data.characters，"
            "每项必须含角色节点 id 与 name。"
        )
    if source_scope == "global" or target_scope == "global":
        return "全局节点(scope=global：主角/worldbuilding/note/reviewer_note)禁止创建关联线"
    if source_type == "element" or target_type == "element":
        return "element 不再是画布节点类型，不要创建 element 连线"
    return None
