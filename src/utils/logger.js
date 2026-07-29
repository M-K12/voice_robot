/**
 * 前端日志工具类：在控制台打印的同时，异步上报至后端 /api/logs/frontend 接口
 * 供后端以 TimedRotatingFileHandler (按天切割、保留60天) 自动持久化保存到 logs/frontend/frontend.log
 */
class FrontendLogger {
  constructor(context = "FrontendApp") {
    this.context = context;
  }

  async _sendLog(level, message) {
    try {
      const payload = {
        level,
        message: typeof message === "object" ? JSON.stringify(message) : String(message),
        context: this.context,
        timestamp: new Date().toISOString()
      };
      
      fetch("/api/logs/frontend", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }).catch(() => {});
    } catch (e) {
      // 忽略日志发送本身的网络异常
    }
  }

  info(message) {
    console.log(`[${this.context}]`, message);
    this._sendLog("info", message);
  }

  warn(message) {
    console.warn(`[${this.context}]`, message);
    this._sendLog("warn", message);
  }

  error(message) {
    console.error(`[${this.context}]`, message);
    this._sendLog("error", message);
  }
}

export const logger = new FrontendLogger("FrontendApp");
export default logger;
