<template>
  <div class="wake-wrap" :class="[displayState, { 'in-call': inCall }]">
    <!-- 声波弧线组（左） -->
    <div class="sound-wave sound-wave-left" :class="[displayState]" v-if="inCall && (displayState === 'listening' || displayState === 'speaking')">
      <span class="arc arc-1"></span>
      <span class="arc arc-2"></span>
    </div>

    <!-- 胶囊按钮 -->
    <button
      class="wake-btn-premium"
      :class="[
        displayState,
        { 
          active: isListening || inCall, 
          detected: justDetected, 
          'mic-error': micError, 
          'in-call': inCall 
        }
      ]"
      @click="micError ? clearMicError() : toggleWake()"
      :title="micError ? '麦克风异常，点击重新连接' : inCall ? '点击挂断通话' : isListening ? '点击停止唤醒监听' : '点击启动唤醒词监听'"
    >
      <!-- 胶囊发光麦克风圆圈 -->
      <div class="mic-circle">
        <span class="mic-icon-svg">
          <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z" fill="currentColor"/>
            <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z" fill="currentColor"/>
          </svg>
        </span>
      </div>
      
      <!-- 双行文本区 -->
      <div class="label-group">
        <span class="label-main">{{ mainLabel }}</span>
        <span class="label-sub">{{ subLabel }}</span>
      </div>
    </button>

    <!-- 声波弧线组（右） -->
    <div class="sound-wave sound-wave-right" :class="[displayState]" v-if="inCall && (displayState === 'listening' || displayState === 'speaking')">
      <span class="arc arc-2"></span>
      <span class="arc arc-1"></span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onUnmounted, onMounted } from 'vue'
import { invoke as tauriInvoke } from '@tauri-apps/api/core'
import { listen as tauriListen } from '@tauri-apps/api/event'

const props = defineProps({
  keyword: { type: String, default: '小安小安' },
  modelPath: { type: String, default: '' },
  inCall: { type: Boolean, default: false },
  isPlaying: { type: Boolean, default: false },
  isThinking: { type: Boolean, default: false },
  isUserSpeaking: { type: Boolean, default: false },
  kwsMaxActivePaths: { type: Number, default: 4 },
  kwsNumTrailingBlanks: { type: Number, default: 1 },
  kwsScore: { type: Number, default: 1.5 },
  kwsThreshold: { type: Number, default: 0.25 }
})

const displayState = computed(() => {
  if (micError.value) return 'error'
  if (justDetected.value) return 'detected'
  if (!props.inCall) return 'sleeping'
  if (props.isPlaying) return 'speaking'
  if (props.isThinking) return 'thinking'
  if (props.isUserSpeaking) return 'listening'
  return 'awakened'
})

const mainLabel = computed(() => {
  switch (displayState.value) {
    case 'error': return '麦克风异常'
    case 'detected': return '已唤醒'
    case 'sleeping': return '休眠中'
    case 'awakened': return '已唤醒'
    case 'thinking': return '思考中...'
    case 'speaking': return '回答中...'
    case 'listening': return '聆听中...'
    default: return '已唤醒'
  }
})

const subLabel = computed(() => {
  switch (displayState.value) {
    case 'error': return 'Error'
    case 'detected': return 'Wake up!'
    case 'sleeping': return 'Standby'
    case 'awakened': return 'Awakened'
    case 'thinking': return 'Thinking...'
    case 'speaking': return 'Responding...'
    case 'listening': return 'Listening...'
    default: return 'Awakened'
  }
})

const emit = defineEmits(['wake', 'mic-error', 'mic-recovered', 'debug', 'stop-call'])

const isListening = ref(false)
const justDetected = ref(false)
const micError = ref(false)
let unlistenFn = null
let unlistenMicError = null
let unlistenMicRecovered = null
let detectedTimer = null

// 动态求值以兼容 Tauri v2 的异步注入
function checkHasTauri() {
  return typeof window !== 'undefined' && (!!window.__TAURI__ || !!window.__tauri_ipc__);
}

let isStarting = false

