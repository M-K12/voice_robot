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

// ... (props and state) ...
const props = defineProps({
  accessKey: { type: String, default: '' },
  keywordPaths: { type: [String, Array], default: () => [] },
  modelPath: { type: String, default: '' },
})

const emit = defineEmits(['wake', 'mic-error', 'mic-recovered'])

const isListening = ref(false)
const justDetected = ref(false)
const micError = ref(false)
let unlistenFn = null
let unlistenMicError = null
let detectedTimer = null

// Tauri API（懒加载）
let tauriInvoke = null
let tauriListen = null

async function loadTauriApis() {
  if (tauriInvoke) return true
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    const { listen } = await import('@tauri-apps/api/event')
    tauriInvoke = invoke
    tauriListen = listen
    return true
  } catch {
    return false
  }
}

async function toggleWake() {
  const hasTauri = await loadTauriApis()

  if (isListening.value) {
    // 停止监听
    if (hasTauri) {
      try { await tauriInvoke('stop_wake_word') } catch (e) { console.error(e) }
    }
    if (unlistenFn) { unlistenFn(); unlistenFn = null }
    isListening.value = false
    return
  }

  // 启动监听
  if (!hasTauri) {
    console.warn('此功能需要在 Tauri 桌面应用中运行。')
    return
  }
  if (!props.accessKey) {
    console.warn('请先在设置中填写 Picovoice AccessKey。')
    return
  }

  try {
    // 订阅唤醒事件
    unlistenFn = await tauriListen('wake-word-detected', (event) => {
      justDetected.value = true
      // event.payload 是触发的关键字索引
      emit('wake', event.payload)
      clearTimeout(detectedTimer)
      detectedTimer = setTimeout(() => { justDetected.value = false }, 2500)
    })

    // 处理 keywordPaths，如果是逗号分隔的字符串则转换为数组
    const paths = Array.isArray(props.keywordPaths)
      ? props.keywordPaths
      : props.keywordPaths.split(',').map(s => s.trim()).filter(s => s.length > 0)

    await tauriInvoke('start_wake_word', {
      accessKey: props.accessKey,
      keywordPaths: paths,
      modelPath: props.modelPath,
    })
    isListening.value = true
  } catch (e) {
    console.error('[wake_word]', e)
    // 自动启动失败时不弹窗打扰
    if (unlistenFn) { unlistenFn(); unlistenFn = null }
  }
}

onMounted(async () => {
  // 组件挂载后稍作延迟自动启动唤醒监听
  setTimeout(() => {
    if (!isListening.value) {
      toggleWake()
    }
  }, 1000)

  // 监听麦克风错误事件
  const hasTauri = await loadTauriApis()
  if (hasTauri && tauriListen) {
    unlistenMicError = await tauriListen('microphone-error', (event) => {
      console.error('[WakeWordIndicator] 麦克风异常:', event.payload)
      micError.value = true
      isListening.value = false
      emit('mic-error', event.payload)
    })
    unlistenMicRecovered = await tauriListen('microphone-recovered', (event) => {
      console.log('[WakeWordIndicator] 麦克风已恢复:', event.payload)
      micError.value = false
      isListening.value = true
      emit('mic-recovered')
    })
  }
})

function clearMicError() {
  micError.value = false
  // 尝试重新启动唤醒监听
  toggleWake()
}

let unlistenMicRecovered = null

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
