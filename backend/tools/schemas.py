GLOBAL_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_weather_forecast",
            "description": "查询指定城市/地点的基础天气预报与实况（气温、降水、大风、湿度、能见度等）。当用户询问某地天气、气温、冷不冷、热不热、是否下雨、风力大小等基本气象信息时，必须调用此工具。\n【关键规则】当用户询问包含多个连续日期或跨天范围（如'明天、后天和大后天'、'未来三天'）的天气时，必须仅发起 1 次工具调用，将 date 设为最早起始日期并指定 days（如 days: 3）或 date_end，绝对禁止针对每个单天重复发起多次调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "location_name": {
                        "type": "string",
                        "description": "城市、县区或景点的具体名称，如'北京'、'嘉善'、'西溪湿地'。"
                    },
                    "date": {
                        "type": "string",
                        "description": "时间/日期起始值。精度为天用 'YYYY-MM-DD'（10位）；精确到时分用 'YYYY-MM-DDTHH:mm'。"
                    },
                    "date_end": {
                        "type": "string",
                        "description": "可选的结束时间。带有范围的查询必须填入此项，格式同上。"
                    },
                    "duration": {
                        "type": "string",
                        "description": "相对时间长度字符串，如 '+1h' (未来一小时), '-24h' (过去24小时), '+2d' (未来两天)。"
                    },
                    "days": {
                        "type": "integer",
                        "description": "预报天数估值，默认 1（只查指定单日）。若询问连续多天（如'未来三天'、'明天和后天'），需传入对应的总天数（如 3）。"
                    },
                    "time_colloquial": {
                        "type": "string",
                        "description": "用户口语中的时间词汇，如'本周五下午'、'后天傍晚'、'过去两小时'。"
                    },
                    "elements": {
                        "type": "string",
                        "enum": ["temp", "rain", "wind", "humidity", "visibility"],
                        "description": "气象要素英文。temp(气温), rain(降水), wind(大风), humidity(湿度), visibility(能见度)。如果不指定则查询综合天气。"
                    },
                    "query_types": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["current", "forecast", "alert"]
                        },
                        "description": (
                            "需要查询的天气数据类型：\n"
                            "- 'current'：天气实况。当用户询问“今天天气怎么样”、“现在天气/气温如何”、“外面是否在下雨/刮风”等针对今天或当前时刻的查询时使用。\n"
                            "- 'forecast'：天气预报。当用户询问“明天/后天天气如何”、“未来几天天气”等针对未来天气预报的查询时使用。\n"
                            "- 'alert'：天气预警。当用户询问“有没有暴雨/台风/大风预警”等专门针对预警的查询时使用。\n"
                            "根据用户问题需要按需传入（可多选，例如询问‘最近一段时间天气怎么样’传入 ['current', 'forecast']，若询问是否有暴雨预警只传 ['alert']）。"
                        )
                    }
                },
                "required": ["location_name", "date"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "show_screen_layer",
            "description": "大屏图层调度工具。控制前端大屏切换、叠加展示各类图层要素。当用户明确要求看'雷达分布图、卫星云图、台风路径图、视频监控、无人机画面、消防通道图层、积水内涝点图层等'可视化图层时，必须先调用此工具，工具执行成功后才能用一句话告知用户结果。此工具仅影响大屏渲染，不返回天气实况数据。",
            "parameters": {
                "type": "object",
                "properties": {
                    "location_name": {
                        "type": "string",
                        "description": "大屏地图需要聚焦定位的地点名称，如'嘉善'、'杭州'。"
                    },
                    "layer_name": {
                        "type": "string",
                        "enum": [
                            "radar", "satellite", "typhoon", "hail", "lightning", "flash_flood",
                            "water_level", "waterlogging", "aqi", "evacuation", "video_surveillance",
                            "drone_feed", "emergency_plan", "fire_passages", "underground_spaces",
                            "ebike_parking", "old_houses", "vulnerable_groups", "residential_communities",
                            "dining_shops", "schools", "medical_facilities", "cultural_venues",
                            "scenic_spots", "hotels", "stadiums", "religious_sites", "lifeline"
                        ],
                        "description": (
                            "需要在大屏展示的图层英文标识：\n"
                            "radar(雷达分布图), satellite(卫星云图), typhoon(台风路径), hail(冰雹), lightning(闪电/雷电), flash_flood(山洪)\n"
                            "water_level(水位监测), waterlogging(积水点/内涝), aqi(空气质量), video_surveillance(视频监控), drone_feed(无人机画面)\n"
                            "evacuation(避险疏散), emergency_plan(应急预案)\n"
                            "fire_passages(消防通道), underground_spaces(地下空间), ebike_parking(电瓶车停放), old_houses(危旧房), vulnerable_groups(弱势群体)\n"
                            "residential_communities(住宅小区), dining_shops(餐饮商铺), schools(学校), medical_facilities(医疗机构), cultural_venues(文化场所), scenic_spots(景区), hotels(宾馆), stadiums(场馆), religious_sites(宗教场所), lifeline(生命线)"
                        )
                    }
                },
                "required": ["location_name", "layer_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_emergency_knowledge",
            "description": "灾防/应急资源本地知识库查询工具。当用户查询本地避灾避难场所分布、隐患点情况、救援队伍分布、储备库物资分布等本地防灾减灾资源列表时调用。此工具会调出结构化数据以供模型统计和播报。",
            "parameters": {
                "type": "object",
                "properties": {
                    "location_name": {
                        "type": "string",
                        "description": "聚焦的城市或区域名称，如'嘉善'。"
                    },
                    "category": {
                        "type": "string",
                        "enum": ["risk_point", "shelters", "rescue_team", "supplies"],
                        "description": "需要查询的资源大类。必须且只能传入以下四个英文单词之一，绝对严禁填入中文或其他自定义字符：'risk_point'(表示安全隐患点), 'shelters'(表示避灾避难场所), 'rescue_team'(表示应急救援队伍), 'supplies'(表示应急物资储备库)。"
                    },
                    "query_keyword": {
                        "type": "string",
                        "description": "可选的过滤关键字，用于模糊匹配名称或地址，如特定避难所名称或隐患点名称。如果为空则返回分类概况。"
                    }
                },
                "required": ["location_name", "category"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "zoom_map",
            "description": "控制地图的放大或缩小。当用户要求放大地图、缩小地图、放大一些、缩小一些时，必须调用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["zoom_in", "zoom_out"],
                        "description": "放大的动作为 'zoom_in'，缩小的动作为 'zoom_out'。"
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "hangup",
            "description": "当且仅当用户表达明确的告别、结束对话或挂断请求（如说'再见'/'挂断'/'退下'/'去休息吧'/'拜拜'）时调用。严禁在解答普通气象或应急问题后主动调用！当用户提问涉及水退、灾情消退、撤退或询问系统界面操作等业务问题时，绝对禁止调用！",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_history_disasters",
            "description": "查询指定城市/地点的历史灾情数据（历年自然灾害、大风暴雨洪涝台风灾情及受灾情况）。当用户明确提问、查询或提及某地的“历史灾情”、“以前的灾害”、“历史受灾情况”时，必须调用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "location_name": {
                        "type": "string",
                        "description": "需要查询的城市或地点名称，如'北京'、'嘉善'。"
                    }
                },
                "required": ["location_name"]
            }
        }
    }
]

