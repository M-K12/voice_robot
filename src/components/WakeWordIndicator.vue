<template>
  <div class="wake-wrap">
    <!-- 唤醒按钮 -->
    <button
      class="wake-btn"
      :class="{ active: isListening, detected: justDetected, 'mic-error': micError }"
      @click="micError ? clearMicError() : toggleWake()"
      :title="micError ? '麦克风异常，点击重新连接' : isListening ? '点击停止唤醒监听' : '点击启动唤醒词监听'"
    >
      <span class="wake-ring" v-if="(isListening || justDetected) && !micError"></span>
      <span class="wake-icon">{{ micError ? '⚠️' : justDetected ? '🎙️' : isListening ? '👂' : '✨' }}</span>
      <span class="wake-label">{{ micError ? '麦克风异常' : justDetected ? '已唤醒' : isListening ? '聆听中' : '唤醒' }}</span>
    </button>
  </div>
</template>

<script setup>
import { ref, watch, onUnmounted, onMounted } from 'vue'
import { invoke as tauriInvoke } from '@tauri-apps/api/core'
import { listen as tauriListen } from '@tauri-apps/api/event'

const props = defineProps({
  keyword: { type: String, default: '小安小安' },
  modelPath: { type: String, default: '' },
})

const emit = defineEmits(['wake', 'mic-error', 'mic-recovered', 'debug'])

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

async function startListening() {
  if (isListening.value) return;
  
  const isTauriEnv = checkHasTauri();
  emit('debug', `[KWS] 准备启动监听，modelPath=${props.modelPath}，isTauriEnv=${isTauriEnv}`)
  
  if (!isTauriEnv) {
    emit('debug', '[KWS] 启动被忽略：未检测到 Tauri 宿主环境（可能在纯浏览器中运行）。')
    return;
  }
  try {
    if (!unlistenFn) {
      unlistenFn = await tauriListen('wake-word-detected', (event) => {
        emit('debug', `[KWS] 收到底层唤醒事件：payload=${event.payload}`)
        justDetected.value = true
        emit('wake', event.payload)
        clearTimeout(detectedTimer)
        detectedTimer = setTimeout(() => { justDetected.value = false }, 2500)
      })
    }

    emit('debug', '[KWS] 正在调用 Rust start_wake_word...')
    await tauriInvoke('start_wake_word', {
      modelDir: props.modelPath,
      keyword: props.keyword,
    })
    emit('debug', '[KWS] Rust start_wake_word 调用成功！已开始在后台采集并识别音频。')
    isListening.value = true
  } catch (e) {
    emit('debug', `[KWS] 启动失败！Rust 抛出异常：${e}`)
    if (unlistenFn) { unlistenFn(); unlistenFn = null }
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
  if (isListening.value) {
    await stopListening()
  } else {
    await startListening()
  }
}

defineExpose({ startListening, stopListening })

onMounted(async () => {
  emit('debug', '[KWS] 组件挂载，等待 1000ms 以确保 Tauri 运行环境注入完成...')
  
  // 稍作延迟注册事件与启动唤醒，防止在加载一瞬间由于时序问题导致 window.__tauri_ipc__ 还没来得及注入
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
.wake-wrap { display: flex; align-items: center; }

.wake-btn {
  position: relative;
  display: flex; align-items: center; gap: 6px;
  padding: 6px 12px;
  background: rgba(167,139,250,0.1);
  border: 1px solid rgba(167,139,250,0.2);
  border-radius: var(--radius-sm);
  color: var(--accent-purple);
  font-size: 0.8rem; font-weight: 500;
  cursor: pointer; overflow: visible;
  transition: all 0.2s;
}
.wake-btn:hover { background: rgba(167,139,250,0.18); }

.wake-btn.active {
  background: rgba(167,139,250,0.2);
  border-color: rgba(167,139,250,0.5);
  box-shadow: 0 0 14px rgba(167,139,250,0.25);
  animation: wake-pulse 2s infinite;
}
.wake-btn.detected {
  background: rgba(99,179,237,0.2);
  border-color: rgba(99,179,237,0.5);
  color: var(--accent-blue);
  box-shadow: 0 0 18px rgba(99,179,237,0.35);
  animation: none;
}

/* 波纹圆环 */
.wake-ring {
  position: absolute; inset: -6px;
  border-radius: inherit;
  border: 2px solid rgba(167,139,250,0.35);
  animation: ring-expand 1.6s ease-out infinite;
  pointer-events: none;
}
.detected .wake-ring { border-color: rgba(99,179,237,0.4); }

@keyframes ring-expand {
  0%  { transform: scale(1);   opacity: 0.8; }
  100% { transform: scale(1.5); opacity: 0; }
}
@keyframes wake-pulse {
  0%   { box-shadow: 0 0 0 0 rgba(167,139,250,0.4); }
  70%  { box-shadow: 0 0 0 8px rgba(167,139,250,0); }
  100% { box-shadow: 0 0 0 0 rgba(167,139,250,0); }
}
/* 麦克风异常 */
.wake-btn.mic-error {
  background: rgba(239, 68, 68, 0.15);
  border-color: rgba(239, 68, 68, 0.5);
  color: #f87171;
  box-shadow: 0 0 14px rgba(239, 68, 68, 0.25);
  animation: none;
}
.wake-btn.mic-error:hover {
  background: rgba(239, 68, 68, 0.25);
}
</style>
