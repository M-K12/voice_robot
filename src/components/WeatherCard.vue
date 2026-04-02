<template>
  <div class="weather-card">
    <!-- 关闭按钮 -->
    <button class="close-btn" @click="$emit('close')">✕</button>

    <!-- 城市 + 今日主信息 -->
    <div class="card-header">
      <div class="city-name">📍 {{ data.city }}</div>
      <div v-if="today" class="today-main">
        <span class="weather-label">{{ todayLabel }}</span>
        <span class="temp-range">{{ todayTempRange }}</span>
      </div>
    </div>



    <!-- 7 天卡片列表 -->
    <div class="daily-list">
      <div v-for="(d, i) in data.daily.slice(0, 7)" :key="i" class="day-item" :class="{today: i===0}">
        <div class="day-label">{{ shortLabel(d.label) }}</div>
        <div class="day-summary">{{ d.summary }}</div>
      </div>
    </div>

    <!-- 8 小时逐时 -->
    <div v-if="data.hourly && data.hourly.length" class="hourly-scroll">
      <div v-for="(h, i) in data.hourly.slice(0, 8)" :key="i" class="hour-item">
        <div class="hour-time">{{ h.hour }}</div>
        <div class="hour-summary">{{ h.summary }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  data: { type: Object, required: true },
  // data: { city, raw_text, daily:[{label, summary}], hourly:[{hour, summary}] }
})
defineEmits(['close'])



const today = computed(() => props.data.daily?.[0])
const todayLabel = computed(() => {
  const s = today.value?.summary || ''
  const m = s.match(/^([^\s]+)\s+/)
  return m ? m[1] : s.substring(0, 4)
})
const todayTempRange = computed(() => {
  const m = today.value?.summary?.match(/(高温[\d.]+℃\/低温[\d.]+℃)/)
  return m ? m[1] : ''
})

function shortLabel(label) {
  if (!label) return ''
  if (label.startsWith('今日')) return '今天'
  if (label.startsWith('明日')) return '明天'
  if (label.startsWith('后天')) return '后天'
  const wm = label.match(/^(周[一二三四五六日])/)
  return wm ? wm[1] : label.substring(0, 2)
}
</script>

<style scoped>
.weather-card {
  position: relative;
  background: linear-gradient(135deg, rgba(15,22,33,0.9) 0%, rgba(20,28,44,0.85) 100%);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  padding: 16px;
  backdrop-filter: blur(20px);
  animation: fadeUp 0.3s ease-out;
}
.close-btn {
  position: absolute; top: 10px; right: 12px;
  background: none; border: none; color: var(--text-muted);
  cursor: pointer; font-size: 0.85rem;
  transition: color var(--transition-fast);
}
.close-btn:hover { color: var(--text-primary); }

.card-header { margin-bottom: 12px; }
.city-name { font-family: var(--font-display); font-size: 1rem; font-weight: 600; margin-bottom: 4px; }
.today-main { display: flex; gap: 12px; align-items: center; }
.weather-label { color: var(--text-secondary); font-size: 0.85rem; }
.temp-range {
  font-size: 0.85rem;
  background: var(--accent-gradient);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}



/* 7 天列表 */
.daily-list {
  display: flex; gap: 4px; overflow-x: auto;
  padding-bottom: 6px; margin-bottom: 12px;
}
.day-item {
  flex-shrink: 0; min-width: 80px;
  background: var(--bg-input); border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  padding: 8px 6px; cursor: default;
  transition: border-color var(--transition-fast);
}
.day-item.today { border-color: rgba(99,179,237,0.3); }
.day-label { font-size: 0.72rem; color: var(--accent-blue); font-weight: 500; margin-bottom: 4px; }
.day-summary { font-size: 0.68rem; color: var(--text-muted); line-height: 1.4; }

/* 8 小时横列 */
.hourly-scroll {
  display: flex; gap: 6px; overflow-x: auto; padding-bottom: 2px;
}
.hour-item {
  flex-shrink: 0; min-width: 60px;
  background: rgba(255,255,255,0.03);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm); padding: 8px 6px; text-align: center;
}
.hour-time { font-size: 0.7rem; color: var(--accent-teal); margin-bottom: 3px; }
.hour-summary { font-size: 0.65rem; color: var(--text-muted); line-height: 1.3; }

@keyframes fadeUp {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
