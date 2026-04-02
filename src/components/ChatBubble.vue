<template>
  <div class="message" :class="role">
    <div class="avatar">{{ role === 'user' ? '你' : '✦' }}</div>
    <div class="body" :class="{'loading-body': loading}">
      <div v-if="loading" class="typing">
        <span></span><span></span><span></span>
      </div>
      <div v-else class="md-content" v-html="rendered"></div>
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
  width: 30px; height: 30px; border-radius: 9px;
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; font-weight: 600; flex-shrink: 0; margin-top: 2px;
}
.user .avatar {
  background: rgba(99,179,237,0.15); color: var(--accent-blue);
}
.assistant .avatar {
  background: var(--accent-gradient); color: #080c14;
}

.body {
  padding: 10px 14px; border-radius: var(--radius-md);
  font-size: 0.9rem; line-height: 1.65;
}
.user .body {
  background: linear-gradient(135deg, rgba(99,179,237,0.1), rgba(167,139,250,0.08));
  border: 1px solid rgba(99,179,237,0.08);
  border-top-right-radius: 4px;
}
.assistant .body {
  background: rgba(255,255,255,0.03);
  border: 1px solid var(--border-subtle);
  border-top-left-radius: 4px;
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
</style>
