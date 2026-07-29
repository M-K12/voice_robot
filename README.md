# 🤖 Voice Robot 小安智能语音机器人

> 基于 **FastAPI (Python) + Tauri (Vue 3 + Rust) + Sherpa-onnx (端侧 KWS) + Qwen-Omni / Qwen-Audio Realtime** 构建的全双工实时语音交互机器人。

---

## 🌟 核心特性 (Key Features)

1. **🎙️ 端到端全双工语音交互 (E2E Realtime Voice)**
   - 支持阿里百炼 `Qwen-Omni-Realtime` 与 `Qwen-Audio-Realtime` 双模型低延迟 WebSocket 流式语音对话；
   - 实时流式 ASR 识别展示与文本/语音双通道并发。

2. **⚡ 端侧轻量化唤醒词打断 (Sherpa-onnx KWS Interception)**
   - 结合 Rust 侧 Sherpa-onnx 引擎实现极低延迟客户端本地打断；
   - **打断拦截模式 (`interruptionMode`)**：支持 `wake_word_only` (唤醒词打断) 与 `any_speech` (任意说话打断)。在 AI 播放音频期间，麦克风音频流自动切换并留在端侧 KWS，避免无效音频上云，极大节省 Token 成本。

3. **👋 智能退出意图与系统提示音 (Exit Intent & System Audio)**
   - 全局标点符号剥离唤醒正则匹配（`is_wake_word`）；
   - 识别到退出指令（如“退下”、“小安退下”、“去休息吧”、“再见”）时，自动输出“再见”并播放 `exit_female.wav` 告别音后软挂断断开。

4. **🌆 聚焦城市三级优先级决策与动态 API (3-Tier City Priority)**
   - **优先级级联**：`HTTP API 动态覆盖` > `本地配置文件` > `IP 自动定位`；
   - 支持通过 `POST /api/city` 接口在线更新聚焦城市，自动联动 WebSocket 全网广播与大屏天气卡片刷新。

5. **🖥️ 大屏视觉同步广播 (Visual Broadcast Manager)**
   - 独立的 WebSocket 广播通道（`/ws/visual`），支持实时状态推演（`listening` / `speaking` / `idle` / `weather` / `restore_location`）。

---

## 🛠️ 项目架构 (Architecture)

```text
voice_robot/
├── backend/                  # Python FastAPI 后端服务
│   ├── main.py               # 后端主入口 & REST API & WS 路由
│   ├── qwen_omni_realtime_handler.py   # Qwen-Omni Realtime 通道句柄
│   ├── qwen_audio_realtime_handler.py  # Qwen-Audio Realtime 通道句柄
│   ├── utils.py              # 工具库 (唤醒词正则/退出意图/IP定位/网络)
│   ├── tools/                # Tool Calling 架构 (天气/应急/大屏地图/挂断等)
│   └── assets/               # 离线系统提示音 (zai_female.wav, exit_female.wav)
├── src/                      # Vue 3 前端界面
│   ├── App.vue               # 主逻辑 & 控制台 & 全屏模式
│   └── components/           # UI 组件 (WeatherCard, VoiceWave, DebugLogs)
├── src-tauri/                # Rust 侧核心引擎
│   ├── src/lib.rs            # Rust KWS KeywordSpotter & 音频流拾取
│   └── Cargo.toml            # Rust 依赖配置
├── configs/                  # 模型与全局配置文件
└── sherpa/                   # Sherpa-onnx 本地模型与 C++ 静态库
```

---

## 🚀 快速启动 (Getting Started)

### 1. 环境准备
- **Python**: 3.11+ (推荐使用 `uv`)
- **Node.js**: 18+ (推荐 `npm`)
- **Rust**: 最新 stable 版本 (支持 Tauri 编译)

### 2. 启动后端 (Python FastAPI)

```bash
# 使用 uv 推荐启动 (默认监听端口 10850)
uv run python backend/main.py

# 或使用虚拟环境解释器启动
.\.venv\Scripts\python.exe backend/main.py
```

### 3. 启动前端 (Tauri + Vue 3)

```bash
# 在新的终端窗口中运行
npm run tauri dev
```

---

## 📡 开放 REST API 接口文档 (Open APIs)

> 💡 详细的三接口规格说明（含请求头、参数列表、curl 示例与完整 JSON 响应结构）请参阅独立文档 **[API.md](file:///d:/projects/xiaoan/voice_robot/API.md)**。

### 1. 用户信息与聚焦城市接口 (`POST /api/user_info`)

| 接口方法 | 路由路径 | 说明 |
| :--- | :--- | :--- |
| `POST` | `/api/user_info` | 动态推送/更新全量用户信息（`areaName`, `tenantName`, `userName`, `orgName` 等），并联动全网广播与天气刷新 |
| `GET` | `/device_id` | 获取当前设备的 32 位 UUID 唯一标识 |

#### POST /api/user_info 请求示例：
```bash
curl -X POST http://127.0.0.1:10850/api/user_info \
  -H "Content-Type: application/json" \
  -d '{
    "timestamp": "2026-07-29 17:50:21",
    "tenantId": "37d179eee0c045aea2884ecc7c45c086",
    "userId": "51460163d42a4db0b290e5f0fee88e4d",
    "orgId": "61a03345abf140ae9ad6ebb54c6c9479",
    "tenantType": "",
    "areaCode": "341021",
    "tenantName": "歙县综合减灾会商研判系统",
    "userName": "sxyjj",
    "orgName": "小安知险县域终端",
    "tenantTypeName": "应急管理",
    "areaName": "歙县"
  }'
```
响应：
```json
{
  "status": "success",
  "user_info": {
    "timestamp": "2026-07-29 17:50:21",
    "tenantId": "37d179eee0c045aea2884ecc7c45c086",
    "userId": "51460163d42a4db0b290e5f0fee88e4d",
    "orgId": "61a03345abf140ae9ad6ebb54c6c9479",
    "tenantType": "",
    "areaCode": "341021",
    "tenantName": "歙县综合减灾会商研判系统",
    "userName": "sxyjj",
    "orgName": "小安知险县域终端",
    "tenantTypeName": "应急管理",
    "areaName": "歙县",
    "effective_city": "歙县",
    "priority_source": "HTTP API Override"
  }
}
```

---

### 2. 系统离线提示音静态服务

后端已使用 FastAPI `StaticFiles` 挂载 `backend/assets` 目录为 `/assets` 静态资源服务：

* **唤醒答复音路径**: `GET http://127.0.0.1:10850/assets/zai_female.wav`
* **退出告别音路径**: `GET http://127.0.0.1:10850/assets/exit_female.wav`

---

## ⚙️ 配置文件说明 (Configuration)

- `configs/global.json`: 全局服务器配置、日志级别、默认聚焦城市；
- `configs/kws_config.json`: 本地 Sherpa-onnx 唤醒词评分与门限阈值；
- `configs/models/voice_e2e/`: 各端到端语音大模型的专属配置（音色、VAD 阈值、Token 数等）。
