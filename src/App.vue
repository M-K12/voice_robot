<template>
  <div class="app-root">
    <!-- 动态背景 -->
    <div class="bg-mesh" aria-hidden="true">
      <div class="orb orb-1"></div>
      <div class="orb orb-2"></div>
    </div>

    <!-- 顶部工具栏 -->
    <header class="toolbar">
      <div class="toolbar-brand">
        <div class="brand-logo">✦</div>
        <span class="brand-name">Voice Robot</span>
      </div>
      <div class="toolbar-actions">
        <WakeWordIndicator
          :access-key="settings.picovoiceKey"
          :keyword-paths="[settings.keywordPathStart, settings.keywordPathStop]"
          :model-path="settings.modelPath"
          @wake="onWakeDetected"
          @mic-error="onMicError"
          @mic-recovered="onMicRecovered"
        />
        <button class="icon-btn" :class="{active: isFullscreen}" @click="toggleFullscreen" title="全屏">
          <span>{{ isFullscreen ? '⛶' : '⛶' }}</span>
        </button>
        <button class="icon-btn" :class="{active: isOnTop}" @click="toggleOnTop" title="置顶">
          <span>📌</span>
        </button>
        <button class="icon-btn" @click="showSettings = true" title="设置">⚙️</button>
        <button class="btn-clear" @click="clearChat">🗑</button>
      </div>
    </header>

    <!-- 主内容区 -->
    <main class="main-area">
      <!-- 左/主：对话区 -->
      <section class="chat-section">
        <div class="messages" ref="messagesEl">
          <!-- 欢迎页 -->
          <div v-if="messages.length === 0" class="welcome">
            <div class="welcome-icon">✦</div>
            <h2>你好，有什么可以帮你？</h2>
            <p>语音唤醒 · 天气查询 · 智能对话</p>
            <div class="quick-chips">
              <button v-for="q in quickQuestions" :key="q" class="chip" @click="sendMessage(q)">{{ q }}</button>
            </div>
          </div>

          <ChatBubble
            v-for="(msg, i) in messages"
            :key="i"
            :role="msg.role"
            :content="msg.content"
            :loading="msg.loading"
          />
        </div>

        <!-- 天气卡片（天气意图时插入） -->
        <Transition name="slide-up">
          <WeatherCard
            v-if="weatherData"
            :data="weatherData"
            class="weather-inline"
            @close="weatherData = null"
          />
        </Transition>

        <!-- 混合输入区 (Hybrid Input) -->
        <div class="input-area">
          <!-- 语音状态浮层：通话中时显示在输入框上方 -->
          <Transition name="fadeUp">
            <div class="call-overlay" v-if="inCall || micErrorMsg">
              <div v-if="micErrorMsg" class="mic-error-banner">
                <span>⚠️ {{ micErrorMsg }}</span>
                <button @click="micErrorMsg = ''">✕</button>
              </div>
              <template v-else>
                <div class="audio-visualizer-mini">
                <div class="bar" :style="{ transform: `scaleY(${visualizerVolume * 0.5 + 0.2})` }"></div>
                <div class="bar" :style="{ transform: `scaleY(${visualizerVolume * 0.8 + 0.3})` }"></div>
                <div class="bar" :style="{ transform: `scaleY(${visualizerVolume * 1.2 + 0.5})` }"></div>
                <div class="bar" :style="{ transform: `scaleY(${visualizerVolume * 0.9 + 0.4})` }"></div>
                <div class="bar" :style="{ transform: `scaleY(${visualizerVolume * 0.6 + 0.2})` }"></div>
              </div>
              <span class="call-hint">正在通话中...您可以说话或打字</span>
              <button class="btn-micro stop" @click="endVoiceCall" title="结束通话">挂断</button>
            </template>
          </div>
        </Transition>

          <div class="input-wrapper" :class="{focused: inputFocused}">
            <textarea
              v-model="inputText"
              ref="inputEl"
              placeholder='输入消息，或说"你好"唤醒…'
              rows="1"
              @focus="inputFocused = true"
              @blur="inputFocused = false"
              @keydown.enter.exact.prevent="sendMessage()"
              @input="autoResize"
            ></textarea>
            
            <div class="input-actions">
              <!-- 手动开启语音按钮 -->
              <button 
                v-if="!inCall" 
                class="btn-micro start" 
                :class="{ disabled: micDisabled }"
                :disabled="micDisabled"
                @click="startVoiceCall" 
                :title="micDisabled ? '麦克风不可用' : '开启语音'">
                🎤
              </button>
              
              <!-- 发送文本按钮 -->
              <button class="btn-send" :disabled="sending || !inputText.trim()" @click="sendMessage()">
                <span v-if="!sending">➤</span>
                <span v-else class="spin">◌</span>
              </button>
            </div>
          </div>
          <div class="input-hint">Enter 发送 · Shift+Enter 换行</div>
        </div>
      </section>
    </main>

    <!-- 设置弹窗 -->
    <Transition name="fade">
      <div v-if="showSettings" class="modal-overlay" @click.self="showSettings = false">
        <div class="modal">
          <h3>⚙️ 设置</h3>
          <div class="settings-grid">
            <label>DashScope API Key
              <input v-model="settings.dashscopeKey" type="password" placeholder="sk-..." />
            </label>
            <label>Picovoice AccessKey
              <input v-model="settings.picovoiceKey" type="password" placeholder="O8KPp..." />
            </label>
            
            <div class="field-row">
              <label>开始唤醒词 (.ppn)
                <div class="input-with-btn">
                  <input v-model="settings.keywordPathStart" type="text" />
                  <button @click.stop="pickFile('keywordPathStart', 'ppn')">📂</button>
                </div>
              </label>
            </div>

            <div class="field-row">
              <label>结束唤醒词 (.ppn)
                <div class="input-with-btn">
                  <input v-model="settings.keywordPathStop" type="text" placeholder="可选，留空则不启用" />
                  <button @click.stop="pickFile('keywordPathStop', 'ppn')">📂</button>
                </div>
              </label>
            </div>

            <div class="field-row">
              <label>全局模型文件 (.pv)
                <div class="input-with-btn">
                  <input v-model="settings.modelPath" type="text" />
                  <button @click.stop="pickFile('modelPath', 'pv')">📂</button>
                </div>
              </label>
            </div>

            <label>后端地址
              <input v-model="settings.backendUrl" type="text" />
            </label>
          </div>
          <div class="modal-actions">
            <button class="btn-cancel" @click="showSettings = false">取消</button>
            <button class="btn-save" @click="saveSettings">保存</button>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { ref, reactive, nextTick, onMounted } from 'vue'
