"""Canvas 布局常量"""

# 节点尺寸
# 必须与前端 CustomNode 的固定尺寸保持一致。
# 布局工具依赖这个矩形向 Agent 返回重叠、紧贴和过近反馈。
NODE_WIDTH = 250
NODE_HEIGHT = 120

# element 节点为圆形，尺寸更小（前端 CustomNode 圆形容器一致）
ELEMENT_WIDTH = 90
ELEMENT_HEIGHT = 90

# 间距
LAYER_GAP_Y = 120
NODE_GAP_X = 40
PADDING = 50
