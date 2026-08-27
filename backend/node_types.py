"""Canvas 节点类型与作用域(scope)的统一定义。

节点类型（仅以下 7 种合法，创建/更新节点时强制校验，不允许 agent 自创）：
  层级链：outline(大纲) → volume(卷) → plot(情节) → chapter(章节)
  关联节点：character(角色) — 需与相关章节/情节等节点连接
  情节元素：不再作为独立节点创建，存放在 chapter.extra_data.chapter_elements
  全局节点：worldbuilding(世界观)、note(笔记)

作用域 scope（5 值，按类型受限）：
  global — 全局（worldbuilding/note 固定；character 表示主角）
  local  — 局部层级链（outline/volume/plot/chapter 固定）
  major  — 主要配角（仅 character）
  minor  — 次要配角（仅 character，默认）
  temp   — 临时角色（仅 character）
character 不允许 local（已废弃），默认 minor。
"""

STANDARD_NODE_TYPES = frozenset({
    "character",
    "outline",
    "volume",
    "plot",
    "chapter",
    "worldbuilding",
    "note",
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

# 固定为 global 的类型：worldbuilding/note（全局节点）
GLOBAL_LOCKED_TYPES = frozenset({"worldbuilding", "note"})
# 固定为 local 的类型：层级链 outline/volume/plot/chapter
LOCAL_LOCKED_TYPES = frozenset({"outline", "volume", "plot", "chapter"})
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
    """按类型返回默认 scope：worldbuilding/note→global，character→minor，层级链→local。"""
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
    "仅限 7 种：character, outline, volume, plot, chapter, worldbuilding, note。"
    "element 不再是节点类型；章节元素请在创建/更新 chapter 时使用 chapter_elements 参数。"
    "角色发展线请在创建/更新 character 时使用 storylines 参数（写入 extra_data.storylines；"
    "每项含 name、description、body 字符串列表），不要把发展线只写进 content。"
    "禁止自创 event/idea/setting 等其它类型；非法类型会报错并列出可用值。"
)

EDGE_ENDPOINT_RULES_TEXT = (
    "端点限制（违反会报错）："
    "scope=global 的节点（worldbuilding/note + 主角 character）禁止任何连线。"
)

EDGE_CONNECTION_RULES_TEXT = (
    "连接点由程序自动计算，无需指定方向："
    "chapter↔chapter 固定源节点右边界→目标节点左边界；"
    "outline/volume/plot/chapter 之间固定源下边界→目标上边界；"
    "其它节点按相对位置自动选择。"
)

NODE_LAYOUT_RULES_TEXT = (
    "画布节点位置布局（position_x/position_y/layer，前端不会自动重排）："
    "① character 位于画布左侧，纵向排列（position_y 递增）；"
    "② note、worldbuilding 位于画布左侧；"
    "③ outline/volume/plot/chapter 从上到下层级排列（Y 随层级递增），"
    "同级多个节点水平排列（position_x 错开）。"
)


def validate_edge_endpoints(source_type: str, target_type: str, source_scope: str = "", target_scope: str = "") -> str | None:
    """校验连线端点限制。返回错误消息或 None（合法）。规则见 EDGE_ENDPOINT_RULES_TEXT。"""
    if source_type == "character" and target_type == "character":
        return "角色之间的关系请使用 character_relations，不要用画布关联线"
    if source_scope == "global" or target_scope == "global":
        return "全局节点(scope=global：主角/worldbuilding/note)禁止创建关联线"
    if source_type == "element" or target_type == "element":
        return "element 不再是画布节点类型；章节元素请写入 chapter.extra_data.chapter_elements，不要创建 element 连线"
    return None


def validate_character_relation(source_type: str, target_type: str) -> str | None:
    """校验角色关系线端点：两端必须是 character。"""
    if source_type != "character" or target_type != "character":
        return "角色关系线的两端必须是 character 节点"
    return None


def validate_relation_type(relation_type: str) -> str:
    """自然语言关系类型：非空，最长 100 字符。"""
    normalized = (relation_type or "").strip()
    if not normalized:
        raise ValueError("关系类型不能为空")
    if len(normalized) > 100:
        raise ValueError("关系类型不能超过100字符")
    return normalized