import ChatBubble from './components/ChatBubble.vue'
import WeatherCard from './components/WeatherCard.vue'
import WakeWordIndicator from './components/WakeWordIndicator.vue'
import { open } from '@tauri-apps/plugin-dialog'

// ── Tauri API（懒加载，在浏览器中 fallback 为 null）
let tauriInvoke = null
import('@tauri-apps/api/core').then(mod => {
  tauriInvoke = mod.invoke
}).catch(() => {})

// ── 响应式状态
const messages = ref([])
const inputText = ref('')
const inputFocused = ref(false)
const sending = ref(false)
const messagesEl = ref(null)
const inputEl = ref(null)
const weatherData = ref(null)
const isFullscreen = ref(false)
const isOnTop = ref(false)
const showSettings = ref(false)
const inCall = ref(false) // Whether we are in live full-duplex mode
const visualizerVolume = ref(1.0)
const silenceTimer = ref(null) // 10秒静默挂断计时器
const micErrorMsg = ref('')    // 麦克风异常提示
const micDisabled = ref(false) // 麦克风不可用时置灰


// ── 默认路径（Windows，基于项目结构）
const defaultKwPath = String.raw`D:\Ming\voice_robot\porcupine\resources\keyword_files_zh\windows\你好_windows.ppn`
const defaultModelPath = String.raw`D:\Ming\voice_robot\porcupine\lib\common\porcupine_params_zh.pv`

const settings = reactive({
  dashscopeKey: localStorage.getItem('dashscopeKey') || '',
  picovoiceKey: localStorage.getItem('picovoiceKey') || 'O8KPpv2UQ9AP5nY7ACJ/ChQOQT8HfX+K80mECRx1SokHqSGwYB84Dg==',
  keywordPathStart: localStorage.getItem('keywordPathStart') || defaultKwPath,
  keywordPathStop: localStorage.getItem('keywordPathStop') || '',
  modelPath: localStorage.getItem('modelPath') || defaultModelPath,
  backendUrl: localStorage.getItem('backendUrl') || 'http://127.0.0.1:8765',
})

const quickQuestions = [
  '🌤 北京今天天气怎么样？',
  '🌧 上海未来7天天气',
  '🌡 深圳现在多少度？',
  '💬 帮我写一段自我介绍',
]

// ── 工具函数
function scrollToBottom() {
  nextTick(() => {
    if (messagesEl.value) {
      messagesEl.value.scrollTop = messagesEl.value.scrollHeight
    }
  })
}

function autoResize(e) {
  const el = e.target
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}

