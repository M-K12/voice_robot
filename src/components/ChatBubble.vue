<template>
  <div class="message" :class="[role, { 'interim': !isFinal }]">
    <div class="avatar">{{ role === 'user' ? '你' : '✦' }}</div>
    <div class="body" :class="{'loading-body': loading}">
      <div v-if="loading" class="typing">
        <span></span><span></span><span></span>
      </div>
      <div v-else class="md-content" v-html="rendered"></div>
      <span v-if="!isFinal && !loading" class="interim-cursor">|</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { marked } from 'marked'

const props = defineProps({
  role: { type: String, required: true },   // 'user' | 'assistant'
  content: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  isFinal: { type: Boolean, default: true },
})

marked.setOptions({ breaks: true, gfm: true })

const rendered = computed(() => {
  try { return marked.parse(props.content || '') }
  catch { return props.content }
})
</script>

<style scoped>
.message {
  display: flex; gap: 10px; max-width: 88%;
  animation: fadeUp 0.25s ease-out;
}
.message.user { margin-left: auto; flex-direction: row-reverse; }

.avatar {
  width: 32px; height: 32px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; font-weight: 600; flex-shrink: 0; margin-top: 2px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.3);
  transition: all var(--transition-fast);
}
.avatar:hover {
  transform: scale(1.05);
}
.user .avatar {
  background: rgba(99,179,237,0.18); color: var(--accent-blue);
  border: 1px solid rgba(99,179,237,0.3);
  box-shadow: 0 0 12px rgba(99,179,237,0.2);
}
.assistant .avatar {
  background: var(--accent-gradient); color: #080c14;
  box-shadow: 0 0 12px rgba(167,139,250,0.3);
}

.body {
  padding: 12px 16px; border-radius: var(--radius-md);
  font-size: 0.9rem; line-height: 1.65;
  transition: all var(--transition-fast);
  backdrop-filter: blur(12px);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
}
.body:hover {
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
}
.user .body {
  background: linear-gradient(135deg, rgba(99,179,237,0.15), rgba(167,139,250,0.1));
  border: 1px solid rgba(99,179,237,0.22);
  border-top-right-radius: 4px;
}
.user .body:hover {
  border-color: rgba(99,179,237,0.35);
  box-shadow: 0 0 16px rgba(99,179,237,0.08), 0 8px 24px rgba(0, 0, 0, 0.25);
}
.assistant .body {
  background: rgba(15, 23, 42, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-top-left-radius: 4px;
}
.assistant .body:hover {
  border-color: rgba(255, 255, 255, 0.1);
}

/* Markdown 内容 */
.md-content :deep(p) { margin-bottom: 0.5em; }
.md-content :deep(p:last-child) { margin-bottom: 0; }
.md-content :deep(strong) { color: var(--accent-blue); }
.md-content :deep(em) { color: var(--accent-purple); }
.md-content :deep(code):not(pre code) {
  background: rgba(99,179,237,0.1); color: var(--accent-blue);
  padding: 1px 5px; border-radius: 4px; font-size: 0.85em;
}
.md-content :deep(pre) {
  background: #0d1117; border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm); overflow-x: auto; margin: 0.6em 0;
}
.md-content :deep(pre code) {
  display: block; padding: 12px 14px; font-size: 0.82rem; line-height: 1.5;
}
.md-content :deep(ul), .md-content :deep(ol) { padding-left: 1.4em; margin: 0.4em 0; }
.md-content :deep(li) { margin-bottom: 0.25em; }
.md-content :deep(blockquote) {
  border-left: 3px solid var(--accent-purple);
  padding: 4px 12px; margin: 0.5em 0;
  color: var(--text-secondary); background: rgba(167,139,250,0.05);
}

/* 加载动画 */
.typing { display: inline-flex; gap: 4px; padding: 4px 0; }
.typing span {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--text-muted);
  animation: bounce 1.2s ease-in-out infinite;
}
.typing span:nth-child(2) { animation-delay: 0.15s; }
.typing span:nth-child(3) { animation-delay: 0.3s; }
@keyframes bounce {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
  30% { transform: translateY(-6px); opacity: 1; }
}

@keyframes fadeUp {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

/* 中间态识别结果 */
.message.interim .body {
  opacity: 0.55;
  border-style: dashed;
  transition: opacity 0.2s ease;
}
.interim-cursor {
  display: inline-block;
  margin-left: 3px;
  color: var(--accent-blue);
  animation: blink 1.2s step-end infinite;
}
@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}
</style>
