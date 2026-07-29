"""
小安气象机器人 - 模拟天气数据提供者
用于开发调试、离线测试或备用保底。
"""

import random
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

# 模拟天气状况库
MOCK_CONDITIONS = [
    {"condition": "sunny", "label": "晴", "icon": "☀️"},
    {"condition": "cloudy", "label": "多云", "icon": "⛅"},
    {"condition": "rainy", "label": "小雨", "icon": "🌧️"},
    {"condition": "thunderstorm", "label": "雷阵雨", "icon": "⛈️"},
    {"condition": "foggy", "label": "大雾", "icon": "🌫️"},
    {"condition": "snowy", "label": "小雪", "icon": "❄️"},
]

def generate_mock_weather(city: str, date: str, days: int = 1, lng: float = None, lat: float = None) -> Dict[str, Any]:
    """生成结构完整的模拟天气数据"""
    cond = random.choice(MOCK_CONDITIONS)
    base_temp = random.randint(-5, 35)
    forecast = []

    for i in range(max(days, 1)):
        d = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=i)).strftime("%Y-%m-%d")
        f_cond = random.choice(MOCK_CONDITIONS)
        forecast.append({
            "date": d,
            "label": f_cond["label"],
            "icon": f_cond["icon"],
            "condition": f_cond["condition"],
            "temp_high": base_temp + random.randint(0, 8),
            "temp_low": base_temp - random.randint(2, 10),
            "humidity": random.randint(20, 90),
            "wind_direction": random.choice(["东北", "东南", "西南", "西北"]) + "风",
            "wind_level": f"{random.randint(1, 6)}级",
        })

    current = forecast[0]
    summary = (
        f"今天{city}{cond['label']}，"
        f"最高气温{current['temp_high']}度，最低{current['temp_low']}度，"
        f"{current['wind_direction']}{current['wind_level']}，"
        f"空气质量{'优' if random.random() > 0.5 else '良'}。"
    )

    return {
        "city": city,
        "date": date,
        "current": {
            "condition": cond["condition"],
            "label": cond["label"],
            "icon": cond["icon"],
            "temp_c": base_temp,
            "feels_like_c": base_temp - random.randint(0, 4),
            "humidity": current["humidity"],
            "wind_direction": current["wind_direction"],
            "wind_level": current["wind_level"],
            "air_quality": random.choice(["优", "良", "轻度污染"]),
            "aqi": random.randint(20, 150),
            "uv_index": random.randint(1, 10),
        },
        "forecast": forecast,
        "summary": summary,
        "lng": lng, # 使用传入的经度
        "lat": lat, # 使用传入的纬度
        "alerts": [
            {
                "title": f"{city}气象台发布寒潮蓝色预警[IV/一般]",
                "type": "寒潮蓝色",
                "level": "蓝色",
                "color": "#4fc3f7",
                "content": f"{city}气象台发布寒潮蓝色预警，受强冷空气影响，预计未来48小时内该地区最低气温降幅可达8℃以上，高海拔山区将出现强降雪，请注意防范。",
                "pub_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "advice": ["加固门窗", "注意保暖", "减少出行"]
            }
        ]
    }
