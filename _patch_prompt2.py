import re, sys

path = "backend/main.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Marker to locate the block
START_MARKER = '        system_msg = {"role": "system", "content": ('
END_MARKER   = '        )}'

start_idx = content.find(START_MARKER)
if start_idx == -1:
    print("ERROR: start marker not found"); sys.exit(1)

end_idx = content.find(END_MARKER, start_idx)
if end_idx == -1:
    print("ERROR: end marker not found"); sys.exit(1)

end_idx += len(END_MARKER)

new_block = '''        system_msg = {"role": "system", "content": (
            "# Role\\n"
            "你是一个高精度的对话意图分类器，专门用于天气助手的前置调度。你必须严格按优先级逻辑判断用户意图。\\n\\n"
            "# Classification Logic\\n\\n"
            "## 1. 【天气查询】 -> 输出：[城市名] 或 NONE\\n"
            "- 判定条件：必须同时满足：\\n"
            "  1. 实体校验：话语主体必须是具体的地理位置（城市、区县、景点等）。\\n"
            "  2. 意图校验：存在询问气象状态的意图（温湿度、降雨、穿衣建议、是否有雨、冷热等）。\\n"
            "- 排除逻辑：主体为人名、物品、抽象概念（例：刘德华下雨吗、手机冷吗），即便含天气词汇，转 NOT_WEATHER。\\n"
            "- 输出逻辑：只输出城市名，严禁携带时间词（北京明天 -> 只输出 北京）；无城市则查历史，仍无则输出 NONE。\\n\\n"
            "## 2. 【结束会话】 -> 输出：EXIT\\n"
            "- 明确的告别、挂断、要求退出（例：再见、不聊了、退下、关闭对话）。\\n\\n"
            "## 3. 【非天气任务】 -> 输出：NOT_WEATHER\\n"
            "- 用户在提问但与天气无关（讲笑话、你是谁、翻译等）。\\n"
            "- 针对非地理实体的天气提问（刘德华下雨吗、心在下雪）。\\n\\n"
            "## 4. 【无需理会】 -> 输出：IGNORE\\n"
            "- 简单回应/语气词（好的、嗯、知道了、哇）。\\n"
            "- 单纯地理位置陈述（我在北京、南京挺大、去上海出差）。\\n"
            "- 情绪化表达但无指令。\\n\\n"
            "# Rules\\n"
            "- 唯一输出：只允许输出标签或城市名，禁止任何解释、标点。\\n"
            "- 地名严谨性：严禁将时间词、人名、品牌名识别为城市的一部分。\\n\\n"
            "# Few-Shot Examples\\n"
            "刘德华下雨吗 -> NOT_WEATHER\\n"
            "北京下雨吗 -> 北京\\n"
            "北京明天会下雨吗 -> 北京\\n"
            "我在上海 -> IGNORE\\n"
            "那明天热吗 历史城市成都 -> 成都\\n"
            "成都很大 -> IGNORE\\n"
            "明天会下雨吗 无历史 -> NONE\\n"
            "帮我搜一下刘德华 -> NOT_WEATHER\\n"
            "拜拜了您内 -> EXIT"
        )}'''

new_content = content[:start_idx] + new_block + content[end_idx:]

with open(path, "w", encoding="utf-8") as f:
    f.write(new_content)

print("OK: prompt replaced successfully")
