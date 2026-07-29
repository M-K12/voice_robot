---
name: remove-weather-chatbubble
overview: 去掉天气卡片场景中重复的 ChatBubble 文本气泡，仅保留 WeatherCard 组件展示天气信息。
todos:
  - id: remove-weather-chatbubble
    content: 修改 src/App.vue：移除 weather_data 中的 ChatBubble push 逻辑和 weather_summary 更新逻辑，简化 output_transcript 中的 isWeather 守卫
    status: pending
---

## 用户需求
天气卡片展示时，WeatherCard 组件和 ChatBubble 文本消息同时出现，内容重复。需要去掉 ChatBubble 文本消息（"正在总结"提示及后续的天气总结文本），仅保留 WeatherCard 可视化卡片。

## 核心改动
- `weather_data` 事件处理：不再向消息列表 push ChatBubble，仅设置 `weatherData` 展示卡片
- `weather_summary` 事件处理：整段移除，因为不再有对应的 ChatBubble 需要更新
- 清理 `isWeather` 标记相关代码，保持代码整洁

## 修改策略
这是对现有代码的**精简删除**，不涉及新增逻辑，只需移除 WeatherCard 与 ChatBubble 重复渲染的部分。

## 修改文件

```
src/App.vue  # [MODIFY] 移除天气 ChatBubble 创建与更新逻辑，仅保留 WeatherCard 渲染
```

### 具体改动点

1. **`weather_data` 事件处理**（约第 2096-2106 行）
   - 保留：`weatherData.value = msg.data`
   - 删除：整个 `messages.value.push({...})` 块（包括 `isWeather` 标记、注释）
   - 保留：`scrollToBottom()`（卡片展示后仍需滚动）

2. **`weather_summary` 事件处理**（约第 2107-2113 行）
   - 整段删除（不再有 ChatBubble 需要更新）

3. **`output_transcript` 中的 `isWeather` 守卫**（约第 2078 行）
   - `!lastMsg.isWeather` 条件可简化，因为不再有任何消息携带 `isWeather` 标记
   - 直接移除该条件，保留 `lastMsg.isVoiceWs` 判断即可