async function startListening() {
  if (isListening.value || isStarting) return;
  isStarting = true;
  
  const isTauriEnv = checkHasTauri();
  emit('debug', `[KWS] 准备启动监听，modelPath=${props.modelPath}，isTauriEnv=${isTauriEnv}`)
  
  if (!isTauriEnv) {
    emit('debug', '[KWS] 启动被忽略：未检测到 Tauri 宿主环境（可能在纯浏览器中运行）。')
    isStarting = false;
    return;
  }
  try {
    if (typeof window !== 'undefined' && window.__kws_unlisten_fn__) {
      try { window.__kws_unlisten_fn__() } catch (e) {}
      window.__kws_unlisten_fn__ = null
    }
    if (unlistenFn) {
      try { unlistenFn() } catch (e) {}
      unlistenFn = null
    }
    const currentUnlisten = await tauriListen('wake-word-detected', (event) => {
      if (props.inCall) {
        emit('debug', `[Interrupt] 收到底层打断事件：payload=${event.payload}`)
      } else {
        emit('debug', `[KWS] 收到底层唤醒事件：payload=${event.payload}`)
      }
      justDetected.value = true
      emit('wake', event.payload)
      clearTimeout(detectedTimer)
      detectedTimer = setTimeout(() => { justDetected.value = false }, 2500)
    })

    // 监听后台异步加载状态
    tauriListen('kws-status', (event) => {
      emit('debug', `[KWS 引擎状态更新] ${event.payload}`)
    })

    if (typeof window !== 'undefined') {
      window.__kws_unlisten_fn__ = currentUnlisten
    }
    unlistenFn = currentUnlisten

    emit('debug', '[KWS] 正在调用 Rust start_wake_word...')
    await tauriInvoke('start_wake_word', {
      modelDir: props.modelPath,
      keyword: props.keyword,
      maxActivePaths: props.kwsMaxActivePaths,
      numTrailingBlanks: props.kwsNumTrailingBlanks,
      keywordsScore: props.kwsScore,
      keywordsThreshold: props.kwsThreshold,
    })
    emit('debug', `[KWS] Rust start_wake_word 已成功提交后台异步加载！max_active_paths=${props.kwsMaxActivePaths}, score=${props.kwsScore}, threshold=${props.kwsThreshold}`)
    isListening.value = true
  } catch (e) {
    emit('debug', `[KWS] 启动失败！Rust 抛出异常：${e}`)
    if (unlistenFn) { unlistenFn(); unlistenFn = null }
  } finally {
    isStarting = false;
  }
}

async function stopListening() {
  if (!isListening.value) return
  emit('debug', '[KWS] 停止监听')
  if (checkHasTauri()) {
    try { 
      await tauriInvoke('stop_wake_word')
      emit('debug', '[KWS] Rust stop_wake_word 调用成功')
    } catch (e) { 
      emit('debug', `[KWS] Rust stop_wake_word 失败：${e}`) 
    }
  }
  if (unlistenFn) { unlistenFn(); unlistenFn = null }
  isListening.value = false
}

async function toggleWake() {
  if (props.inCall) {
    emit('stop-call')
    return
  }
  if (isListening.value) {
    await stopListening()
  } else {
    await startListening()
  }
}

defineExpose({ startListening, stopListening })

onMounted(async () => {
  emit('debug', '[KWS] 组件挂载，等待 1000ms 以确保 Tauri 运行环境注入完成...')
  
  setTimeout(async () => {
    const isTauriEnv = checkHasTauri();
    emit('debug', `[KWS] 延时检测宿主环境：isTauriEnv=${isTauriEnv}`)

    if (isTauriEnv) {
      try {
        unlistenMicError = await tauriListen('microphone-error', (event) => {
          emit('debug', `[KWS] 收到底层麦克风异常事件：${JSON.stringify(event.payload)}`)
          micError.value = true
          isListening.value = false
          emit('mic-error', event.payload)
        })
        unlistenMicRecovered = await tauriListen('microphone-recovered', (event) => {
          emit('debug', `[KWS] 收到底层麦克风已恢复事件：${JSON.stringify(event.payload)}`)
          micError.value = false
          isListening.value = true
          emit('mic-recovered')
        })
        emit('debug', '[KWS] 成功挂载底层麦克风事件监听监听器')
      } catch (e) {
        emit('debug', `[KWS] 挂载底层麦克风监听器失败：${e}`)
      }
    }

    if (!isListening.value) {
      await startListening()
    }
  }, 1000)
})