// ── 天气意图检测（覆盖口语化问法）
const weatherRegex = /天气|气温|温度|多少度|多少℃|几度|冷不冷|冷吗|冷么|热不热|热吗|热么|下雨|下雪|会下|带伞|预报|穿衣|穿什么|出行|降水|气候|刮风|风大|暖和|凉快|闷热|潮湿|现在.*度|今天.*热|今天.*冷|最近.*冷|最近.*热|明天.*冷|明天.*热/

async function fetchWeather(city) {
  try {
    const res = await fetch(`${settings.backendUrl}/weather?city=${encodeURIComponent(city)}`)
    if (res.ok) {
        const data = await res.json()
        weatherData.value = data
        return data
    }
  } catch (e) {
    console.warn('[weather]', e)
  }
  return null
}

// ── 城市提取（简单规则 初筛，覆盖口语化问法）
function extractCity(text) {
  // 先去除时间修饰词
  const cleaned = text.replace(/今天|明天|后天|这几天|未来|最近|现在/g, '')
  // 尝试匹配："城市+的?+天气关键词"
  const match = cleaned.match(/([^\s，,。！？]{2,6}?)[的]?(?:天气|气温|温度|多少度|多少℃|几度|冷不冷|冷吗|冷么|热不热|热吗|热么|下雨|下雪|会下|带伞|预报|穿衣|出行|降水|气候|刮风|风大|暖和|凉快|闷热|潮湿)/)
  if (match) {
      return match[1].trim()
  }
  return null
}

// ── 发送消息
async function sendMessage(text) {
  const content = (text || inputText.value).trim()
  if (!content) return

  inputText.value = ''
  nextTick(() => { if (inputEl.value) { inputEl.value.style.height = 'auto' } })

  messages.value.push({ role: 'user', content })
  scrollToBottom()

  let finalPrompt = content

  // 天气意图：尝试拦截并查询天气
  if (weatherRegex.test(content)) {
    let city = extractCity(content) || '北京' // 初筛兜底
    let wData = await fetchWeather(city)

    // 若第一次查询失败（如匹配到了"萧山"等区县，或者根本没查到），调用大模型进行名称上升映射
    if (!wData || !wData.raw_text) {
      try {
        const aiResp = await fetch(`${settings.backendUrl}/extract_city`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${settings.dashscopeKey}`
          },
          body: JSON.stringify({ message: content })
        })
        if (aiResp.ok) {
          const { city: smartCity } = await aiResp.json()
          if (smartCity) {
            city = smartCity
            wData = await fetchWeather(city) // 使用智能获取的标准地市名再次尝试
          }
        }
      } catch (e) {
        console.warn('智能地名转换失败', e)
      }
    }

    if (wData && wData.raw_text) {
        // 将天气原始数据隐藏注入到发给模型的最终 Prompt 中
        finalPrompt = `已知最新的【${city}】天气原始数据如下：\n\`\`\`\n${wData.raw_text}\n\`\`\`\n\n用户的问题是："${content}"\n\n请严格参考气象数据回答，务必包含具体的最高/最低气温、风力等核心数据。回答要简明扼要，直接切入正题，拒绝一切如“今天真是个好日子”之类的空泛废话和寒暄。结合数据简短提供：1.穿衣建议、2.出行建议、3.运动建议。不要完全输出死板表格。`
    }
  }

  // 添加 AI 占位
  const aiMsg = reactive({ role: 'assistant', content: '', loading: true })
  messages.value.push(aiMsg)
  scrollToBottom()
  sending.value = true

  try {
    const history = messages.value
      .slice(0, -2)
      .filter(m => !m.loading)
      .map(m => ({ role: m.role, content: m.content }))

    const resp = await fetch(`${settings.backendUrl}/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${settings.dashscopeKey}`
      },
      body: JSON.stringify({
        message: finalPrompt,
        history: history.slice(-10),
        system: "你是一个智能语音助手，请用简洁友好的中文回答问题。"
      }),
    })

    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    aiMsg.loading = false

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      const lines = decoder.decode(value).split('\n')
      for (const line of lines) {
        if (!line.startsWith('data:')) continue
        try {
          const obj = JSON.parse(line.slice(5))
          if (obj.type === 'delta') {
            aiMsg.content += obj.content
            scrollToBottom()
          } else if (obj.type === 'done') {
            break
          } else if (obj.type === 'error') {
            aiMsg.content += `[Backend Error] ${obj.message}`
            scrollToBottom()
            break
          }
        } catch {}
      }
    }
  } catch (e) {
    aiMsg.content = `⚠️ 请求失败：${e.message}，请确认后端已启动（${settings.backendUrl}）。`
    aiMsg.loading = false
  } finally {
    sending.value = false
  }
}

