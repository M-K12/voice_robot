---
name: remove-weather-chatbubble
overview: 去掉天气卡片场景中重复的 ChatBubble 文本气泡，仅保留 WeatherCard 组件展示天气信息；并在通用设置中新增"展示天气卡片"开关。
todos:
  - id: remove-weather-chatbubble
    content: 修改 src/App.vue：移除 weather_data 中的 ChatBubble push 逻辑、删除 weather_summary 事件处理、简化 output_transcript 的 isWeather 守卫
    status: completed
  - id: add-show-weather-card-setting
    content: 修改 src/App.vue：在 settings 对象中新增 showWeatherCard 字段、两处通用设置面板新增复选框、WeatherCard v-if 条件增加设置判断、saveSettings 追加持久化
    status: completed
---

## 用户需求
1. 去掉天气卡片场景中重复的 ChatBubble 文本气泡，仅保留 WeatherCard 视觉组件展示天气信息
2. 在通用设置面板中新增"展示天气卡片"复选框，用户可自行控制是否显示 WeatherCard

## 产品概述
Vue 3 语音助手前端应用，当前天气数据到达时 WeatherCard 和 ChatBubble 文本消息同时渲染导致内容重复。通过移除 ChatBubble 文本路径并新增设置项，让用户体验更简洁，同时赋予用户对天气卡片显示的自主控制权。

## 核心功能
- 天气数据仅通过 WeatherCard 组件展示，不再生成文本气泡
- 通用设置中提供"展示天气卡片"开关，默认开启
- 关闭开关后天气数据不再显示 WeatherCard，仅保留语音播报等原有行为


## 技术栈
- 前端框架：Vue 3 (Composition API) + Vite
- 状态管理：reactive / ref 响应式数据
- 持久化：localStorage + 后端 /config API

## 实现方案

### 改动策略
所有修改集中在 `src/App.vue` 单文件，共 7 处改动，均为删除冗余代码或新增简单设置项。

### 改动点详情

**1. 移除 weather_data 中的 ChatBubble push 逻辑（第 2096-2106 行）**
- 当前：`weatherData.value = msg.data` 后，push 了一条 `isWeather: true` 的消息，再 `scrollToBottom()`
- 修改后：仅保留 `weatherData.value = msg.data` + `scrollToBottom()`，删除中间的 push 块及注释

**2. 移除 weather_summary 事件处理（第 2107-2113 行）**
- 整段删除 `else if (msg.type === 'weather_summary')` 分支
- 原因：不再有 `isWeather` 标记的 ChatBubble 需要更新

**3. 简化 output_transcript 中的 isWeather 守卫（第 2078 行）**
- 当前条件：`lastMsg.isVoiceWs && !lastMsg.isWeather`
- 修改为：`lastMsg.isVoiceWs`
- 原因：`isWeather` 标记已随 ChatBubble 一起移除，条件中的 `!lastMsg.isWeather` 不再需要

**4. settings 对象新增 showWeatherCard 字段（第 1384 行附近）**
- 在 `enableVisualBroadcast: true,` 之后新增：`showWeatherCard: localStorage.getItem('showWeatherCard') !== 'false'`
- 默认 true，支持 localStorage 持久化

**5. 两处通用设置面板新增复选框**
- 独立设置窗口（第 43-48 行 enableVisualBroadcast 复选框之后）：复用相同的 checkbox-group 模式
- 主窗口内嵌面板（第 715-723 行 enableVisualBroadcast 复选框之后）：同样复用

**6. WeatherCard v-if 条件增加设置判断（第 543 行）**
- 当前：`v-if="weatherData"`
- 修改为：`v-if="weatherData && settings.showWeatherCard"`

**7. saveSettings 追加 localStorage 持久化（第 2541 行之后）**
- 新增：`localStorage.setItem('showWeatherCard', settings.showWeatherCard)`