function clearMicError() {
  emit('debug', '[KWS] 尝试手动清理麦克风异常并重连')
  micError.value = false
  toggleWake()
}

onUnmounted(() => {
  if (unlistenFn) unlistenFn()
  if (unlistenMicError) unlistenMicError()
  if (unlistenMicRecovered) unlistenMicRecovered()
  clearTimeout(detectedTimer)
})
</script>

<style scoped>
.wake-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
}

/* ── 胶囊按钮基础样式 ── */
.wake-btn-premium {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 20px 6px 8px;
  border-radius: 28px;
  background: rgba(15, 23, 42, 0.45);
  border: 1.5px solid rgba(255, 255, 255, 0.08);
  color: var(--text-primary);
  cursor: pointer;
  outline: none;
  backdrop-filter: blur(20px);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25);
  user-select: none;
}

.wake-btn-premium:hover {
  background: rgba(15, 23, 42, 0.6);
  border-color: rgba(255, 255, 255, 0.15);
  transform: translateY(-1px);
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.35);
}

/* ── 麦克风图标圆形包装 ── */
.mic-circle {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.1) 0%, rgba(255, 255, 255, 0.02) 100%);
  border: 1px solid rgba(255, 255, 255, 0.15);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.mic-icon-svg {
  width: 16px;
  height: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.wake-btn-premium:hover .mic-circle {
  border-color: rgba(255, 255, 255, 0.3);
  color: #fff;
}

/* ── 双行文字排版 ── */
.label-group {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  text-align: left;
}

.label-main {
  font-family: var(--font-sans);
  font-size: 0.85rem;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.2;
  transition: all 0.3s;
}

.label-sub {
  font-family: var(--font-display);
  font-size: 0.62rem;
  font-weight: 500;
  color: var(--text-muted);
  line-height: 1.1;
  margin-top: 2px;
  letter-spacing: 0.5px;
  transition: all 0.3s;
}

/* ── 状态高亮：已开启监听（聆听中） ── */
.wake-btn-premium.active {
  background: rgba(167, 139, 250, 0.1);
  border-color: rgba(167, 139, 250, 0.4);
  box-shadow: 0 0 16px rgba(167, 139, 250, 0.15), 0 4px 20px rgba(0,0,0,0.25);
}

.wake-btn-premium.active .mic-circle {
  background: linear-gradient(135deg, rgba(167, 139, 250, 0.2) 0%, rgba(167, 139, 250, 0.05) 100%);
  border-color: rgba(167, 139, 250, 0.5);
  color: var(--accent-purple);
  box-shadow: 0 0 10px rgba(167, 139, 250, 0.2);
}

.wake-btn-premium.active .label-main {
  color: var(--accent-purple);
}

.wake-btn-premium.active .label-sub {
  color: rgba(167, 139, 250, 0.8);
}

/* ── 状态高亮：已唤醒瞬间 ── */
.wake-btn-premium.detected {
  background: rgba(99, 179, 237, 0.15);
  border-color: rgba(99, 179, 237, 0.6);
  box-shadow: 0 0 20px rgba(99, 179, 237, 0.35);
}

.wake-btn-premium.detected .mic-circle {
  background: linear-gradient(135deg, #3b82f6 0%, #63b3ed 100%);
  border-color: rgba(99, 179, 237, 0.8);
  color: #fff;
  box-shadow: 0 0 12px rgba(99, 179, 237, 0.4);
}

.wake-btn-premium.detected .label-main {
  color: var(--accent-blue);
  text-shadow: 0 0 8px rgba(99, 179, 237, 0.4);
}

/* ── 状态高亮：对话中通话中（完全对齐设计图） ── */
.wake-btn-premium.in-call {
  background: rgba(8, 20, 36, 0.6);
  border-color: rgba(99, 179, 237, 0.85);
  box-shadow: 
    0 0 25px rgba(99, 179, 237, 0.45), 
    inset 0 0 10px rgba(99, 179, 237, 0.2), 
    0 4px 20px rgba(0, 0, 0, 0.3);
}

.wake-btn-premium.in-call:hover {
  background: rgba(8, 20, 36, 0.75);
  border-color: rgba(99, 179, 237, 1);
  box-shadow: 
    0 0 30px rgba(99, 179, 237, 0.6), 
    inset 0 0 12px rgba(99, 179, 237, 0.3), 
    0 6px 24px rgba(0, 0, 0, 0.4);
}

.wake-btn-premium.in-call .mic-circle {
  background: linear-gradient(135deg, #1d4ed8 0%, #0284c7 100%);
  border-color: rgba(99, 179, 237, 0.9);
  color: #fff;
  box-shadow: 0 0 14px rgba(99, 179, 237, 0.65);
  animation: pulse-mic 2s infinite alternate;
}

.wake-btn-premium.in-call .label-main {
  color: #fff;
  text-shadow: 0 0 8px rgba(99, 179, 237, 0.6);
}

.wake-btn-premium.in-call .label-sub {
  color: rgba(99, 179, 237, 0.85);
  text-shadow: 0 0 4px rgba(99, 179, 237, 0.3);
}

@keyframes pulse-mic {
  0% { transform: scale(1); box-shadow: 0 0 10px rgba(99, 179, 237, 0.5); }
  100% { transform: scale(1.05); box-shadow: 0 0 16px rgba(99, 179, 237, 0.8); }
}

/* ── 麦克风异常状态 ── */
.wake-btn-premium.mic-error {
  background: rgba(239, 68, 68, 0.15);
  border-color: rgba(239, 68, 68, 0.5);
  box-shadow: 0 0 16px rgba(239, 68, 68, 0.25);
}

.wake-btn-premium.mic-error .mic-circle {
  background: rgba(239, 68, 68, 0.2);
  border-color: rgba(239, 68, 68, 0.6);
  color: #f87171;
}

.wake-btn-premium.mic-error .label-main {
  color: #f87171;
}

.wake-btn-premium.mic-error .label-sub {
  color: rgba(239, 68, 68, 0.8);
}

/* ── 声波弧线（左右两侧） ── */
.sound-wave {
  display: flex;
  gap: 6px;
  align-items: center;
  pointer-events: none;
  animation: fade-in 0.3s ease-out;
}

.sound-wave-left {
  margin-right: 14px;
}

.sound-wave-right {
  margin-left: 14px;
  flex-direction: row-reverse;
}

.arc {
  width: 3px;
  height: 28px;
  background: transparent;
  border-radius: 4px;
}

/* 弧线样式（左） */
.sound-wave-left .arc-1 {
  border-left: 2px solid rgba(99, 179, 237, 0.9);
  filter: drop-shadow(0 0 6px rgba(99, 179, 237, 0.8));
  height: 28px;
  animation: pulse-wave-outer 1.1s infinite ease-in-out;
}

.sound-wave-left .arc-2 {
  border-left: 2px solid rgba(99, 179, 237, 0.65);
  filter: drop-shadow(0 0 4px rgba(99, 179, 237, 0.5));
  height: 20px;
  animation: pulse-wave-inner 1.1s infinite ease-in-out 0.22s;
}

/* 弧线样式（右） */
.sound-wave-right .arc-1 {
  border-right: 2px solid rgba(99, 179, 237, 0.9);
  filter: drop-shadow(0 0 6px rgba(99, 179, 237, 0.8));
  height: 28px;
  animation: pulse-wave-outer 1.1s infinite ease-in-out;
}

.sound-wave-right .arc-2 {
  border-right: 2px solid rgba(99, 179, 237, 0.65);
  filter: drop-shadow(0 0 4px rgba(99, 179, 237, 0.5));
  height: 20px;
  animation: pulse-wave-inner 1.1s infinite ease-in-out 0.22s;
}

@keyframes pulse-wave-outer {
  0%, 100% { transform: scaleY(0.8); opacity: 0.45; }
  50% { transform: scaleY(1.2); opacity: 1; }
}

@keyframes pulse-wave-inner {
  0%, 100% { transform: scaleY(0.75); opacity: 0.35; }
  50% { transform: scaleY(1.15); opacity: 0.9; }
}

@keyframes fade-in {
  from { opacity: 0; transform: scale(0.9); }
  to { opacity: 1; transform: scale(1); }
}

@keyframes rotate-pulse {
  0% { transform: rotate(0deg) scale(1); }
  50% { transform: rotate(180deg) scale(1.08); }
  100% { transform: rotate(360deg) scale(1); }
}

/* ── 状态高亮：休眠中 ── */
.wake-btn-premium.sleeping {
  background: rgba(15, 23, 42, 0.45);
  border-color: rgba(255, 255, 255, 0.08);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25);
}

.wake-btn-premium.sleeping .mic-circle {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(255, 255, 255, 0.1);
  color: var(--text-muted);
}

.wake-btn-premium.sleeping .label-main {
  color: var(--text-muted);
}

/* ── 状态高亮：已唤醒（就绪待对话） ── */
.wake-btn-premium.awakened {
  background: rgba(14, 165, 233, 0.15);
  border-color: rgba(56, 189, 248, 0.6);
  box-shadow: 0 0 20px rgba(56, 189, 248, 0.25);
}

.wake-btn-premium.awakened .mic-circle {
  background: linear-gradient(135deg, rgba(56, 189, 248, 0.3) 0%, rgba(14, 165, 233, 0.1) 100%);
  border-color: rgba(56, 189, 248, 0.7);
  color: #38bdf8;
  box-shadow: 0 0 12px rgba(56, 189, 248, 0.3);
}

.wake-btn-premium.awakened .label-main {
  color: #38bdf8;
  text-shadow: 0 0 8px rgba(56, 189, 248, 0.4);
}

.wake-btn-premium.awakened .label-sub {
  color: rgba(56, 189, 248, 0.85);
}

/* ── 状态高亮：思考中 ── */
.wake-btn-premium.thinking {
  background: rgba(147, 51, 234, 0.2);
  border-color: rgba(168, 85, 247, 0.8);
  box-shadow: 0 0 25px rgba(168, 85, 247, 0.4);
}

.wake-btn-premium.thinking .mic-circle {
  background: linear-gradient(135deg, #7e22ce 0%, #a855f7 100%);
  border-color: rgba(168, 85, 247, 0.9);
  color: #fff;
  animation: rotate-pulse 2s infinite linear;
}

.wake-btn-premium.thinking .label-main {
  color: #d8b4fe;
  text-shadow: 0 0 8px rgba(168, 85, 247, 0.6);
}

.wake-btn-premium.thinking .label-sub {
  color: rgba(216, 180, 254, 0.85);
}

/* ── 状态高亮：回答中 ── */
.wake-btn-premium.speaking {
  background: rgba(16, 185, 129, 0.2);
  border-color: rgba(16, 185, 129, 0.85);
  box-shadow: 0 0 25px rgba(16, 185, 129, 0.45);
}

.wake-btn-premium.speaking .mic-circle {
  background: linear-gradient(135deg, #059669 0%, #10b981 100%);
  border-color: rgba(16, 185, 129, 0.9);
  color: #fff;
  animation: pulse-mic 1.2s infinite alternate;
}

.wake-btn-premium.speaking .label-main {
  color: #6ee7b7;
  text-shadow: 0 0 8px rgba(16, 185, 129, 0.6);
}

.wake-btn-premium.speaking .label-sub {
  color: rgba(110, 231, 183, 0.85);
}

/* 回答中的声波颜色 (极光绿) */
.sound-wave.speaking .arc-1 {
  border-color: rgba(16, 185, 129, 0.9);
  filter: drop-shadow(0 0 6px rgba(16, 185, 129, 0.8));
}
.sound-wave.speaking .arc-2 {
  border-color: rgba(16, 185, 129, 0.65);
  filter: drop-shadow(0 0 4px rgba(16, 185, 129, 0.5));
}
</style>