// ── 语音通话状态（WebSocket + Web Audio API 直连方案）
let voiceWs = null        // WebSocket 连接
let micStream = null      // 麦克风 MediaStream
let audioCtx = null       // 录音用 AudioContext
let micSource = null      // MediaStreamSourceNode
let micProcessor = null   // ScriptProcessorNode

let playCtx = null        // 播放用 AudioContext（24kHz）
let playQueue = []        // PCM16 帧队列
let isPlaying = false     // 是否正在播放
let pendingSilenceTimer = false  // 是否等待播放完后启动静默计时器

// 将 Float32 转为 PCM16 并加首字节前缀 0x00（协议标识 audio）
function float32ToPcm16WithPrefix(input) {
  const out = new Int16Array(input.length)
  for (let i = 0; i < input.length; i++) {
    let s = Math.max(-1, Math.min(1, input[i]))
    out[i] = s < 0 ? s * 0x8000 : s * 0x7FFF
  }
  const prefixed = new Uint8Array(1 + out.byteLength)
  prefixed[0] = 0x00  // stream_type = audio
  prefixed.set(new Uint8Array(out.buffer), 1)
  return prefixed
}

// 播放 PCM16 bytes（24kHz 单声道）
async function enqueueAudio(pcm16bytes) {
  if (!playCtx) {
    playCtx = new AudioContext({ sampleRate: 24000 })
  }
  playQueue.push(pcm16bytes)
  if (!isPlaying) {
    isPlaying = true
    while (playQueue.length > 0) {
      const chunk = playQueue.shift()
      const int16 = new Int16Array(chunk.buffer, chunk.byteOffset, chunk.byteLength / 2)
      const float32 = new Float32Array(int16.length)
      for (let i = 0; i < int16.length; i++) {
        float32[i] = int16[i] / 32768
      }
      const buffer = playCtx.createBuffer(1, float32.length, 24000)
      buffer.copyToChannel(float32, 0)
      const source = playCtx.createBufferSource()
      source.buffer = buffer
      source.connect(playCtx.destination)
      await new Promise(resolve => {
        source.onended = resolve
        source.start()
      })
    }
    isPlaying = false
    // 播放队列排空了，如果有等待的静默计时器，现在启动
    if (pendingSilenceTimer) {
      pendingSilenceTimer = false
      startSilenceTimer()
    }
  }
}

function stopAudioPlayback() {
  playQueue = []
  isPlaying = false
  if (playCtx) {
    playCtx.close().catch(() => {})
    playCtx = null
  }
}

// ── 语音通话控制
function startSilenceTimer() {
  stopSilenceTimer()
  silenceTimer.value = setTimeout(() => {
    console.log('[SilenceDetector] 10秒无语音输入，准备挂断')
    // 先显示提示消息
    messages.value.push({ role: 'assistant', content: '如果没有其他问题，我先退下了。', isFinal: true })
    scrollToBottom()
    // 延迟2秒后挂断，给用户反应时间
    silenceTimer.value = setTimeout(() => {
      endVoiceCall()
    }, 2000)
  }, 10000)
}

function stopSilenceTimer() {
  if (silenceTimer.value) {
    clearTimeout(silenceTimer.value)
    silenceTimer.value = null
  }
}

