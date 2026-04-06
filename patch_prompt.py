import re

with open('backend/main.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = (
    '        system_msg = {"role": "system", "content": (\n'
    '            "你是一个天气意图分类器。结合对话历史判断用户当前是否在询问天气或气象相关问题。\\n"\n'
    '            "规则：\\n"\n'
    '            "1. 如果是天气相关，提取城市名并只输出城市名（如\u201c成都\u201d\u201c北京\u201d）。\\n"\n'
    '            "2. 如果是天气相关但未提及城市（如\u201c那明天呢\u201d\u201c会下雨吗\u201d），从对话历史中推断城市并输出城市名；如果历史中也没有城市，输出 NONE。\\n"\n'
    '            "3. 如果不是天气相关（如打招呼、算数、聊天等），输出 NOT_WEATHER。\\n"\n'
    '            "只输出一个词，不要其他内容。"\n'
    '        )}'
)

new = (
    '        system_msg = {"role": "system", "content": (\n'
    '            "你是一个对话意图分类器。结合对话历史判断用户当前话语的意图。只输出一个词，不要其他内容。\\n"\n'
    '            "规则：\\n"\n'
    '            "1. 天气/气象相关提问 -> 提取城市名（如成都）；无城市则从历史推断；历史也无则输出 NONE\\n"\n'
    '            "2. 明确要结束对话（如再见、不聊了、我走了、不问了）-> 输出 EXIT\\n"\n'
    '            "3. 明确提问但与天气无关（如你叫什么名字、5加5等于几）-> 输出 NOT_WEATHER\\n"\n'
    '            "4. 不是提问（陈述句、感叹词、回应如好的、嗯、谢谢、哦、知道了）-> 输出 IGNORE"\n'
    '        )}'
)

if old in content:
    content = content.replace(old, new)
    with open('backend/main.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('OK: prompt updated to 4-class')
else:
    print('NOT FOUND - checking actual content around system_msg...')
    idx = content.find('system_msg = {"role": "system"')
    if idx >= 0:
        print(repr(content[idx:idx+500]))
    else:
        print('system_msg not found at all')
