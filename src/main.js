import { createApp } from 'vue'
import App from './App.vue'
import './style.css'

const app = createApp(App)
app.config.errorHandler = (err, vm, info) => {
  console.error('[Vue error]', err, info, vm)
}
app.config.warnHandler = (msg, vm, trace) => {
  console.warn('[Vue warn]', msg, trace, vm)
}
app.mount('#app')