async function startVoiceCall() {
  inCall.value = true
  try {
    // 获取麦克风
    micStream = await navigator.mediaDevices.getUserMedia({ audio: {
      sampleRate: 16000,
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true
    }})

    // 建立 WebSocket 连接
    const wsUrl = settings.backendUrl
      .replace(/^https?:\/\//, (m) => m === 'http://' ? 'ws://' : 'wss://')
      + `/voice_ws?voice=Cherry&token=${encodeURIComponent(settings.dashscopeKey)}`
    voiceWs = new WebSocket(wsUrl)
    voiceWs.binaryType = 'arraybuffer'

    voiceWs.onopen = () => {
      console.log('[voice_ws] 已连接')
      // 开始录音推流
      audioCtx = new AudioContext({ sampleRate: 16000 })
      micSource = audioCtx.createMediaStreamSource(micStream)
      micProcessor = audioCtx.createScriptProcessor(4096, 1, 1)
      micProcessor.onaudioprocess = (e) => {
        if (voiceWs && voiceWs.readyState === WebSocket.OPEN) {
          const inputData = e.inputBuffer.getChannelData(0)
          voiceWs.send(float32ToPcm16WithPrefix(inputData))
        }
        // 更新音量可视化
        const buf = e.inputBuffer.getChannelData(0)
        const rms = Math.sqrt(buf.reduce((s, v) => s + v * v, 0) / buf.length)
        visualizerVolume.value = 1.0 + rms * 20
      }
      micSource.connect(micProcessor)
      micProcessor.connect(audioCtx.destination)
      
      // 连接建立时启动静默计时器
      startSilenceTimer()
    }

    voiceWs.onerror = (e) => {
      console.error('[voice_ws] 连接错误', e)
      inCall.value = false
    }

    voiceWs.onclose = () => {
      console.log('[voice_ws] 已断开')
      inCall.value = false
    }

    voiceWs.onmessage = async (event) => {
      if (event.data instanceof ArrayBuffer) {
        // 二进制 = AI 语音 PCM16 音频
        await enqueueAudio(new Uint8Array(event.data))
        visualizerVolume.value = 1.5
      } else {
        // 文本 JSON 消息
        try {
          const msg = JSON.parse(event.data)
          if (msg.type === 'interrupt') {
            stopAudioPlayback()
          } else if (msg.type === 'input_transcript') {
            // 用户说话的转录（最终结果）
            const now = Date.now()
            
            // 用户说话了，停止当前的静默计时器（防止在用户说话期间挂断）
            stopSilenceTimer()
            // 往回找最近的由 voice_ws 发出的用户消息
            let lastUserMsg = null
            for (let i = messages.value.length - 1; i >= 0; i--) {
              if (messages.value[i].role === 'user' && messages.value[i].isVoiceWs) {
                lastUserMsg = messages.value[i]
                break
              }
            }
            
            // 如果找到了，且时间在3秒以内，作为同一个气泡更新（防止口吃重复显示）
            if (lastUserMsg && (now - lastUserMsg.timestamp < 3000)) {
              if (lastUserMsg.content !== msg.data) {
                lastUserMsg.content = msg.data
                lastUserMsg.timestamp = now // 刷新时间
              }
            } else {
              messages.value.push({ 
                id: 'in-' + now, 
                role: 'user', 
                content: msg.data, 
                isFinal: true,
                isVoiceWs: true,
                timestamp: now 
              })
            }
            scrollToBottom()
          } else if (msg.type === 'output_transcript') {
            // AI 回复的完整文本
            messages.value.push({ id: 'out-' + Date.now(), role: 'assistant', content: msg.data, isFinal: true })
            scrollToBottom()
            // AI 文字回复完成，如果语音还在播放，等播放完再启动计时器
            if (isPlaying) {
              pendingSilenceTimer = true
            } else {
              startSilenceTimer()
            }
          } else if (msg.type === 'weather_data') {
            weatherData.value = msg.data
            // 标记为 isWeather 以便后续总结替换内容
            messages.value.push({ 
              id: 'tool-' + Date.now(), 
              role: 'assistant', 
              content: `【正在总结】正在为您整理 ${msg.city} 的天气预报...`, 
              isFinal: true,
              isWeather: true 
            })
            scrollToBottom()
            } else if (msg.type === 'weather_summary') {
              // 收到总结后，替换掉之前的“正在总结”提示
              const lastWeatherMsg = [...messages.value].reverse().find(m => m.isWeather)
              if (lastWeatherMsg) {
                lastWeatherMsg.content = msg.data
                scrollToBottom()
              }
            } else if (msg.type === 'hangup') {
              // 收到挂断信号，延迟一点点让语音播完（如果有的话）
              console.log('[voice_ws] Received hangup signal')
              setTimeout(() => {
                endVoiceCall()
              }, 1500)
            }
        } catch (e) {
          console.warn('[voice_ws] 文本消息解析失败', e)
        }
      }
    }

  } catch(e) {
    console.error('语音通话启动失败:', e)
    inCall.value = false
  }
}

async function endVoiceCall() {
  inCall.value = false
  visualizerVolume.value = 1.0

  // 停止录音
  if (micProcessor) { micProcessor.disconnect(); micProcessor = null }
  if (micSource) { micSource.disconnect(); micSource = null }
  if (audioCtx) { audioCtx.close().catch(() => {}); audioCtx = null }
  if (micStream) { micStream.getTracks().forEach(t => t.stop()); micStream = null }

  // 停止播放
  stopAudioPlayback()

  // 关闭 WebSocket
  if (voiceWs) {
    voiceWs.onclose = null  // 防止触发 inCall = false 再次
    voiceWs.close()
    voiceWs = null
  }
  
  // 停止静默计时器
  stopSilenceTimer()
}

// ── 唤醒词触发
function onWakeDetected(index) {
  console.log('[App] 唤醒词触发，索引：', index)
  
  // 约定：索引 0 为启动，索引 1 为结束
  if (index === 0) {
    if (!inCall.value) {
      startVoiceCall()
      if (messages.value.length === 0) {
        messages.value.push({ role: 'assistant', content: '我在，请吩咐。', isFinal: true })
        scrollToBottom()
      }
    }
  } else if (index === 1) {
    if (inCall.value) {
      endVoiceCall()
      messages.value.push({ role: 'assistant', content: '好的，先退下了。', isFinal: true })
      scrollToBottom()
    }
  }

  nextTick(() => inputEl.value?.focus())
}

// ── 麦克风异常处理
function onMicError(errMsg) {
  console.error('[App] 麦克风异常:', errMsg)
  micDisabled.value = true
  // 如果正在通话，自动挂断
  if (inCall.value) {
    endVoiceCall()
    messages.value.push({ role: 'assistant', content: '麦克风异常，通话已自动挂断。', isFinal: true })
    scrollToBottom()
  }
}

// ── 麦克风恢复处理
function onMicRecovered() {
  console.log('[App] 麦克风已恢复')
  micDisabled.value = false
}

import { listen } from '@tauri-apps/api/event'
onMounted(async () => {
  if (window.__TAURI__) {
    await listen('livekit-text', (event) => {
      let payload = event.payload;
      if (typeof payload === 'string') {
        payload = { text: payload, is_final: true, role: 'assistant' };
      }
      const text = payload.text;
      const role = payload.role || 'assistant';
      const isFinal = payload.is_final !== undefined ? payload.is_final : true;

      if (!text) return;

      const lastMsg = messages.value[messages.value.length - 1];
      
      // If we don't have a matching un-finalized message, push a new one
      if (!lastMsg || lastMsg.role !== role || lastMsg.isFinal) {
        messages.value.push({ 
          role: role, 
          content: isFinal ? text : `<span class="partial-text">${text} (正在识别中...)</span>`, 
          rawContent: text,
          isFinal: isFinal, 
          loading: false 
        });
      } else {
        // Update existing partial message
        lastMsg.rawContent = text;
        lastMsg.isFinal = isFinal;
        lastMsg.content = isFinal ? text : `<span class="partial-text">${text} (正在识别中...)</span>`;
      }
      scrollToBottom()
    })
    await listen('livekit-volume', (event) => {
      visualizerVolume.value = event.payload?.volume || 1.0
    })
    await listen('microphone-error', (event) => {
      console.log('[App] Microphone error event received:', event)
      const msg = typeof event.payload === 'string' ? event.payload : (event.payload?.message || '麦克风异常');
      micErrorMsg.value = msg
      setTimeout(() => { micErrorMsg.value = '' }, 8000)
      if (inCall.value) endVoiceCall()
    })
  }
})

// ── Tauri 窗口控制
async function toggleFullscreen() {
  isFullscreen.value = !isFullscreen.value
  if (tauriInvoke) await tauriInvoke('set_fullscreen', { fullscreen: isFullscreen.value })
}
async function toggleOnTop() {
  isOnTop.value = !isOnTop.value
  if (tauriInvoke) await tauriInvoke('set_always_on_top', { onTop: isOnTop.value })
}

// ── 文件选择
async function pickFile(key, extension) {
  try {
    const selected = await open({
      multiple: false,
      filters: [{ name: 'Porcupine File', extensions: [extension] }]
    })
    if (selected) {
      settings[key] = selected
    }
  } catch (e) {
    console.error('File picker error:', e)
  }
}

function clearChat() {
  messages.value = []
  weatherData.value = null
}

function saveSettings() {
  Object.keys(settings).forEach(k => localStorage.setItem(k, settings[k]))
  showSettings.value = false
}
</script>

<style scoped>
/* ── 根布局 */
.app-root {
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

/* ── 动态背景 */
.bg-mesh { position: fixed; inset: 0; pointer-events: none; z-index: 0; overflow: hidden; }
.orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
}
.orb-1 {
  width: 500px; height: 500px;
  top: -150px; right: -100px;
  background: radial-gradient(circle, rgba(99,179,237,0.09) 0%, transparent 70%);
  animation: float 20s ease-in-out infinite alternate;
}
.orb-2 {
  width: 400px; height: 400px;
  bottom: -100px; left: -80px;
  background: radial-gradient(circle, rgba(167,139,250,0.07) 0%, transparent 70%);
  animation: float 26s ease-in-out infinite alternate-reverse;
}
@keyframes float {
  0% { transform: translate(0,0) scale(1); }
  100% { transform: translate(30px,-40px) scale(1.08); }
}

/* ── 工具栏 */
.toolbar {
  position: relative; z-index: 10;
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 20px;
  background: rgba(8,12,20,0.8);
  backdrop-filter: blur(20px) saturate(1.4);
  border-bottom: 1px solid var(--border-subtle);
  flex-shrink: 0;
}
.toolbar-brand { display: flex; align-items: center; gap: 10px; }
.brand-logo {
  width: 34px; height: 34px;
  background: var(--accent-gradient);
  border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  font-size: 16px; color: #080c14; font-weight: 700;
}
.brand-name {
  font-family: var(--font-display);
  font-size: 1rem; font-weight: 600;
  background: var(--accent-gradient);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}
.toolbar-actions { display: flex; align-items: center; gap: 8px; }
.icon-btn {
  width: 34px; height: 34px;
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  font-size: 0.85rem;
  transition: all var(--transition-fast);
}
.icon-btn:hover { background: rgba(255,255,255,0.08); color: var(--text-primary); }
.icon-btn.active { border-color: var(--accent-blue); color: var(--accent-blue); background: rgba(99,179,237,0.1); }
.btn-clear {
  padding: 6px 12px;
  background: var(--bg-input); border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm); color: var(--text-muted); cursor: pointer;
  font-size: 0.82rem;
  transition: all var(--transition-fast);
}
.btn-clear:hover { color: var(--text-primary); background: rgba(255,255,255,0.08); }