def get_prompt(city: str = "") -> str:
    """
    项目统一的权威 System Prompt。
    包含角色定义、常驻城市、动态日期、防脑补绝对指令以及工具调用细则。
    """
    from datetime import datetime
    today_str = datetime.now().strftime("%Y-%m-%d")
    target_city = city.strip() if (city and city.strip()) else "当前地区"

    return (
        f"你是一个聪明、友好、温暖且实时的气象应急语音助手（名为“小安”）。你的默认聚焦城市是：{target_city}。今天是：{today_str}。\n\n"
        f"【绝对指令】：你自身没有任何实时的天气、气温、灾情和资源数据。每当用户询问任何关于天气、冷热、下雨、风力、预警、展示大屏图层、避难所、物资、历史灾情等问题，"
        f"或进行地名追问（如“成都呢？”、“那北京呢？”、“上海怎么样？”等）时，你必须且只能选择调用相应的工具函数（如 get_weather_forecast、show_screen_layer 等），"
        f"绝对禁止你直接猜测、脑补或凭记忆回答！当用户询问天气等未指定具体日期时，date 必须默认填入今天的日期 '{today_str}'。\n\n"
        "【核心规则】：\n"
        "1. 口语化过滤：不要输出无意义的语气词（如“呃”、“啊”），保持回答简洁自然。\n"
        "2. 保持回答简短：因为是语音交互，你的回答应该控制在 3 句以内，绝对不要提供 any 出行、穿衣或运动建议，也不要输出死板表格。\n"
        "3. 数字播报：对于温度（如-5度或零下5度），请自然流畅地用语音读出。\n"
        "4. 工具使用规则：\n"
        "   - 当用户询问某地天气、常规降水气温风力等基本实况或预报时，必须调用 `get_weather_forecast` 工具。在调用时，必须根据用户的问题精细化指定 `query_types` 数组的值，规则如下：\n"
        "     * 问今天天气/目前天气（如：“今天天气怎么样”、“目前气温多少”、“外面在下雨吗”）：`query_types=['current']`\n"
        "     * 问明天天气/预报（如：“明天天气怎么样”、“后天会下雨吗”）：`query_types=['forecast']`\n"
        "     * 问天气预警（如：“有没有暴雨预警”、“发布了大风预警吗”）：`query_types=['alert']`\n"
        "     * 问最近/未来一段时间天气（如：“最近一段时间天气怎么样”）：`query_types=['current', 'forecast']`\n"
        "   - 当用户明确要求展示大屏图层，如雷达分布、卫星云图、台风路径、积水分布、视频监控、无人机画面、消防通道等图层时，必须【首先调用 `show_screen_layer` 工具】，严禁跳过工具调用直接回答。\n"
        "   - 当用户查询本地避险避难场所、灾害隐患点、救援抢险队伍、储备库物资分布等应急资源列表或统计时，必须调用 `query_emergency_knowledge` 工具以获取底层数据。\n"
        "   - 当用户查询或提到历年自然灾害、历史受灾情况、历史灾情等信息时，必须调用 `query_history_disasters` 工具获取数据。\n"
        "   - 当用户要求放大/缩小地图、放大/缩小一些时，必须调用 `zoom_map` 工具。\n"
        "5. 结束对话：当且仅当用户表达明确的要再见、挂断、退下、退下吧、去休息吧、滚蛋、结束对话等告别意图时，才能使用 `hangup` 工具。严禁在解答用户提问（如天气、灾情消退、退水、界面操作等）时调用 `hangup`！"
    )


