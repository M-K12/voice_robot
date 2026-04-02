// 语音助手脚本 - 基于官方 porcupine.js 策略
let porcupine = null;
let isRunning = false;

// 页面加载时初始化关键词列表
window.addEventListener("load", function () {
  let usingBuiltIns = false;
  if (
    porcupineKeywords.length === 0 &&
    porcupineModel.publicPath.endsWith("porcupine_params.pv")
  ) {
    usingBuiltIns = true;
    for (const k in PorcupineWeb.BuiltInKeyword) {
      porcupineKeywords.push(k);
    }
  }

  let select = document.getElementById("keywords");
  for (let i = 0; i < porcupineKeywords.length; i++) {
    let el = document.createElement("option");
    el.textContent = usingBuiltIns
      ? PorcupineWeb.BuiltInKeyword[porcupineKeywords[i]]
      : porcupineKeywords[i].label;
    el.value = `${i}`;
    select.appendChild(el);
  }
  
  console.log("语音助手已加载，关键词数量:", porcupineKeywords.length);
});

// 写入状态消息
function writeMessage(message, type = 'info') {
  console.log(message);
  const statusBox = document.getElementById("statusBox");
  const statusDiv = document.getElementById("status");
  
  statusDiv.innerHTML = message;
  
  // 根据类型设置样式
  statusBox.className = 'status-box';
  if (type === 'active') {
    statusBox.classList.add('active');
  } else if (type === 'detected') {
    statusBox.classList.add('detected');
  } else if (type === 'error') {
    statusBox.classList.add('error');
  }
}

// 错误回调
function porcupineErrorCallback(error) {
  writeMessage(`❌ 错误: ${error}`, 'error');
  isRunning = false;
  updateButtons();
}

// 关键词检测回调
function porcupineKeywordCallback(detection) {
  const time = new Date();
  const message = `🔔 检测到唤醒词: ${detection.label}\n时间: ${time.toLocaleTimeString()}\n索引: ${detection.index}`;
  
  console.log(message);
  document.getElementById("result").innerHTML = message;
  writeMessage("检测到唤醒词！正在打开聊天窗口...", 'detected');
  
  // 打开聊天窗口
  openChatWindow();
  
  // 播放提示音
  playNotificationSound();
  
  // 3秒后恢复监听状态
  setTimeout(() => {
    if (isRunning) {
      writeMessage("🎤 正在监听唤醒词...", 'active');
    }
  }, 3000);
}

// 打开聊天窗口
function openChatWindow() {
  const chatUrl = document.getElementById('chatUrl').value;
  
  if (!chatUrl) {
    alert('请先输入聊天窗口 URL');
    return;
  }
  
  // 在新窗口打开聊天页面
  const chatWindowUrl = `chat_window.html?url=${encodeURIComponent(chatUrl)}`;
  const chatWindow = window.open(
    chatWindowUrl, 
    'ChatAssistant',
    'width=1000,height=800,resizable=yes,scrollbars=yes'
  );
  
  if (chatWindow) {
    console.log('聊天窗口已在新窗口打开:', chatUrl);
    chatWindow.focus();
  } else {
    alert('无法打开新窗口，请检查浏览器弹窗设置');
  }
}

// 播放提示音
function playNotificationSound() {
  try {
    const audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const oscillator = audioContext.createOscillator();
    const gainNode = audioContext.createGain();
    
    oscillator.connect(gainNode);
    gainNode.connect(audioContext.destination);
    
    oscillator.frequency.value = 800;
    oscillator.type = 'sine';
    
    gainNode.gain.setValueAtTime(0.3, audioContext.currentTime);
    gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.5);
    
    oscillator.start(audioContext.currentTime);
    oscillator.stop(audioContext.currentTime + 0.5);
  } catch (e) {
    console.log('无法播放提示音:', e);
  }
}

// 更新按钮状态
function updateButtons() {
  const startBtn = document.getElementById('startBtn');
  const stopBtn = document.getElementById('stopBtn');
  const keywordSelect = document.getElementById('keywords');
  
  startBtn.disabled = isRunning;
  stopBtn.disabled = !isRunning;
  keywordSelect.disabled = isRunning;
}

// 启动语音助手
async function startVoiceAssistant() {
  const accessKey = document.getElementById('accessKey').value;
  const keywordIndex = parseInt(document.getElementById('keywords').value);
  
  if (!accessKey) {
    alert('请先输入 AccessKey');
    return;
  }
  
  // 如果已经在运行，先停止
  if (window.WebVoiceProcessor.WebVoiceProcessor.isRecording) {
    await window.WebVoiceProcessor.WebVoiceProcessor.unsubscribe(porcupine);
    await porcupine.terminate();
  }

  writeMessage("⏳ Porcupine 正在加载，请稍候...");
  
  try {
    // 创建 Porcupine Worker
    porcupine = await PorcupineWeb.PorcupineWorker.create(
      accessKey,
      [porcupineKeywords[keywordIndex]],
      porcupineKeywordCallback,
      porcupineModel,
    );

    writeMessage("✅ Porcupine worker 已就绪！");

    writeMessage("🎤 正在初始化麦克风，请允许权限...");
    
    // 订阅 WebVoiceProcessor
    await window.WebVoiceProcessor.WebVoiceProcessor.subscribe(porcupine);

    isRunning = true;
    const keywordName = porcupineKeywords[keywordIndex].builtin || 
                        porcupineKeywords[keywordIndex].label || 
                        porcupineKeywords[keywordIndex];
    writeMessage(`🎤 正在监听唤醒词: "${keywordName}"`, 'active');
    updateButtons();
    
    console.log('语音助手已启动，监听关键词:', keywordName);
    
  } catch (err) {
    porcupineErrorCallback(err);
  }
}

// 停止语音助手
async function stopVoiceAssistant() {
  writeMessage("⏳ 正在停止语音助手...");
  
  try {
    if (window.WebVoiceProcessor.WebVoiceProcessor.isRecording) {
      await window.WebVoiceProcessor.WebVoiceProcessor.unsubscribe(porcupine);
    }
    
    if (porcupine) {
      await porcupine.terminate();
      porcupine = null;
    }
    
    isRunning = false;
    writeMessage("⏸️ 语音助手已停止");
    document.getElementById("result").innerHTML = '';
    updateButtons();
    
    console.log('语音助手已停止');
    
  } catch (err) {
    porcupineErrorCallback(err);
  }
}

// 页面卸载时清理
window.addEventListener('beforeunload', () => {
  if (porcupine && isRunning) {
    stopVoiceAssistant();
  }
});

// 监听关键词选择变化
document.addEventListener('DOMContentLoaded', () => {
  const keywordSelect = document.getElementById('keywords');
  if (keywordSelect) {
    keywordSelect.addEventListener('change', async () => {
      if (isRunning) {
        // 如果正在运行，重新启动以使用新关键词
        await stopVoiceAssistant();
        setTimeout(() => startVoiceAssistant(), 500);
      }
    });
  }
});