/* ── 主区域 */
.main-area {
  position: relative; z-index: 1;
  flex: 1; display: flex; overflow: hidden;
}
.chat-section {
  flex: 1; display: flex; flex-direction: column; overflow: hidden;
}
.messages {
  flex: 1; overflow-y: auto;
  padding: 20px 16px;
  display: flex; flex-direction: column; gap: 16px;
  scroll-behavior: smooth;
}

/* ── 欢迎页 */
.welcome {
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; height: 100%; text-align: center; padding: 40px;
  animation: fadeUp 0.5s ease-out;
}
.welcome-icon {
  width: 72px; height: 72px;
  background: var(--accent-gradient);
  border-radius: 22px;
  display: flex; align-items: center; justify-content: center;
  font-size: 30px; margin-bottom: 20px;
  box-shadow: 0 4px 24px rgba(99,179,237,0.2);
}
.welcome h2 {
  font-family: var(--font-display); font-size: 1.4rem; margin-bottom: 8px;
  background: var(--accent-gradient);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}
.welcome p { color: var(--text-muted); font-size: 0.88rem; margin-bottom: 24px; }
.quick-chips { display: flex; flex-wrap: wrap; gap: 10px; justify-content: center; }
.chip {
  padding: 8px 16px;
  background: var(--bg-input); border: 1px solid var(--border-subtle);
  border-radius: 20px; color: var(--text-secondary); cursor: pointer;
  font-size: 0.82rem; font-family: var(--font-sans);
  transition: all var(--transition-fast);
}
.chip:hover {
  background: rgba(99,179,237,0.08);
  border-color: var(--border-glow); color: var(--accent-blue);
  transform: translateY(-1px);
}

/* ── 天气卡片过渡 */
.weather-inline { margin: 0 16px 8px; }
.slide-up-enter-active, .slide-up-leave-active {
  transition: all 0.35s cubic-bezier(0.4,0,0.2,1);
}
.slide-up-enter-from { opacity: 0; transform: translateY(20px); }
.slide-up-leave-to { opacity: 0; transform: translateY(20px); }

/* ── 输入区 */
.input-area {
  padding: 12px 16px 16px;
  background: rgba(8,12,20,0.8);
  backdrop-filter: blur(20px);
  border-top: 1px solid var(--border-subtle);
  flex-shrink: 0;
}
.input-wrapper {
  display: flex; align-items: flex-end; gap: 8px;
  background: var(--bg-input); border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  padding: 6px 6px 6px 16px;
  transition: border-color var(--transition-smooth), box-shadow var(--transition-smooth);
}
.input-wrapper.focused {
  border-color: rgba(99,179,237,0.3);
  box-shadow: 0 0 0 3px rgba(99,179,237,0.06);
}
textarea {
  flex: 1; background: none; border: none; outline: none;
  color: var(--text-primary); font-family: var(--font-sans);
  font-size: 0.9rem; resize: none;
  min-height: 24px; max-height: 160px;
  padding: 6px 0; line-height: 1.55;
}
textarea::placeholder { color: var(--text-muted); }
.btn-send {
  width: 40px; height: 40px; border-radius: 12px; border: none;
  background: var(--accent-gradient); color: #080c14;
  font-size: 16px; cursor: pointer; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  transition: all var(--transition-fast);
  box-shadow: 0 2px 10px rgba(99,179,237,0.2);
}
.btn-send:hover { transform: scale(1.05); }
.btn-send:active { transform: scale(0.95); }
.btn-send:disabled { opacity: 0.35; cursor: not-allowed; transform: none; }
.spin { display: inline-block; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.input-hint { font-size: 0.68rem; color: var(--text-muted); padding: 4px 8px 0; }

.input-actions {
  display: flex; gap: 8px; flex-shrink: 0; align-items: center;
}
.btn-micro {
  width: 40px; height: 40px; border-radius: 12px; border: none;
  font-size: 16px; cursor: pointer; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  transition: all var(--transition-fast);
}
.btn-micro.start {
  background: rgba(99,179,237,0.1); color: var(--accent-blue);
  border: 1px solid rgba(99,179,237,0.3);
}
.btn-micro.start:hover { background: rgba(99,179,237,0.2); }
.btn-micro.stop {
  background: rgba(255, 77, 79, 0.1); border: 1px solid rgba(255, 77, 79, 0.4);
  color: #ff4d4f; padding: 6px 16px; height: 32px; border-radius: 16px; width: auto; font-size: 0.8rem;
}
.btn-micro.stop:hover { background: rgba(255, 77, 79, 0.2); }

.call-overlay {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 12px; padding: 10px 16px;
  background: linear-gradient(90deg, rgba(8,12,20,0) 0%, rgba(99,179,237,0.08) 50%, rgba(8,12,20,0) 100%);
  border-radius: var(--radius-md);
  border-top: 1px solid rgba(99,179,237,0.1);
  border-bottom: 1px solid rgba(99,179,237,0.1);
}
.audio-visualizer-mini {
  display: flex; gap: 4px; align-items: center; height: 24px; width: 40px; justify-content: center;
}
.call-hint {
  font-size: 0.82rem; color: var(--accent-blue); animation: pulseText 2s infinite; flex: 1; text-align: center;
}
@keyframes pulseText { 0%, 100% { opacity: 0.8; } 50% { opacity: 0.4; } }


/* ── 模态弹窗 */
.modal-overlay {
  position: fixed; inset: 0; z-index: 100;
  background: rgba(0,0,0,0.6); backdrop-filter: blur(8px);
  display: flex; align-items: center; justify-content: center;
}
.modal {
  background: var(--bg-secondary);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-xl);
  padding: 28px; width: 90%; max-width: 420px;
  box-shadow: var(--shadow-deep);
  display: flex; flex-direction: column; gap: 14px;
}
.modal h3 { font-family: var(--font-display); font-size: 1.1rem; }
.modal label {
  display: flex; flex-direction: column; gap: 6px;
  font-size: 0.82rem; color: var(--text-secondary);
}
.modal input {
  background: var(--bg-input); border: 1px solid var(--border-subtle);
  color: var(--text-primary); padding: 9px 12px;
  border-radius: var(--radius-sm); font-family: var(--font-sans); font-size: 0.88rem;
  outline: none;
}
.modal input:focus { border-color: rgba(99,179,237,0.35); }
.modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 4px; }
.btn-cancel {
  padding: 8px 16px; background: var(--bg-input);
  border: 1px solid var(--border-subtle); border-radius: var(--radius-sm);
  color: var(--text-secondary); cursor: pointer;
}
.btn-save {
  padding: 8px 18px;
  background: var(--accent-gradient); border: none;
  border-radius: var(--radius-sm); color: #080c14; font-weight: 600; cursor: pointer;
}

/* ── 过渡 */
.fade-enter-active, .fade-leave-active { transition: opacity 0.25s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

@keyframes fadeUp {
  from { opacity: 0; transform: translateY(16px); }
  to   { opacity: 1; transform: translateY(0); }
}

:deep(.partial-text) {
  color: #888;
  font-style: italic;
  transition: color 0.3s;
}
/* ── 设置弹窗样式升级 */
.settings-grid {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 10px;
}
.field-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.input-with-btn {
  display: flex;
  gap: 8px;
}
.input-with-btn input {
  flex: 1;
}
.input-with-btn button {
  padding: 0 10px;
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  cursor: pointer;
  transition: all 0.2s;
}
.input-with-btn button:hover {
  background: rgba(255,255,255,0.1);
  border-color: var(--accent-blue);
}
.mic-error-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.5);
  padding: 8px 16px;
  border-radius: var(--radius-sm);
  color: #f87171;
  font-size: 0.85rem;
  backdrop-filter: blur(10px);
}
.mic-error-banner button {
  background: none;
  border: none;
  color: #f87171;
  cursor: pointer;
  font-size: 1.1rem;
  padding: 0 4px;
}
.btn-micro.start.disabled {
  opacity: 0.35;
  cursor: not-allowed;
  pointer-events: none;
}
</style>
