<template>
  <!-- 如果是独立设置窗口，只渲染大面板并铺满整屏 -->
  <div v-if="isSettingsWindow" class="independent-settings-root">
    <div class="settings-dialog independent-settings-dialog">
      <div class="settings-header">
        <h3>⚙️ 控制面板设置</h3>
      </div>
      <div class="settings-container">
        <!-- 左侧导航 -->
        <nav class="settings-sidebar">
          <button class="tab-btn" :class="{ active: activeTab === 'general' }" @click="activeTab = 'general'">
            <span class="tab-icon">🌐</span> 通用设置
          </button>
          <button class="tab-btn" :class="{ active: activeTab === 'kws' }" @click="activeTab = 'kws'">
            <span class="tab-icon">🎙️</span> 语音唤醒
          </button>
          <button class="tab-btn" :class="{ active: activeTab === 'llm' }" @click="activeTab = 'llm'">
            <span class="tab-icon">🤖</span> 模型设置
          </button>
        </nav>
        
        <!-- 右侧面板 -->
        <div class="settings-content">
          <!-- Tab 1: 通用设置 -->
          <div v-show="activeTab === 'general'" class="tab-panel">
            <div class="form-group">
              <label class="form-label">后端服务地址</label>
              <input v-model="settings.backendUrl" type="text" class="form-input" placeholder="http://127.0.0.1:10850" />
              <span class="form-help">FastAPI 后端服务的本地监听地址。</span>
            </div>
            <div class="form-group">
              <label class="form-label">默认聚焦城市</label>
              <input v-model="settings.defaultCity" type="text" class="form-input" placeholder="成都" />
              <span class="form-help">当对话中未显式提及城市名时的天气聚焦城市。</span>
            </div>
            <div class="form-group" style="margin-top: 10px;">
              <label class="form-label">大屏视觉端类别 (Visual Terminal UI)</label>
              <select v-model="settings.visualTerminal" class="form-select">
                <option value="demo_ui">demo_ui</option>
                <option value="app_ui">app_ui</option>
              </select>
              <span class="form-help">控制后端通过 WebSocket 广播给大屏端的数据指令协议标准 (demo_ui / app_ui)。</span>
            </div>
            <div class="form-group checkbox-group" style="margin-top: 10px; padding: 4px 0;">
              <div style="display: flex; align-items: center; gap: 10px;">
                <input v-model="isStartFullscreen" type="checkbox" id="isStartFullscreenCheckboxSettings" class="form-checkbox" @change="onStartFullscreenChange" />
                <label for="isStartFullscreenCheckboxSettings" class="checkbox-title">前端启动时全屏</label>
              </div>
              <span class="form-help" style="margin-left: 26px;">开启后，前端应用启动时主窗口将自动进入全屏显示。</span>
            </div>
            <div class="form-group checkbox-group" style="margin-top: 10px; padding: 4px 0;">
              <div style="display: flex; align-items: center; gap: 10px;">
                <input v-model="settings.enableVisualBroadcast" type="checkbox" id="enableVisualBroadcastSettingsWindow" class="form-checkbox" />
                <label for="enableVisualBroadcastSettingsWindow" class="checkbox-title">开启大屏视觉端同步广播</label>
              </div>
              <p class="checkbox-desc">开启后，文字、天气面板、地图缩放等交互控制指令会通过独立的 WebSocket 管道广播投递给三维地理大屏网页端，进行无缝的视觉联动展示。</p>
            </div>
            <div class="form-group checkbox-group" style="margin-top: 10px; padding: 4px 0;">
              <div style="display: flex; align-items: center; gap: 10px;">
                <input v-model="settings.showWeatherCard" type="checkbox" id="showWeatherCardSettingsWindow" class="form-checkbox" />
                <label for="showWeatherCardSettingsWindow" class="checkbox-title">展示天气卡片</label>
              </div>
              <span class="form-help" style="margin-left: 26px;">关闭后，天气信息将不再弹出可视化卡片，仅保留语音和文字回复。</span>
            </div>
            <div class="form-group" style="margin-top: 14px;">
              <label class="form-label">控制台日志显示等级</label>
              <select v-model="settings.logLevel" class="form-select">
                <option value="DEBUG">DEBUG (详细调试)</option>
                <option value="INFO">INFO (标准信息)</option>
                <option value="WARNING">WARNING (仅警告与错误)</option>
                <option value="ERROR">ERROR (仅严重错误)</option>
              </select>
              <span class="form-help">控制终端控制台中实时的日志打印级别。</span>
            </div>
            <div class="form-group">
              <label class="form-label">磁盘日志保存等级</label>
              <select v-model="settings.logFileLevel" class="form-select">
                <option value="DEBUG">DEBUG (全部记录)</option>
                <option value="INFO">INFO (标准记录)</option>
                <option value="WARNING">WARNING (仅警告与错误)</option>
                <option value="ERROR">ERROR (仅严重错误)</option>
              </select>
              <span class="form-help">写入 logs/backend/backend.log 磁盘文件的日志保留级别。</span>
            </div>
            <div class="form-group">
              <label class="form-label">无对话超时挂断时间（秒）</label>
              <input v-model.number="settings.sessionIdleTimeoutSec" type="number" class="form-input" placeholder="30" min="0" />
              <span class="form-help">静默无对话自动关停通话的时间（单位：秒，设为 0 代表禁用自动超时挂断）。</span>
            </div>
          </div>

          <!-- Tab 2: 语音唤醒 -->
          <div v-show="activeTab === 'kws'" class="tab-panel">
            <div class="form-group">
              <label class="form-label">Sherpa-Onnx 唤醒词模型</label>
              <div class="select-editable-wrapper">
                <select v-model="settings.modelDir" class="form-select">
                  <option v-for="opt in kwsModelOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                  <option value="custom">-- 自定义选择文件夹 --</option>
                </select>
                <div class="input-with-btn custom-input" v-if="settings.modelDir === 'custom' || !kwsModelOptions.map(o => o.value).includes(settings.modelDir)">
                  <input v-model="settings.modelDir" type="text" placeholder="选择存放 ONNX 模型的文件夹" class="form-input" style="flex: 1;" />
                  <button @click.stop="pickDirectory('modelDir')">📂</button>
                </div>
              </div>
              <span class="form-help">支持切换 WenetSpeech 中文模型或 ZH-EN 双语模型。</span>
            </div>
            <div class="form-group">
              <label class="form-label">本地侦听唤醒词</label>
              <textarea 
                v-model="settings.wakeWord" 
                placeholder="输入唤醒词，如：&#10;小安小安&#10;你好军哥&#10;（每行一个）" 
                class="form-input wake-word-textarea" 
                rows="12" 
              ></textarea>
              <span class="form-help">支持输入纯中文（每行一个，自动转拼音），或直接输入带有阈值的拼音微调行（如 <code>x iǎo ān x iǎo ān :3.0 #0.08 @小安小安</code>）。系统会自动保存并同步模型目录下的 <code>keywords.txt</code>。</span>
            </div>

            <!-- KWS 引擎高级参数 -->
            <fieldset class="settings-fieldset">
              <legend class="fieldset-legend">⚙️ KWS 引擎参数</legend>
              <span class="form-help" style="display:block;margin-bottom:10px;">调整唤醒灵敏度与精度。<code>keywords.txt</code> 中的逐行 <code>:score</code>/<code>#threshold</code> 会覆盖下方全局值。</span>

              <div class="form-group">
                <div style="display:flex;justify-content:space-between;align-items:center;">
                  <label class="form-label">全局 boosting 分数 (keywords_score): {{ settings.kwsScore }}</label>
                </div>
                <input type="range" v-model.number="settings.kwsScore" min="0.5" max="5.0" step="0.1"
                  style="width:100%;accent-color:#00e5ff;height:6px;border-radius:3px;background:rgba(255,255,255,0.1);cursor:pointer;" />
                <span class="form-help">越大越容易触发（提高召回率）；越小越保守（减少误触）。推荐 1.0–2.0，默认 1.5。</span>
              </div>

              <div class="form-group">
                <div style="display:flex;justify-content:space-between;align-items:center;">
                  <label class="form-label">全局触发阈值 (keywords_threshold): {{ settings.kwsThreshold }}</label>
                </div>
                <input type="range" v-model.number="settings.kwsThreshold" min="0.01" max="0.5" step="0.01"
                  style="width:100%;accent-color:#00e5ff;height:6px;border-radius:3px;background:rgba(255,255,255,0.1);cursor:pointer;" />
                <span class="form-help">越小越灵敏（更容易唤醒）；越大越严格（需要更清晰发音）。推荐 0.1–0.3，默认 0.25。</span>
              </div>

              <div class="form-group">
                <label class="form-label">Beam Search 宽度 (max_active_paths)</label>
                <select v-model.number="settings.kwsMaxActivePaths" class="form-select">
                  <option :value="2">2 — 最快，精度略低</option>
                  <option :value="4">4 — 平衡（推荐）</option>
                  <option :value="8">8 — 较慢，精度更高</option>
                </select>
                <span class="form-help">Beam search 搜索宽度，值越大精度越高但 CPU 开销越大。</span>
              </div>

              <div class="form-group">
                <label class="form-label">尾部空白帧 (num_trailing_blanks)</label>
                <select v-model.number="settings.kwsNumTrailingBlanks" class="form-select">
                  <option :value="1">1 — 默认</option>
                  <option :value="2">2 — 减少截断误判</option>
                  <option :value="0">0 — 最快响应</option>
                </select>
                <span class="form-help">关键词结束后等待的空白帧数，越大延迟越高但误判越少。</span>
              </div>
            </fieldset>
          </div>

          <!-- Tab 3: 模型设置 -->
          <div v-show="activeTab === 'llm'" class="tab-panel scrollable-panel">
            <!-- 文字对话模型 -->
            <fieldset class="settings-fieldset">
              <legend class="fieldset-legend">📝 文字对话模型</legend>
              <div class="form-group">
                <label class="form-label">* 文字对话大模型</label>
                <div class="select-editable-wrapper">
                  <select v-model="settings.textModelName" class="form-select">
                    <option v-for="opt in textModelOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                    <option value="custom">-- 自定义输入 --</option>
                  </select>
                  <input 
                    v-if="settings.textModelName === 'custom' || !textModelOptions.map(o => o.value).includes(settings.textModelName)"
                    v-model="settings.textModelName" 
                    type="text" 
                    placeholder="请输入自定义文字模型名" 
                    class="form-input custom-input" 
                  />
                </div>
                <span class="form-help">用于键盘打字聊天的推理大脑，以及语音级联模式下的文本生成核心。</span>
              </div>
              <div class="form-group">
                <label class="form-label">工具调用执行模式</label>
                <div class="radio-group">
                  <label class="radio-label"><input type="radio" v-model="settings.textModelToolMode" value="parallel" /> 并行 (parallel)</label>
                  <label class="radio-label"><input type="radio" v-model="settings.textModelToolMode" value="serial" /> 串行 (serial)</label>
                </div>
                <span class="form-help">控制文字对话执行工具是并发或串行排队。</span>
              </div>
              <div class="form-group">
                <label class="form-label">工具触发提取风格</label>
                <div class="radio-group">
                  <label class="radio-label"><input type="radio" v-model="settings.textModelToolStyle" value="native" /> 原生 FC (native)</label>
                  <label class="radio-label"><input type="radio" v-model="settings.textModelToolStyle" value="router" /> 意图路由 (router)</label>
                </div>
                <span class="form-help">原生依靠大模型 API 自身的 Function Calling 能力；路由则是根据题干意图自主判定。</span>
              </div>
            </fieldset>

            <!-- 语音对话模型 -->
            <fieldset class="settings-fieldset">
              <legend class="fieldset-legend">🔊 语音对话模型</legend>
              
              <div class="form-group">
                <label class="form-label">语音通话架构模式选择</label>
                <div class="radio-group">
                  <label class="radio-label">
                    <input type="radio" v-model="settings.voiceInteractionStyle" value="e2e" /> 端到端模式 (Voice-to-Voice)
                  </label>
                  <label class="radio-label">
                    <input type="radio" v-model="settings.voiceInteractionStyle" value="cascade" /> 级联模式 (ASR + LLM + TTS)
                  </label>
                </div>
                <span class="form-help">端到端模式提供低延迟、带语气情感和呼吸声的云端对话；级联模式则将识别、大模型与合成切分，支持高度定制和完全单机离线。</span>
              </div>

              <!-- A: 端到端模式配置 -->
              <template v-if="settings.voiceInteractionStyle === 'e2e'">
                <div class="form-group">
                  <label class="form-label">* 端到端实时语音模型名</label>
                  <div class="select-editable-wrapper">
                    <select v-model="settings.voiceModelName" class="form-select">
                      <option v-for="opt in voiceModelOptions.filter(o => o.value !== 'sherpa-local')" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                      <option value="custom">-- 自定义输入 --</option>
                    </select>
                    <input 
                      v-if="settings.voiceModelName === 'custom' || (!voiceModelOptions.map(o => o.value).includes(settings.voiceModelName) && settings.voiceModelName !== 'sherpa-local')"
                      v-model="settings.voiceModelName" 
                      type="text" 
                      placeholder="请输入自定义端到端模型名" 
                      class="form-input custom-input" 
                    />
                  </div>
                </div>

                <div class="form-group">
                  <label class="form-label">语音通话实时音色</label>
                  <select v-model="settings.voice" class="form-select">
                    <option v-for="opt in voiceOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                  </select>
                  <span class="form-help">实时通话发音音色，保存后系统会自动使用该音色重新生成唤醒响应提示音。</span>
                </div>

                <!-- 科大讯飞超拟人专属配置项 -->
                <template v-if="settings.voiceModelName === 'xunfei-realtime'">
                  <div class="form-group">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                      <label class="form-label">超拟人合成语速: {{ settings.voiceSpeed }}</label>
                    </div>
                    <input type="range" v-model.number="settings.voiceSpeed" min="0" max="100" step="1" style="width: 100%; accent-color: #00e5ff; height: 6px; border-radius: 3px; background: rgba(255,255,255,0.1); cursor: pointer;" />
                    <span class="form-help">控制科大讯飞大模型超拟人发音合成的速度（取值 0-100，默认 50，数值越小越慢，越大越快）。</span>
                  </div>
                </template>

                <div class="form-group">
                  <div style="display: flex; justify-content: space-between; align-items: center;">
                    <label class="form-label">采样温度 (Temperature): {{ settings.e2eTemperature }}</label>
                  </div>
                  <input type="range" v-model.number="settings.e2eTemperature" min="0.0" max="2.0" step="0.1" style="width: 100%; accent-color: #00e5ff; height: 6px; border-radius: 3px; background: rgba(255,255,255,0.1); cursor: pointer;" />
                  <span class="form-help">控制语音应答的语气随机性与词汇创造力。</span>
                </div>

                <div class="form-group">
                  <label class="form-label">最大输出 Token 数</label>
                  <input type="number" v-model.number="settings.e2eMaxTokens" min="1" max="4096" class="form-input" />
                  <span class="form-help">限制单次回答的最大长度，防止大模型发生长篇大论。</span>
                </div>

                <div class="form-group">
                  <label class="form-label">AI 播报打断拦截模式</label>
                  <select v-model="settings.interruptionMode" class="form-select">
                    <option value="wake_word_only">wake_word_only (仅唤醒词打断 - 推荐)</option>
                    <option value="any_speech">any_speech (任意说话即打断 - 全双工)</option>
                  </select>
                  <span class="form-help">控制小安正在回答/播放音频时的打断策略。“仅唤醒词打断”模式下普通杂音/说话自动切至端侧 KWS，避免打断，喊出唤醒词后瞬间截断打断。</span>
                </div>
                
                <!-- Qwen-Audio 3.0 Realtime 专属配置块 -->
                <template v-if="settings.voiceModelName === 'qwen-audio-3.0-realtime-plus' || settings.voiceModelName === 'qwen-audio-3.0-realtime-flash'">
                  <fieldset class="settings-fieldset" style="margin-top: 15px; border-color: rgba(0, 229, 255, 0.2); padding: 15px; border-radius: 8px; border-style: solid; border-width: 1px;">
                    <legend class="fieldset-legend" style="color: #00e5ff; padding: 0 10px; font-weight: 600;">🎙️ Qwen-Audio 专属配置</legend>
                    
                    <!-- 实时语音识别流式推送开关 -->
                    <div class="form-group" style="display: flex; justify-content: space-between; align-items: center; background: rgba(0, 229, 255, 0.04); border: 1px solid rgba(0, 229, 255, 0.12); border-radius: 8px; padding: 10px 14px; margin-bottom: 15px;">
                      <div>
                        <label class="form-label" style="margin-bottom: 2px; font-weight: 600; color: #00e5ff;">⚡ 实时语音识别流式推送 (ASR Stream Push)</label>
                        <span class="form-help" style="margin: 0; font-size: 0.76rem;">
                          {{ settings.streamAsrEnabled ? '开启后：说话时同步实时流式展示文本片段 (推荐)' : '关闭后：完整说完一整句话后统一展示识别结果' }}
                        </span>
                      </div>
                      <label class="switch-toggle" style="position: relative; display: inline-block; width: 44px; height: 24px; flex-shrink: 0; margin-left: 12px;">
                        <input type="checkbox" v-model="settings.streamAsrEnabled" style="opacity: 0; width: 0; height: 0;" />
                        <span class="slider" :style="{
                          position: 'absolute', cursor: 'pointer', top: 0, left: 0, right: 0, bottom: 0,
                          backgroundColor: settings.streamAsrEnabled ? '#00e5ff' : 'rgba(255,255,255,0.2)',
                          transition: '.3s', borderRadius: '24px', boxShadow: settings.streamAsrEnabled ? '0 0 10px rgba(0,229,255,0.5)' : 'none'
                        }">
                          <span :style="{
                            position: 'absolute', height: '18px', width: '18px', left: '3px', bottom: '3px',
                            backgroundColor: '#fff', transition: '.3s', borderRadius: '50%',
                            transform: settings.streamAsrEnabled ? 'translateX(20px)' : 'translateX(0)'
                          }"></span>
                        </span>
                      </label>
                    </div>

                    <div class="form-group">
                      <label class="form-label">历史对话参考轮数限制</label>
                      <input type="number" v-model.number="settings.qwenAudioMaxHistoryTurns" min="1" max="50" class="form-input" />
                      <span class="form-help">模型参考的多轮对话历史 QA 轮数，取值范围 1-50，默认 20。较小值有利于减少回复延迟。</span>
                    </div>

                    <div class="form-group">
                      <label class="form-label">对话交互轮次检测模式</label>
                      <select v-model="settings.qwenAudioTurnMode" class="form-select" :disabled="settings.qwenAudioVoiceprintMode === 'static'">
                        <option value="server_vad">server_vad (声学 VAD 自动检测)</option>
                        <option value="smart_turn">smart_turn (智能语义轮次 - 推荐)</option>
                        <option value="push_to_talk">push_to_talk (手动控制 / 手动提交)</option>
                      </select>
                      <span class="form-help">控制何时触发 AI 的回应。当启用静态声纹锁定时，系统将强制锁定为 <code>smart_turn</code> 模式。</span>
                    </div>

                    <!-- 声纹锁定模式选择 -->
                    <div class="form-group">
                      <label class="form-label">声纹锁定</label>
                      <select v-model="settings.qwenAudioVoiceprintMode" class="form-select">
                        <option value="none">无锁定 (不限制发言人)</option>
                        <option value="dynamic">自动锁定首位说话人 (首轮通话录音并动态锁定)</option>
                        <option value="static">绑定已有静态声纹 (精准锁定录制好的声纹特征)</option>
                      </select>
                      <span class="form-help">智能语义轮次专用：提取发音人声音特征以过滤旁人干扰。</span>
                    </div>

                    <!-- A. 静态声纹：组合在同一行的两级下拉框与控制按钮 -->
                    <div class="form-group" v-if="settings.qwenAudioVoiceprintMode === 'static'">
                      <label class="form-label" style="display: flex; justify-content: space-between; align-items: center;">
                        <span>选择绑定的已有声纹角色与具体采样</span>
                        <span style="font-size: 0.75rem; color: #00e5ff;" v-if="settings.selectedVoiceprintId && selectedRoleSamples.length > 0">
                          (已选角色共 {{ selectedRoleSamples.length }}/5 段采样)
                        </span>
                      </label>
                      
                      <div style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center;">
                        <!-- 1. 选择声纹角色下拉框 -->
                        <select v-model="settings.selectedVoiceprintId" class="form-select" style="flex: 1; min-width: 140px; height: 38px;">
                          <option value="">-- 请选择声纹角色 --</option>
                          <option v-for="vp in voiceprints" :key="vp.id" :value="vp.id">
                            {{ vp.name }} ({{ vp.sample_count || 1 }}/5 段)
                          </option>
                        </select>

                        <!-- 2. 右侧对应角色的声纹音频文件列表下拉框 -->
                        <select 
                          v-if="settings.selectedVoiceprintId && selectedRoleSamples.length > 0" 
                          v-model="selectedSampleId" 
                          class="form-select" 
                          style="flex: 1.3; min-width: 160px; height: 38px; font-size: 0.8rem;"
                        >
                          <option v-for="(sample, idx) in selectedRoleSamples" :key="sample.id || idx" :value="sample.id">
                            {{ sample.created_at || sample.filename }} {{ idx === 0 ? ' (最新采样 ★)' : '' }}
                          </option>
                        </select>

                        <!-- 3. 精准删除选中采样按钮 -->
                        <button 
                          type="button" 
                          v-if="selectedSampleId" 
                          @click="deleteSingleVoiceprintSample(selectedSampleId)" 
                          class="btn-micro" 
                          style="background: rgba(255, 77, 79, 0.15); border: 1px solid rgba(255, 77, 79, 0.4); color: #ff4d4f; width: auto; padding: 0 10px; height: 38px; border-radius: 8px; font-size: 0.78rem; white-space: nowrap;" 
                          title="删除下拉框中选中的具体音频文件"
                        >
                          🗑️ 删除采样
                        </button>

                        <!-- 4. 删除整个角色按钮 -->
                        <button 
                          type="button" 
                          v-if="settings.selectedVoiceprintId" 
                          @click="deleteVoiceprintRole(settings.selectedVoiceprintId)" 
                          class="btn-micro" 
                          style="background: rgba(255, 77, 79, 0.12); border: 1px solid rgba(255, 77, 79, 0.3); color: #ff4d4f; width: auto; padding: 0 8px; height: 38px; border-radius: 8px; font-size: 0.78rem; white-space: nowrap;" 
                          title="删除选中的整个声纹角色及其所有采样"
                        >
                          🗑️ 清空角色
                        </button>

                        <!-- 5. 录制新声纹按钮 -->
                        <button type="button" @click="startRecordVoiceprintFlow" class="btn-micro start" style="width: auto; padding: 0 14px; white-space: nowrap; height: 38px; border-radius: 8px;">
                          🎙️ 录制新声纹
                        </button>
                      </div>

                      <span class="form-help" v-if="voiceprints.length === 0" style="color: #ff4d4f;">⚠️ 暂无可用声纹角色，请点击右侧按钮录制并创建角色。</span>
                    </div>




                    <!-- B. 动态声纹：提示文字 -->
                    <div class="form-group" v-if="settings.qwenAudioVoiceprintMode === 'dynamic'" style="background: rgba(0, 229, 255, 0.05); border: 1px solid rgba(0, 229, 255, 0.15); border-radius: 8px; padding: 12px; margin-bottom: 12px;">
                      <span class="form-help" style="color: #00e5ff; margin: 0; font-size: 0.8rem; line-height: 1.5;">
                        ℹ️ <strong>自动首句锁定</strong>：通话开始的第一回合，系统会以常规模式捕获您的声音并保存，第二回合起自动锁定您的声纹，旁人或嘈杂的背景人声将不会打断对话。
                      </span>
                    </div>

                    <!-- C. 无锁定：兼容旧的手填 URLs 功能 -->
                    <div class="form-group" v-if="settings.qwenAudioVoiceprintMode === 'none'">
                      <label class="form-label">锁定说话人预录音频 URLs (兼容项)</label>
                      <textarea 
                        v-model="settings.qwenAudioVoiceprintAudioUrls" 
                        placeholder="请输入目标用户的预录音频公网 URL&#10;支持多个，每行输入一个&#10;格式支持 16kHz PCM 或 WAV" 
                        class="form-input" 
                        rows="3" 
                      ></textarea>
                      <span class="form-help">如果不使用上述自动模式，您仍可以在此手动填入多行参考音频公网链接来完成声纹配置。</span>
                    </div>

                    <!-- D. server_vad 专属配置项：VAD 灵敏度阈值 -->
                    <div class="form-group" v-if="settings.qwenAudioTurnMode === 'server_vad' && settings.qwenAudioVoiceprintMode !== 'static'">
                      <div style="display: flex; justify-content: space-between; align-items: center;">
                        <label class="form-label">VAD 灵敏度阈值 (threshold): {{ settings.qwenAudioVadThreshold }}</label>
                      </div>
                      <input type="range" v-model.number="settings.qwenAudioVadThreshold" min="-1.0" max="1.0" step="0.05" style="width: 100%; accent-color: #00e5ff; height: 6px; border-radius: 3px; background: rgba(255,255,255,0.1); cursor: pointer;" />
                      <span class="form-help">声学VAD判定灵敏度，值越小越灵敏越容易触发，值越大越严格。范围 [-1.0, 1.0]，默认 0.5。</span>
                    </div>
                  </fieldset>
                </template>
              </template>

              <!-- B: 级联模式配置 -->
              <template v-else-if="settings.voiceInteractionStyle === 'cascade'">
                <div class="form-group">
                  <label class="form-label">* 级联语音对话大模型</label>
                  <div class="select-editable-wrapper">
                    <select v-model="settings.voiceCascadeModelName" class="form-select">
                      <option v-for="opt in textModelOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                      <option value="custom">-- 自定义输入 --</option>
                    </select>
                    <input 
                      v-if="settings.voiceCascadeModelName === 'custom' || !textModelOptions.map(o => o.value).includes(settings.voiceCascadeModelName)"
                      v-model="settings.voiceCascadeModelName" 
                      type="text" 
                      placeholder="请输入自定义级联大脑模型名" 
                      class="form-input custom-input" 
                    />
                  </div>
                  <span class="form-help">此大模型将作为您在本地级联语音通话时的推理脑。</span>
                </div>

                <div class="form-group">
                  <label class="form-label">级联大脑工具调用执行模式</label>
                  <div class="radio-group">
                    <label class="radio-label"><input type="radio" v-model="settings.voiceCascadeModelToolMode" value="parallel" /> 并行 (parallel)</label>
                    <label class="radio-label"><input type="radio" v-model="settings.voiceCascadeModelToolMode" value="serial" /> 串行 (serial)</label>
                  </div>
                  <span class="form-help">控制级联语音大模型执行工具是并发或是串行排队。</span>
                </div>

                <div class="form-group">
                  <label class="form-label">级联大脑工具触发提取风格</label>
                  <div class="radio-group">
                    <label class="radio-label"><input type="radio" v-model="settings.voiceCascadeModelToolStyle" value="native" /> 原生 FC (native)</label>
                    <label class="radio-label"><input type="radio" v-model="settings.voiceCascadeModelToolStyle" value="router" /> 意图路由 (router)</label>
                  </div>
                  <span class="form-help">原生依靠大模型 API 自身的 Function Calling 能力；路由则是根据题干意图自主判定。</span>
                </div>

                <div class="form-group">
                  <label class="form-label">级联 TTS 语音合成引擎</label>
                  <select v-model="settings.cascadeTtsType" class="form-select">
                    <option value="sherpa-vits">sherpa-vits (本地离线中文 VITS 引擎)</option>
                    <option value="edge-tts" disabled>edge-tts (微软 Edge 语音在线 - 后续支持)</option>
                  </select>
                  <span class="form-help">选择语音合成采用的引擎模型。</span>
                </div>

                <div v-if="settings.cascadeTtsType === 'sherpa-vits'" class="form-group">
                  <label class="form-label">本地 TTS 发音人 ID</label>
                  <input v-model.number="settings.localTtsSpeakerId" type="number" min="0" max="173" placeholder="请输入发音人ID (0-173)" class="form-input" />
                  <span class="form-help">AIShell3 中文离线合成引擎，支持 174 个不同的发音人音色（可选 0 ~ 173）。</span>
                </div>

                <div class="form-group">
                  <div style="display: flex; justify-content: space-between; align-items: center;">
                    <label class="form-label">离线 TTS 合成语速: {{ settings.localTtsSpeedRate }}x</label>
                  </div>
                  <input type="range" v-model.number="settings.localTtsSpeedRate" min="0.5" max="2.0" step="0.05" style="width: 100%; accent-color: #00e5ff; height: 6px; border-radius: 3px; background: rgba(255,255,255,0.1); cursor: pointer;" />
                  <span class="form-help">调节本地 VITS 合成朗读的语速（微调至 1.05~1.1x 听起来更连贯自然）。</span>
                </div>

                <!-- ASR 模型路径选择 -->
                <div class="form-group">
                  <label class="form-label">本地 ASR / 唤醒词模型目录</label>
                  <div class="select-editable-wrapper">
                    <select v-model="settings.modelDir" class="form-select">
                      <option v-for="opt in kwsModelOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                      <option value="custom">-- 自定义选择文件夹 --</option>
                    </select>
                    <div class="input-with-btn custom-input" v-if="settings.modelDir === 'custom' || !kwsModelOptions.map(o => o.value).includes(settings.modelDir)">
                      <input v-model="settings.modelDir" type="text" placeholder="选择存放 ONNX 模型的文件夹" class="form-input" style="flex: 1;" />
                      <button @click.stop="pickDirectory('modelDir')">📂</button>
                    </div>
                  </div>
                  <span class="form-help">指定本地 ASR 语音识别与 KWS 语音唤醒共用的模型路径。</span>
                </div>

                <div class="form-group">
                  <label class="form-label">本地 ASR 语音识别模式</label>
                  <div class="radio-group">
                    <label class="radio-label"><input type="radio" v-model="settings.asrMode" value="streaming" /> 实时流式 (Zipformer)</label>
                    <label class="radio-label"><input type="radio" v-model="settings.asrMode" value="offline" /> 情绪识别非流式 (SenseVoice)</label>
                  </div>
                  <span class="form-help">流式边说边识别；非流式在说话完毕后整体识别，支持中/英/日/韩/粤和情绪识别。</span>
                </div>

                <div class="form-group">
                  <div style="display: flex; justify-content: space-between; align-items: center;">
                    <label class="form-label">级联 VAD 静音断句判定时长: {{ settings.cascadeSilenceDurationMs }}ms</label>
                  </div>
                  <input type="range" v-model.number="settings.cascadeSilenceDurationMs" min="500" max="3000" step="100" style="width: 100%; accent-color: #00e5ff; height: 6px; border-radius: 3px; background: rgba(255,255,255,0.1); cursor: pointer;" />
                  <span class="form-help">说话停止多少毫秒后自动判定您说话完毕并开始回应。</span>
                </div>

                <div class="form-group">
                  <div style="display: flex; justify-content: space-between; align-items: center;">
                    <label class="form-label">本地 ASR 拾音能量门限: {{ settings.cascadeVadEnergyThreshold }}</label>
                  </div>
                  <input type="range" v-model.number="settings.cascadeVadEnergyThreshold" min="0.005" max="0.100" step="0.005" style="width: 100%; accent-color: #00e5ff; height: 6px; border-radius: 3px; background: rgba(255,255,255,0.1); cursor: pointer;" />
                  <span class="form-help">过滤环境底噪的能量阈值。如果所处环境嘈杂导致小安不断采集杂音，可往大调；若说话太轻不识别，可往小调。</span>
                </div>
              </template>


            </fieldset>
          </div>
        </div>
      </div>

      <div class="modal-actions settings-dialog-actions">
        <button class="btn-cancel" @click="closeSettingsWindow">退出</button>
        <button class="btn-save" @click="saveSettings">保存配置</button>
      </div>
    </div>
  </div>

  <div v-else class="app-root">
    <!-- 动态背景 -->
    <div class="bg-mesh" aria-hidden="true">
      <div class="orb orb-1"></div>
      <div class="orb orb-2"></div>
    </div>

    <!-- 顶部工具栏 -->
    <header class="toolbar">
      <div class="toolbar-brand">
        <div class="brand-logo">
          <img src="./assets/avatar.png" alt="小安" class="girl-logo-img" />
        </div>
        <span class="brand-name">小安</span>
      </div>
      <!-- 状态仪表盘面板（完全对齐设计图参数标贴排布） -->
      <div class="status-dashboard">
        <!-- 后端连接状态 -->
        <div class="status-pill backend-pill" :class="backendOnline ? 'on' : 'off'" :title="backendOnline ? '后端服务在线' : '后端服务离线，正在尝试连接...'">
          <span class="pill-dot"></span>
          <span class="pill-text">后端 {{ backendOnline ? 'ON' : 'OFF' }}</span>
        </div>
        
        <!-- 麦克风设备状态 -->
        <div class="status-pill mic-pill" :class="micDisabled ? 'error' : 'ok'" :title="micDisabled ? '麦克风异常或被禁用' : '麦克风工作正常'">
          <span class="pill-dot"></span>
          <span class="pill-text">麦克风 {{ micDisabled ? 'OFF' : 'ON' }}</span>
        </div>
        
        <!-- 扬声器播放状态 -->
        <div class="status-pill speaker-pill" :class="isPlaying ? 'active' : 'ok'" :title="isPlaying ? '语音扬声器正在输出音频' : '扬声器就绪'">
          <span class="pill-dot"></span>
          <span class="pill-text">扬声器 {{ isPlaying ? 'PLAY' : 'ON' }}</span>
        </div>
      </div>
      <div class="toolbar-actions">
        <WakeWordIndicator
          ref="wakeIndicatorEl"
          :keyword="settings.wakeWord"
          :model-path="settings.modelDir"
          :in-call="inCall"
          :is-playing="isPlaying"
          :is-thinking="isThinking"
          :is-user-speaking="isUserSpeaking"
          :kws-max-active-paths="settings.kwsMaxActivePaths"
          :kws-num-trailing-blanks="settings.kwsNumTrailingBlanks"
          :kws-score="settings.kwsScore"
          :kws-threshold="settings.kwsThreshold"
          @wake="onWakeDetected"
          @mic-error="onMicError"
          @mic-recovered="onMicRecovered"
          @debug="onKwsDebug"
          @stop-call="endVoiceCall"
        />
        <button class="icon-btn" @click="openSettingsWindow" title="设置">⚙️</button>
        <button v-if="messages.length > 0" class="icon-btn btn-clear" @click="clearChat" title="清空对话历史">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="trash-svg" style="width: 15px; height: 15px;">
            <g class="trash-lid">
              <line x1="3" y1="6" x2="21" y2="6"></line>
              <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
            </g>
            <g class="trash-can">
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"></path>
              <line x1="10" y1="11" x2="10" y2="17"></line>
              <line x1="14" y1="11" x2="14" y2="17"></line>
            </g>
          </svg>
        </button>
      </div>
    </header>

    <!-- 主内容区 -->
    <main class="main-area">
      <!-- 左/主：对话区 -->
      <section class="chat-section">
        <div class="messages" ref="messagesEl">
          <!-- 极简内嵌空状态提示 -->
          <div v-if="messages.length === 0" class="empty-chat-placeholder">
            <div class="empty-icon">
              <img src="./assets/avatar.png" alt="小安" class="girl-placeholder-img" />
            </div>
            <h2 class="empty-title">您好，我是小安，您的气象语音助手</h2>
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
            :is-final="msg.isFinal !== false"
          />
        </div>

        <!-- 天气卡片（天气意图时插入） -->
        <Transition name="slide-up">
          <WeatherCard
            v-if="weatherData && settings.showWeatherCard"
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
              :placeholder="`输入消息，或说&quot;小安小安&quot;唤醒…`"
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

      <!-- 侧边折叠拉手按钮 -->
      <button 
        class="collapse-handle" 
        :class="{ 'is-collapsed': !showDebugPanel }"
        @click="showDebugPanel = !showDebugPanel" 
        :title="showDebugPanel ? '收起面板' : '展开面板'"
      >
        <span>{{ showDebugPanel ? '❯' : '❮' }}</span>
      </button>

      <!-- 右侧：全链路调试控制台 -->
      <aside class="debug-panel" :class="{ 'is-collapsed': !showDebugPanel }">
        <div class="debug-inner">
          <div class="debug-header">
            <h3>🛠️ 全链路调试控制台</h3>
            <button class="btn-clear-debug" @click="clearDebugLogs" title="清空日志">🗑️</button>
          </div>
          <div class="debug-content" ref="debugContentEl">
            <div v-if="debugLogs.length === 0" class="debug-empty">
              等待语音交互启动以捕获链路事件...
            </div>
            <div v-else class="debug-timeline">
              <div 
                v-for="(log, idx) in debugLogs" 
                :key="idx" 
                class="debug-item" 
                :class="log.step"
              >
                <div class="debug-item-header" @click="toggleLogDetail(idx)">
                  <span class="debug-tag">{{ getStepLabel(log.step) }}</span>
                  <span class="debug-time">{{ formatTime(log.timestamp) }}</span>
                  <span class="debug-toggle" v-if="hasDetail(log)">{{ log.collapsed ? '▶' : '▼' }}</span>
                </div>
                <div class="debug-item-body">
                  <div v-if="log.step === 'stt'" class="debug-text-content">
                    识别文本: "{{ log.content }}"
                  </div>
                  <div v-else-if="log.step === 'intent'" class="debug-text-content">
                    {{ log.content }}
                  </div>
                  <div v-else-if="log.step === 'tts'" class="debug-text-content">
                    语音回复: "{{ log.content }}"
                  </div>
                  <div v-else-if="log.step === 'tool_call'" class="debug-json-content" v-show="!log.collapsed">
                    <div class="debug-meta">工具名: <code>{{ log.name }}</code></div>
                    <pre><code>{{ formatJson(log.arguments) }}</code></pre>
                  </div>
                  <div v-else-if="log.step === 'tool_result'" class="debug-json-content" v-show="!log.collapsed">
                    <div class="debug-meta">工具名: <code>{{ log.name }}</code></div>
                    <pre><code>{{ formatJson(log.result) }}</code></pre>
                  </div>
                  <div v-else-if="log.step === 'control'" class="debug-json-content" v-show="!log.collapsed">
                    <div class="debug-meta">指令内容: <code>{{ log.content }}</code></div>
                    <pre><code>{{ formatJson(log.arguments) }}</code></pre>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </aside>
    </main>

    <!-- 设置弹窗 -->
    <Transition name="fade">
      <div v-if="showSettings" class="modal-overlay" @click.self="closeSettingsWindow">
        <div class="modal settings-dialog">
          <div class="settings-header">
            <h3>⚙️ 控制面板设置</h3>
            <button class="btn-close-modal" @click="closeSettingsWindow">✕</button>
          </div>
          <div class="settings-container">
            <!-- 左侧导航 -->
            <nav class="settings-sidebar">
              <button class="tab-btn" :class="{ active: activeTab === 'general' }" @click="activeTab = 'general'">
                <span class="tab-icon">🌐</span> 通用设置
              </button>
              <button class="tab-btn" :class="{ active: activeTab === 'kws' }" @click="activeTab = 'kws'">
                <span class="tab-icon">🎙️</span> 语音唤醒
              </button>
              <button class="tab-btn" :class="{ active: activeTab === 'llm' }" @click="activeTab = 'llm'">
                <span class="tab-icon">🤖</span> 模型设置
              </button>
            </nav>
            
            <!-- 右侧面板 -->
            <div class="settings-content">
              <!-- Tab 1: 通用设置 -->
              <div v-show="activeTab === 'general'" class="tab-panel">
                <div class="form-group">
                  <label class="form-label">后端服务地址</label>
                  <input v-model="settings.backendUrl" type="text" class="form-input" placeholder="http://127.0.0.1:10850" />
                  <span class="form-help">FastAPI 后端服务的本地监听地址。</span>
                </div>
                <div class="form-group">
                  <label class="form-label">默认聚焦城市</label>
                  <input v-model="settings.defaultCity" type="text" class="form-input" placeholder="成都" />
                  <span class="form-help">当对话中未显式提及城市名时的天气聚焦城市。</span>
                </div>
                <div class="form-group" style="margin-top: 10px;">
                  <label class="form-label" style="font-weight: 600; color: #60a5fa;">大屏视觉端类别 (Visual Terminal UI)</label>
                  <select v-model="settings.visualTerminal" class="form-select">
                    <option value="demo_ui">demo_ui</option>
                    <option value="app_ui">app_ui</option>
                  </select>
                  <span class="form-help">控制后端通过 WebSocket 广播给大屏端的数据指令协议标准 (demo_ui / app_ui)。</span>
                </div>

                <div class="form-group checkbox-group" style="margin-top: 10px; padding: 4px 0;">
                  <div style="display: flex; align-items: center; gap: 10px;">
                    <input v-model="isStartFullscreen" type="checkbox" id="isStartFullscreenCheckbox" class="form-checkbox" @change="onStartFullscreenChange" />
                    <label for="isStartFullscreenCheckbox" class="checkbox-title">前端启动时全屏</label>
                  </div>
                  <span class="form-help" style="margin-left: 26px;">开启后，前端应用启动时主窗口将自动进入全屏显示。</span>
                </div>
                <div class="form-group checkbox-group" style="margin-top: 10px; padding: 4px 0;">
                  <div style="display: flex; align-items: center; gap: 10px;">
                    <input v-model="settings.enableVisualBroadcast" type="checkbox" id="enableVisualBroadcast" class="form-checkbox" />
                    <label for="enableVisualBroadcast" class="checkbox-title">开启大屏视觉端同步广播</label>
                  </div>
                  <p class="checkbox-desc">
                    开启后，交互控制指令会通过独立的 WebSocket 管道广播投递给大屏端，进行无缝视觉联动。
                  </p>
                </div>
                <div class="form-group checkbox-group" style="margin-top: 10px; padding: 4px 0;">
                  <div style="display: flex; align-items: center; gap: 10px;">
                    <input v-model="settings.showWeatherCard" type="checkbox" id="showWeatherCard" class="form-checkbox" />
                    <label for="showWeatherCard" class="checkbox-title">展示天气卡片</label>
                  </div>
                  <span class="form-help" style="margin-left: 26px;">关闭后，天气信息将不再弹出可视化卡片，仅保留语音和文字回复。</span>
                </div>
                <div class="form-group" style="margin-top: 14px;">
                  <label class="form-label">控制台日志显示等级</label>
                  <select v-model="settings.logLevel" class="form-select">
                    <option value="DEBUG">DEBUG (详细调试)</option>
                    <option value="INFO">INFO (标准信息)</option>
                    <option value="WARNING">WARNING (仅警告与错误)</option>
                    <option value="ERROR">ERROR (仅严重错误)</option>
                  </select>
                  <span class="form-help">控制终端控制台中实时的日志打印级别。</span>
                </div>
                <div class="form-group">
                  <label class="form-label">磁盘日志保存等级</label>
                  <select v-model="settings.logFileLevel" class="form-select">
                    <option value="DEBUG">DEBUG (全部记录)</option>
                    <option value="INFO">INFO (标准记录)</option>
                    <option value="WARNING">WARNING (仅警告与错误)</option>
                    <option value="ERROR">ERROR (仅严重错误)</option>
                  </select>
                  <span class="form-help">写入 logs/backend/backend.log 磁盘文件的日志保留级别。</span>
                </div>
                <div class="form-group">
                  <label class="form-label">无对话超时挂断时间（秒）</label>
                  <input v-model.number="settings.sessionIdleTimeoutSec" type="number" class="form-input" placeholder="30" min="0" />
                  <span class="form-help">静默无对话自动关停通话的时间（单位：秒，设为 0 代表禁用自动超时挂断）。</span>
                </div>
              </div>

              <!-- Tab 2: 语音唤醒 -->
              <div v-show="activeTab === 'kws'" class="tab-panel">
                <div class="form-group">
                  <label class="form-label">Sherpa-Onnx 唤醒词模型</label>
                  <div class="select-editable-wrapper">
                    <select v-model="settings.modelDir" class="form-select">
                      <option v-for="opt in kwsModelOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                      <option value="custom">-- 自定义选择文件夹 --</option>
                    </select>
                    <div class="input-with-btn custom-input" v-if="settings.modelDir === 'custom' || !kwsModelOptions.map(o => o.value).includes(settings.modelDir)">
                      <input v-model="settings.modelDir" type="text" placeholder="选择存放 ONNX 模型的文件夹" class="form-input" style="flex: 1;" />
                      <button @click.stop="pickDirectory('modelDir')">📂</button>
                    </div>
                  </div>
                  <span class="form-help">支持切换 WenetSpeech 中文模型或 ZH-EN 双语模型。</span>
                </div>
                <div class="form-group">
                  <label class="form-label">本地侦听唤醒词</label>
                  <textarea 
                    v-model="settings.wakeWord" 
                    placeholder="输入唤醒词，如：&#10;小安小安&#10;你好军哥&#10;（每行一个）" 
                    class="form-input wake-word-textarea" 
                    rows="12" 
                  ></textarea>
                  <span class="form-help">支持输入纯中文（每行一个，自动转拼音），或直接输入带有阈值的拼音微调行（如 <code>x iǎo ān x iǎo ān :3.0 #0.08 @小安小安</code>）。系统会自动保存并同步模型目录下的 <code>keywords.txt</code>。</span>
                </div>

                <!-- KWS 引擎高级参数 -->
                <fieldset class="settings-fieldset">
                  <legend class="fieldset-legend">⚙️ KWS 引擎参数</legend>
                  <span class="form-help" style="display:block;margin-bottom:10px;">调整唤醒灵敏度与精度。<code>keywords.txt</code> 中的逐行 <code>:score</code>/<code>#threshold</code> 会覆盖下方全局值。</span>

                  <div class="form-group">
                    <div style="display:flex;justify-content:space-between;align-items:center;">
                      <label class="form-label">全局 boosting 分数 (keywords_score): {{ settings.kwsScore }}</label>
                    </div>
                    <input type="range" v-model.number="settings.kwsScore" min="0.5" max="5.0" step="0.1"
                      style="width:100%;accent-color:#00e5ff;height:6px;border-radius:3px;background:rgba(255,255,255,0.1);cursor:pointer;" />
                    <span class="form-help">越大越容易触发（提高召回率）；越小越保守（减少误触）。推荐 1.0–2.0，默认 1.5。</span>
                  </div>

                  <div class="form-group">
                    <div style="display:flex;justify-content:space-between;align-items:center;">
                      <label class="form-label">全局触发阈值 (keywords_threshold): {{ settings.kwsThreshold }}</label>
                    </div>
                    <input type="range" v-model.number="settings.kwsThreshold" min="0.01" max="0.5" step="0.01"
                      style="width:100%;accent-color:#00e5ff;height:6px;border-radius:3px;background:rgba(255,255,255,0.1);cursor:pointer;" />
                    <span class="form-help">越小越灵敏（更容易唤醒）；越大越严格（需要更清晰发音）。推荐 0.1–0.3，默认 0.25。</span>
                  </div>

                  <div class="form-group">
                    <label class="form-label">Beam Search 宽度 (max_active_paths)</label>
                    <select v-model.number="settings.kwsMaxActivePaths" class="form-select">
                      <option :value="2">2 — 最快，精度略低</option>
                      <option :value="4">4 — 平衡（推荐）</option>
                      <option :value="8">8 — 较慢，精度更高</option>
                    </select>
                    <span class="form-help">Beam search 搜索宽度，值越大精度越高但 CPU 开销越大。</span>
                  </div>

                  <div class="form-group">
                    <label class="form-label">尾部空白帧 (num_trailing_blanks)</label>
                    <select v-model.number="settings.kwsNumTrailingBlanks" class="form-select">
                      <option :value="1">1 — 默认</option>
                      <option :value="2">2 — 减少截断误判</option>
                      <option :value="0">0 — 最快响应</option>
                    </select>
                    <span class="form-help">关键词结束后等待的空白帧数，越大延迟越高但误判越少。</span>
                  </div>
                </fieldset>
              </div>

              <!-- Tab 3: 模型设置 -->
              <div v-show="activeTab === 'llm'" class="tab-panel scrollable-panel">
                <!-- 文字对话模型 -->
                <fieldset class="settings-fieldset">
                  <legend class="fieldset-legend">📝 文字对话模型</legend>
                  <div class="form-group">
                    <label class="form-label">* 文字对话大模型</label>
                    <div class="select-editable-wrapper">
                      <select v-model="settings.textModelName" class="form-select">
                        <option v-for="opt in textModelOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                        <option value="custom">-- 自定义输入 --</option>
                      </select>
                      <input 
                        v-if="settings.textModelName === 'custom' || !textModelOptions.map(o => o.value).includes(settings.textModelName)"
                        v-model="settings.textModelName" 
                        type="text" 
                        placeholder="请输入自定义文字模型名" 
                        class="form-input custom-input" 
                      />
                    </div>
                    <span class="form-help">用于键盘打字聊天的推理大脑，以及语音级联模式下的文本生成核心。</span>
                  </div>
                  <div class="form-group">
                    <label class="form-label">工具调用执行模式</label>
                    <div class="radio-group">
                      <label class="radio-label"><input type="radio" v-model="settings.textModelToolMode" value="parallel" /> 并行 (parallel)</label>
                      <label class="radio-label"><input type="radio" v-model="settings.textModelToolMode" value="serial" /> 串行 (serial)</label>
                    </div>
                    <span class="form-help">控制文字对话执行工具是并发或串行排队。</span>
                  </div>
                  <div class="form-group">
                    <label class="form-label">工具触发提取风格</label>
                    <div class="radio-group">
                      <label class="radio-label"><input type="radio" v-model="settings.textModelToolStyle" value="native" /> 原生 FC (native)</label>
                      <label class="radio-label"><input type="radio" v-model="settings.textModelToolStyle" value="router" /> 意图路由 (router)</label>
                    </div>
                    <span class="form-help">原生依靠大模型 API 自身的 Function Calling 能力；路由则是根据题干意图自主判定。</span>
                  </div>
                </fieldset>

                <!-- 语音对话模型 -->
                <fieldset class="settings-fieldset">
                  <legend class="fieldset-legend">🔊 语音对话模型</legend>
                  
                  <div class="form-group">
                    <label class="form-label">语音通话架构模式选择</label>
                    <div class="radio-group">
                      <label class="radio-label">
                        <input type="radio" v-model="settings.voiceInteractionStyle" value="e2e" /> 端到端模式 (Voice-to-Voice)
                      </label>
                      <label class="radio-label">
                        <input type="radio" v-model="settings.voiceInteractionStyle" value="cascade" /> 级联模式 (ASR + LLM + TTS)
                      </label>
                    </div>
                    <span class="form-help">端到端模式提供低延迟、带语气情感和呼吸声的云端对话；级联模式则将识别、大模型与合成切分，支持高度定制和完全单机离线。</span>
                  </div>

                  <!-- A: 端到端模式配置 -->
                  <template v-if="settings.voiceInteractionStyle === 'e2e'">
                    <div class="form-group">
                      <label class="form-label">* 端到端实时语音模型名</label>
                      <div class="select-editable-wrapper">
                        <select v-model="settings.voiceModelName" class="form-select">
                          <option v-for="opt in voiceModelOptions.filter(o => o.value !== 'sherpa-local')" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                          <option value="custom">-- 自定义输入 --</option>
                        </select>
                        <input 
                          v-if="settings.voiceModelName === 'custom' || (!voiceModelOptions.map(o => o.value).includes(settings.voiceModelName) && settings.voiceModelName !== 'sherpa-local')"
                          v-model="settings.voiceModelName" 
                          type="text" 
                          placeholder="请输入自定义端到端模型名" 
                          class="form-input custom-input" 
                        />
                      </div>
                    </div>

                    <div class="form-group">
                      <label class="form-label">语音通话实时音色</label>
                      <select v-model="settings.voice" class="form-select">
                        <option v-for="opt in voiceOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                      </select>
                      <span class="form-help">实时通话发音音色，保存后系统会自动使用该音色重新生成唤醒响应提示音。</span>
                    </div>

                    <!-- 科大讯飞超拟人专属配置项 -->
                    <template v-if="settings.voiceModelName === 'xunfei-realtime'">
                      <div class="form-group">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                          <label class="form-label">超拟人合成语速: {{ settings.voiceSpeed }}</label>
                        </div>
                        <input type="range" v-model.number="settings.voiceSpeed" min="0" max="100" step="1" style="width: 100%; accent-color: #00e5ff; height: 6px; border-radius: 3px; background: rgba(255,255,255,0.1); cursor: pointer;" />
                        <span class="form-help">控制科大讯飞大模型超拟人发音合成的速度（取值 0-100，默认 50，数值越小越慢，越大越快）。</span>
                      </div>
                    </template>

                    <div class="form-group">
                      <div style="display: flex; justify-content: space-between; align-items: center;">
                        <label class="form-label">采样温度 (Temperature): {{ settings.e2eTemperature }}</label>
                      </div>
                      <input type="range" v-model.number="settings.e2eTemperature" min="0.0" max="2.0" step="0.1" style="width: 100%; accent-color: #00e5ff; height: 6px; border-radius: 3px; background: rgba(255,255,255,0.1); cursor: pointer;" />
                      <span class="form-help">控制语音应答的语气随机性与词汇创造力。</span>
                    </div>

                    <div class="form-group">
                      <label class="form-label">最大输出 Token 数</label>
                      <input type="number" v-model.number="settings.e2eMaxTokens" min="1" max="4096" class="form-input" />
                      <span class="form-help">限制单次回答的最大长度，防止大模型发生长篇大论。</span>
                    </div>

                    <div class="form-group">
                      <div style="display: flex; justify-content: space-between; align-items: center;">
                        <label class="form-label">VAD 静音断句判定时长: {{ settings.e2eSilenceDurationMs }}ms</label>
                      </div>
                      <input type="range" v-model.number="settings.e2eSilenceDurationMs" min="300" max="2000" step="50" style="width: 100%; accent-color: #00e5ff; height: 6px; border-radius: 3px; background: rgba(255,255,255,0.1); cursor: pointer;" />
                      <span class="form-help">静音多少毫秒后自动判定您说话结束并开始回应（越短反应越敏捷，防插嘴可调长）。</span>
                    </div>
                    
                    <!-- Qwen-Audio 3.0 Realtime 专属配置块 -->
                    <template v-if="settings.voiceModelName === 'qwen-audio-3.0-realtime-plus' || settings.voiceModelName === 'qwen-audio-3.0-realtime-flash'">
                      <fieldset class="settings-fieldset" style="margin-top: 15px; border-color: rgba(0, 229, 255, 0.2); padding: 15px; border-radius: 8px; border-style: solid; border-width: 1px;">
                        <legend class="fieldset-legend" style="color: #00e5ff; padding: 0 10px; font-weight: 600;">🎙️ Qwen-Audio 专属配置</legend>
                        
                        <!-- 实时语音识别流式推送开关 -->
                        <div class="form-group" style="display: flex; justify-content: space-between; align-items: center; background: rgba(0, 229, 255, 0.04); border: 1px solid rgba(0, 229, 255, 0.12); border-radius: 8px; padding: 10px 14px; margin-bottom: 15px;">
                          <div>
                            <label class="form-label" style="margin-bottom: 2px; font-weight: 600; color: #00e5ff;">⚡ 实时语音识别流式推送 (ASR Stream Push)</label>
                            <span class="form-help" style="margin: 0; font-size: 0.76rem;">
                              {{ settings.streamAsrEnabled ? '开启后：说话时同步实时流式展示文本片段 (推荐)' : '关闭后：完整说完一整句话后统一展示识别结果' }}
                            </span>
                          </div>
                          <label class="switch-toggle" style="position: relative; display: inline-block; width: 44px; height: 24px; flex-shrink: 0; margin-left: 12px;">
                            <input type="checkbox" v-model="settings.streamAsrEnabled" style="opacity: 0; width: 0; height: 0;" />
                            <span class="slider" :style="{
                              position: 'absolute', cursor: 'pointer', top: 0, left: 0, right: 0, bottom: 0,
                              backgroundColor: settings.streamAsrEnabled ? '#00e5ff' : 'rgba(255,255,255,0.2)',
                              transition: '.3s', borderRadius: '24px', boxShadow: settings.streamAsrEnabled ? '0 0 10px rgba(0,229,255,0.5)' : 'none'
                            }">
                              <span :style="{
                                position: 'absolute', height: '18px', width: '18px', left: '3px', bottom: '3px',
                                backgroundColor: '#fff', transition: '.3s', borderRadius: '50%',
                                transform: settings.streamAsrEnabled ? 'translateX(20px)' : 'translateX(0)'
                              }"></span>
                            </span>
                          </label>
                        </div>

                        <div class="form-group">
                          <label class="form-label">历史对话参考轮数限制</label>
                          <input type="number" v-model.number="settings.qwenAudioMaxHistoryTurns" min="1" max="50" class="form-input" />
                          <span class="form-help">模型参考的多轮对话历史 QA 轮数，取值范围 1-50，默认 20。较小值有利于减少回复延迟。</span>
                        </div>

                        <div class="form-group">
                          <label class="form-label">对话交互轮次检测模式</label>
                          <select v-model="settings.qwenAudioTurnMode" class="form-select" :disabled="settings.qwenAudioVoiceprintMode === 'static'">
                            <option value="server_vad">server_vad (声学 VAD 自动检测)</option>
                            <option value="smart_turn">smart_turn (智能语义轮次 - 推荐)</option>
                            <option value="push_to_talk">push_to_talk (手动控制 / 手动提交)</option>
                          </select>
                          <span class="form-help">控制何时触发 AI 的回应。当启用静态声纹锁定时，系统将强制锁定为 <code>smart_turn</code> 模式。</span>
                        </div>

                        <!-- 声纹锁定模式选择 -->
                        <div class="form-group">
                          <label class="form-label">声纹锁定</label>
                          <select v-model="settings.qwenAudioVoiceprintMode" class="form-select">
                            <option value="none">无锁定 (不限制发言人)</option>
                            <option value="dynamic">自动锁定首位说话人 (首轮通话录音并动态锁定)</option>
                            <option value="static">绑定已有静态声纹 (精准锁定录制好的声纹特征)</option>
                          </select>
                          <span class="form-help">智能语义轮次专用：提取发音人声音特征以过滤旁人干扰。</span>
                        </div>

                        <!-- A. 静态声纹：组合在同一行的两级下拉框与控制按钮 -->
                        <div class="form-group" v-if="settings.qwenAudioVoiceprintMode === 'static'">
                          <label class="form-label" style="display: flex; justify-content: space-between; align-items: center;">
                            <span>选择绑定的已有声纹角色与具体采样</span>
                            <span style="font-size: 0.75rem; color: #00e5ff;" v-if="settings.selectedVoiceprintId && selectedRoleSamples.length > 0">
                              (已选角色共 {{ selectedRoleSamples.length }}/5 段采样)
                            </span>
                          </label>
                          
                          <div style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center;">
                            <!-- 1. 选择声纹角色下拉框 -->
                            <select v-model="settings.selectedVoiceprintId" class="form-select" style="flex: 1; min-width: 140px; height: 38px;">
                              <option value="">-- 请选择声纹角色 --</option>
                              <option v-for="vp in voiceprints" :key="vp.id" :value="vp.id">
                                {{ vp.name }} ({{ vp.sample_count || 1 }}/5 段)
                              </option>
                            </select>

                            <!-- 2. 右侧对应角色的声纹音频文件列表下拉框 -->
                            <select 
                              v-if="settings.selectedVoiceprintId && selectedRoleSamples.length > 0" 
                              v-model="selectedSampleId" 
                              class="form-select" 
                              style="flex: 1.3; min-width: 160px; height: 38px; font-size: 0.8rem;"
                            >
                              <option v-for="(sample, idx) in selectedRoleSamples" :key="sample.id || idx" :value="sample.id">
                                {{ sample.created_at || sample.filename }} {{ idx === 0 ? ' (最新采样 ★)' : '' }}
                              </option>
                            </select>

                            <!-- 3. 精准删除选中采样按钮 -->
                            <button 
                              type="button" 
                              v-if="selectedSampleId" 
                              @click="deleteSingleVoiceprintSample(selectedSampleId)" 
                              class="btn-micro" 
                              style="background: rgba(255, 77, 79, 0.15); border: 1px solid rgba(255, 77, 79, 0.4); color: #ff4d4f; width: auto; padding: 0 10px; height: 38px; border-radius: 8px; font-size: 0.78rem; white-space: nowrap;" 
                              title="删除下拉框中选中的具体音频文件"
                            >
                              🗑️ 删除采样
                            </button>

                            <!-- 4. 删除整个角色按钮 -->
                            <button 
                              type="button" 
                              v-if="settings.selectedVoiceprintId" 
                              @click="deleteVoiceprintRole(settings.selectedVoiceprintId)" 
                              class="btn-micro" 
                              style="background: rgba(255, 77, 79, 0.12); border: 1px solid rgba(255, 77, 79, 0.3); color: #ff4d4f; width: auto; padding: 0 8px; height: 38px; border-radius: 8px; font-size: 0.78rem; white-space: nowrap;" 
                              title="删除选中的整个声纹角色及其所有采样"
                            >
                              🗑️ 清空角色
                            </button>

                            <!-- 5. 录制新声纹按钮 -->
                            <button type="button" @click="startRecordVoiceprintFlow" class="btn-micro start" style="width: auto; padding: 0 14px; white-space: nowrap; height: 38px; border-radius: 8px;">
                              🎙️ 录制新声纹
                            </button>
                          </div>

                          <span class="form-help" v-if="voiceprints.length === 0" style="color: #ff4d4f;">⚠️ 暂无可用声纹角色，请点击右侧按钮录制并创建角色。</span>
                        </div>




                        <!-- B. 动态声纹：提示文字 -->
                        <div class="form-group" v-if="settings.qwenAudioVoiceprintMode === 'dynamic'" style="background: rgba(0, 229, 255, 0.05); border: 1px solid rgba(0, 229, 255, 0.15); border-radius: 8px; padding: 12px; margin-bottom: 12px;">
                          <span class="form-help" style="color: #00e5ff; margin: 0; font-size: 0.8rem; line-height: 1.5;">
                            ℹ️ <strong>自动首句锁定</strong>：通话开始的第一回合，系统会以常规模式捕获您的声音并保存，第二回合起自动锁定您的声纹，旁人或嘈杂的背景人声将不会打断对话。
                          </span>
                        </div>

                        <!-- C. 无锁定：兼容旧的手填 URLs 功能 -->
                        <div class="form-group" v-if="settings.qwenAudioVoiceprintMode === 'none'">
                          <label class="form-label">锁定说话人预录音频 URLs (兼容项)</label>
                          <textarea 
                            v-model="settings.qwenAudioVoiceprintAudioUrls" 
                            placeholder="请输入目标用户的预录音频公网 URL&#10;支持多个，每行输入一个&#10;格式支持 16kHz PCM 或 WAV" 
                            class="form-input" 
                            rows="3" 
                          ></textarea>
                          <span class="form-help">如果不使用上述自动模式，您仍可以在此手动填入多行参考音频公网链接来完成声纹配置。</span>
                        </div>

                        <!-- D. server_vad 专属配置项：VAD 灵敏度阈值 -->
                        <div class="form-group" v-if="settings.qwenAudioTurnMode === 'server_vad' && settings.qwenAudioVoiceprintMode !== 'static'">
                          <div style="display: flex; justify-content: space-between; align-items: center;">
                            <label class="form-label">VAD 灵敏度阈值 (threshold): {{ settings.qwenAudioVadThreshold }}</label>
                          </div>
                          <input type="range" v-model.number="settings.qwenAudioVadThreshold" min="-1.0" max="1.0" step="0.05" style="width: 100%; accent-color: #00e5ff; height: 6px; border-radius: 3px; background: rgba(255,255,255,0.1); cursor: pointer;" />
                          <span class="form-help">声学VAD判定灵敏度，值越小越灵敏越容易触发，值越大越严格。范围 [-1.0, 1.0]，默认 0.5。</span>
                        </div>
                      </fieldset>
                    </template>
                  </template>

                  <!-- B: 级联模式配置 -->
                  <template v-else-if="settings.voiceInteractionStyle === 'cascade'">
                    <div class="form-group">
                      <label class="form-label">* 级联语音对话大模型</label>
                      <div class="select-editable-wrapper">
                        <select v-model="settings.voiceCascadeModelName" class="form-select">
                          <option v-for="opt in textModelOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                          <option value="custom">-- 自定义输入 --</option>
                        </select>
                        <input 
                          v-if="settings.voiceCascadeModelName === 'custom' || !textModelOptions.map(o => o.value).includes(settings.voiceCascadeModelName)"
                          v-model="settings.voiceCascadeModelName" 
                          type="text" 
                          placeholder="请输入自定义级联大脑模型名" 
                          class="form-input custom-input" 
                        />
                      </div>
                      <span class="form-help">此大模型将作为您在本地级联语音通话时的推理脑。</span>
                    </div>

                    <div class="form-group">
                      <label class="form-label">级联大脑工具调用执行模式</label>
                      <div class="radio-group">
                        <label class="radio-label"><input type="radio" v-model="settings.voiceCascadeModelToolMode" value="parallel" /> 并行 (parallel)</label>
                        <label class="radio-label"><input type="radio" v-model="settings.voiceCascadeModelToolMode" value="serial" /> 串行 (serial)</label>
                      </div>
                      <span class="form-help">控制级联语音大模型执行工具是并发或是串行排队。</span>
                    </div>

                    <div class="form-group">
                      <label class="form-label">级联大脑工具触发提取风格</label>
                      <div class="radio-group">
                        <label class="radio-label"><input type="radio" v-model="settings.voiceCascadeModelToolStyle" value="native" /> 原生 FC (native)</label>
                        <label class="radio-label"><input type="radio" v-model="settings.voiceCascadeModelToolStyle" value="router" /> 意图路由 (router)</label>
                      </div>
                      <span class="form-help">原生依靠大模型 API 自身的 Function Calling 能力；路由则是根据题干意图自主判定。</span>
                    </div>

                    <div class="form-group">
                      <label class="form-label">级联 TTS 语音合成引擎</label>
                      <select v-model="settings.cascadeTtsType" class="form-select">
                        <option value="sherpa-vits">sherpa-vits (本地离线中文 VITS 引擎)</option>
                        <option value="edge-tts" disabled>edge-tts (微软 Edge 语音在线 - 后续支持)</option>
                      </select>
                      <span class="form-help">选择语音合成采用的引擎模型。</span>
                    </div>

                    <div v-if="settings.cascadeTtsType === 'sherpa-vits'" class="form-group">
                      <label class="form-label">本地 TTS 发音人 ID</label>
                      <input v-model.number="settings.localTtsSpeakerId" type="number" min="0" max="173" placeholder="请输入发音人ID (0-173)" class="form-input" />
                      <span class="form-help">AIShell3 中文离线合成引擎，支持 174 个不同的发音人音色（可选 0 ~ 173）。</span>
                    </div>

                    <div class="form-group">
                      <div style="display: flex; justify-content: space-between; align-items: center;">
                        <label class="form-label">离线 TTS 合成语速: {{ settings.localTtsSpeedRate }}x</label>
                      </div>
                      <input type="range" v-model.number="settings.localTtsSpeedRate" min="0.5" max="2.0" step="0.05" style="width: 100%; accent-color: #00e5ff; height: 6px; border-radius: 3px; background: rgba(255,255,255,0.1); cursor: pointer;" />
                      <span class="form-help">调节本地 VITS 合成朗读的语速（微调至 1.05~1.1x 听起来更连贯自然）。</span>
                    </div>

                    <!-- ASR 模型路径选择 -->
                    <div class="form-group">
                      <label class="form-label">本地 ASR / 唤醒词模型目录</label>
                      <div class="select-editable-wrapper">
                        <select v-model="settings.modelDir" class="form-select">
                          <option v-for="opt in kwsModelOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                          <option value="custom">-- 自定义选择文件夹 --</option>
                        </select>
                        <div class="input-with-btn custom-input" v-if="settings.modelDir === 'custom' || !kwsModelOptions.map(o => o.value).includes(settings.modelDir)">
                          <input v-model="settings.modelDir" type="text" placeholder="选择存放 ONNX 模型的文件夹" class="form-input" style="flex: 1;" />
                          <button @click.stop="pickDirectory('modelDir')">📂</button>
                        </div>
                      </div>
                      <span class="form-help">指定本地 ASR 语音识别与 KWS 语音唤醒共用的模型路径。</span>
                    </div>

                    <div class="form-group">
                      <label class="form-label">本地 ASR 语音识别模式</label>
                      <div class="radio-group">
                        <label class="radio-label"><input type="radio" v-model="settings.asrMode" value="streaming" /> 实时流式 (Zipformer)</label>
                        <label class="radio-label"><input type="radio" v-model="settings.asrMode" value="offline" /> 情绪识别非流式 (SenseVoice)</label>
                      </div>
                      <span class="form-help">流式边说边识别；非流式在说话完毕后整体识别，支持中/英/日/韩/粤和情绪识别。</span>
                    </div>

                    <div class="form-group">
                      <div style="display: flex; justify-content: space-between; align-items: center;">
                        <label class="form-label">级联 VAD 静音断句判定时长: {{ settings.cascadeSilenceDurationMs }}ms</label>
                      </div>
                      <input type="range" v-model.number="settings.cascadeSilenceDurationMs" min="500" max="3000" step="100" style="width: 100%; accent-color: #00e5ff; height: 6px; border-radius: 3px; background: rgba(255,255,255,0.1); cursor: pointer;" />
                      <span class="form-help">说话停止多少毫秒后自动判定您说话完毕并开始回应。</span>
                    </div>

                    <div class="form-group">
                      <div style="display: flex; justify-content: space-between; align-items: center;">
                        <label class="form-label">本地 ASR 拾音能量门限: {{ settings.cascadeVadEnergyThreshold }}</label>
                      </div>
                      <input type="range" v-model.number="settings.cascadeVadEnergyThreshold" min="0.005" max="0.100" step="0.005" style="width: 100%; accent-color: #00e5ff; height: 6px; border-radius: 3px; background: rgba(255,255,255,0.1); cursor: pointer;" />
                      <span class="form-help">过滤环境底噪的能量阈值。如果所处环境嘈杂导致小安不断采集杂音，可往大调；若说话太轻不识别，可往小调。</span>
                    </div>
                  </template>


                </fieldset>
              </div>
            </div>
          </div>
          <div class="modal-actions settings-dialog-actions">
            <button class="btn-cancel" @click="closeSettingsWindow">退出</button>
            <button class="btn-save" @click="saveSettings">保存配置</button>
          </div>
        </div>
      </div>
    </Transition>

  </div>

  <!-- 🎙️ 声纹录制与采样注册模态窗（全局通用，支持独立设置窗口与主界面） -->
  <Teleport to="body">
    <Transition name="fade">
      <div class="modal-overlay" v-if="showVoiceprintRecorder" style="z-index: 9999; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); display: flex; align-items: center; justify-content: center;">
        <div class="settings-dialog" style="max-width: 480px; width: 90%; height: auto; min-height: 400px; max-height: 90vh; background: #0c101c; border: 1px solid rgba(0, 229, 255, 0.3); border-radius: 12px; display: flex; flex-direction: column; box-shadow: 0 10px 40px rgba(0,0,0,0.8);">
          <div class="settings-header">
            <h3>🎙️ 新建说话人声纹注册</h3>
            <button class="btn-close-modal" @click="cancelVpRecordingFlow">✕</button>
          </div>
          <div class="settings-body scrollable-panel" style="padding: 24px; flex: 1; display: flex; flex-direction: column; gap: 18px; overflow-y: auto;">
            
            <!-- 1. 说话人角色选择/新建区域 -->
            <div class="form-group" style="margin-bottom: 0;">
              <label class="form-label" style="font-size: 0.85rem; display: flex; justify-content: space-between; align-items: center;">
                <span>说话人角色名称 *</span>
                <span v-if="voiceprints.length > 0" style="font-size: 0.75rem; color: #00e5ff; cursor: pointer; text-decoration: underline;" @click="isCreatingNewRole = !isCreatingNewRole">
                  {{ isCreatingNewRole ? '👈 选择已有角色' : '➕ 新建新角色' }}
                </span>
              </label>

              <!-- 模式 A：选择已有角色（方便向已有角色追加采样） -->
              <select v-if="!isCreatingNewRole && voiceprints.length > 0" v-model="voiceprintName" class="form-select" style="height: 38px;" :disabled="isRecordingVoiceprint">
                <option value="">-- 请选择要追加采样的已有角色 --</option>
                <option v-for="vp in voiceprints" :key="vp.id" :value="vp.name">
                  {{ vp.name }} (已包含 {{ vp.sample_count || 1 }}/5 段采样)
                </option>
              </select>

              <!-- 模式 B：新建角色（或列表为空时） -->
              <input 
                v-else
                v-model="voiceprintName" 
                type="text" 
                placeholder="请输入新角色名称（例如：主人、张三）" 
                class="form-input" 
                style="height: 38px;"
                :disabled="isRecordingVoiceprint"
              />
              <span class="form-help">必须选择或填写角色名称后，方可开启录音。</span>
            </div>

            <!-- 当检测到所选角色采样数 >= 5 时提示即将淘汰旧记录 -->
            <div v-if="activeRoleSampleCount >= 5" style="background: rgba(255, 171, 0, 0.12); border: 1px solid rgba(255, 171, 0, 0.35); border-radius: 8px; padding: 10px 14px; font-size: 0.78rem; color: #ffab00; line-height: 1.5; display: flex; align-items: flex-start; gap: 8px;">
              <span style="font-size: 1rem;">⚠️</span>
              <div>
                <strong>采样达到上限提示</strong>：角色『<strong>{{ voiceprintName }}</strong>』当前已包含 <strong>{{ activeRoleSampleCount }}/5</strong> 段采样上限。继续录制保存将根据规则<strong>自动淘汰并清除最旧的 1 段采样</strong>。
              </div>
            </div>

            <!-- 2. 朗读文本提示区域 -->
            <div class="form-group" style="margin-bottom: 0;">
              <label class="form-label" style="font-size: 0.85rem; display: flex; justify-content: space-between; align-items: center;">
                <span>请用正常语速与声调朗读以下文本：</span>
                <span style="color: #00e5ff; font-weight: 500; cursor: pointer; background: rgba(0, 229, 255, 0.1); border: 1px solid rgba(0, 229, 255, 0.25); padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; transition: all 0.2s;" @click="refreshVoiceprintPromptText" :style="{ opacity: isGeneratingPromptText ? 0.5 : 1 }">
                  {{ isGeneratingPromptText ? '🔄 生成中...' : '🔀 换一组' }}
                </span>
              </label>
              <div style="background: rgba(8, 12, 20, 0.7); border: 1px solid rgba(0, 229, 255, 0.2); border-radius: 8px; padding: 14px 16px; color: #00e5ff; font-family: var(--font-sans); font-size: 0.95rem; font-weight: 500; line-height: 1.6; text-align: center; box-shadow: inset 0 2px 8px rgba(0,0,0,0.5);">
                " {{ voiceprintText }} "
              </div>
            </div>

            <!-- 3. 录音按键与波形指示区域 -->
            <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; margin: 10px 0;">
              <!-- 录音状态波纹指示器与进度条 -->
              <div style="height: 24px; display: flex; align-items: center; gap: 3px;" v-if="isRecordingVoiceprint">
                <span v-for="i in 8" :key="i" class="bar" :style="`width: 3px; height: ${Math.random()*16 + 4}px; background: #ff4d4f; border-radius: 1px; display: inline-block; animation: pulseWave ${0.4 + i*0.1}s infinite alternate;`" />
              </div>
              
              <!-- 霓虹高感度进度条 (0% -> 100%) -->
              <div style="height: 6px; width: 100%; background: rgba(255,255,255,0.08); border-radius: 3px; overflow: hidden; margin-bottom: 6px;" v-if="isRecordingVoiceprint">
                <div :style="{ width: Math.min((recordingTime / 15 * 100), 100) + '%' }" style="height: 100%; background: linear-gradient(90deg, #00e5ff, #0072ff); transition: width 0.3s linear; box-shadow: 0 0 10px #00e5ff;"></div>
              </div>

              <!-- 强约束：必须填了角色名才能录制，没有填名时置灰并禁用按钮 -->
              <button 
                type="button"
                @click="isRecordingVoiceprint ? stopVpRecording() : startVpRecording()"
                :disabled="!voiceprintName.trim()"
                :class="isRecordingVoiceprint ? 'btn-record stop-rec' : 'btn-record start-rec'"
                style="width: 72px; height: 72px; border-radius: 50%; border: none; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: all 0.3s; box-shadow: 0 4px 20px rgba(0,0,0,0.3);"
                :style="!voiceprintName.trim() ? 'background: #2a313d; color: #5a667a; cursor: not-allowed; opacity: 0.6;' : (isRecordingVoiceprint ? 'background: #ff4d4f; color: #fff;' : 'background: var(--accent-gradient); color: #080c14;')"
              >
                <span v-if="isRecordingVoiceprint" style="font-size: 1.4rem;">⏹</span>
                <span v-else style="font-size: 1.6rem;">🎙️</span>
              </button>
              
              <span style="font-size: 0.8rem; font-weight: 500; text-align: center;" :style="!voiceprintName.trim() ? 'color: #ff4d4f;' : (isRecordingVoiceprint ? 'color: #ff4d4f;' : 'color: var(--text-secondary);')">
                <template v-if="!voiceprintName.trim()">
                  ⚠️ 请先选择或填写说话人角色名称
                </template>
                <template v-else-if="isRecordingVoiceprint">
                  正在录音中: {{ recordingTime }}秒 / 15秒 (建议朗读 5 - 15 秒)
                </template>
                <template v-else-if="recordedBlob">
                  ✅ 采样录制完成！可以在下方点击确认保存或重新录制。
                </template>
                <template v-else>
                  准备就绪，点击上方按钮开始录音 (5-15秒)
                </template>
              </span>
            </div>

          </div>

          <!-- 4. 底部动作按钮区：未录音前只允许取消；录音完成后提供【重新录制】与【确认保存】 -->
          <div class="modal-actions settings-dialog-actions" style="display: flex; justify-content: flex-end; gap: 12px; padding: 16px 24px; border-top: 1px solid rgba(255,255,255,0.1);">
            <button class="btn-cancel" @click="cancelVpRecordingFlow">取消</button>
            
            <button v-if="recordedBlob && !isRecordingVoiceprint" class="btn-cancel" @click="reRecordVoiceprint" style="border-color: rgba(255, 171, 0, 0.5); color: #ffab00;">
              🔄 重新录制
            </button>

            <button class="btn-save" :disabled="!recordedBlob || !voiceprintName.trim() || isRecordingVoiceprint" @click="uploadVoiceprint" style="box-shadow: 0 4px 12px rgba(0, 229, 255, 0.2);">
              确认保存
            </button>
          </div>

        </div>
      </div>
    </Transition>
  </Teleport>

</template>

<script setup>
import { ref, reactive, computed, nextTick, onMounted, watch } from 'vue'
import ChatBubble from './components/ChatBubble.vue'
import WeatherCard from './components/WeatherCard.vue'
import WakeWordIndicator from './components/WakeWordIndicator.vue'
import { open } from '@tauri-apps/plugin-dialog'
import { listen, emit as tauriEmit } from '@tauri-apps/api/event'
import { invoke as _tauriInvokeRaw } from '@tauri-apps/api/core'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { logger } from './utils/logger'

// ── Tauri invoke（Tauri 环境下为真实 invoke，纯浏览器下为 null）
const isTauriEnvCheck = typeof window !== 'undefined' && !!(window.__TAURI__ || window.__tauri_ipc__)
const tauriInvoke = isTauriEnvCheck ? _tauriInvokeRaw : null
const appWindow = isTauriEnvCheck ? getCurrentWindow() : null

// 判定当前是否为独立设置窗口（兼容 URL query 参数与 Tauri 窗口 label 判定）
const isSettingsWindow = ref(
  (typeof window !== 'undefined' && window.location.search.includes('page=settings')) ||
  (appWindow && appWindow.label === 'settings')
)
const emitEvent = isTauriEnvCheck ? tauriEmit : null

// ── 仅在 Tauri 环境中重定向 console 到 Rust 日志 (增加 window.__console_redirected__ 标记防 Vite HMR 重复包装)
if (isTauriEnvCheck && !window.__console_redirected__) {
  window.__console_redirected__ = true
  const rawLog = window.console.log
  const rawError = window.console.error
  const rawWarn = window.console.warn

  const safeFormat = (a) => {
    if (a === null || a === undefined) return String(a)
    if (a instanceof Error) return `${a.name}: ${a.message}`
    if (typeof a !== 'object') return String(a)
    if (a.$ || a._isVue || a.render) return '[VueComponent]'
    try {
      return JSON.stringify(a)
    } catch (e) {
      return String(a)
    }
  }

  window.console.log = (...args) => {
    rawLog(...args)
    _tauriInvokeRaw('frontend_log', { level: 'LOG', message: args.map(safeFormat).join(' ') }).catch(() => {})
  }
  window.console.error = (...args) => {
    rawError(...args)
    _tauriInvokeRaw('frontend_log', { level: 'ERROR', message: args.map(safeFormat).join(' ') }).catch(() => {})
  }
  window.console.warn = (...args) => {
    rawWarn(...args)
    _tauriInvokeRaw('frontend_log', { level: 'WARN', message: args.map(safeFormat).join(' ') }).catch(() => {})
  }

  console.log('[Frontend] Console redirect initialized.')
}


// ── 响应式状态
const messages = ref([])
const inputText = ref('')
const inputFocused = ref(false)
const sending = ref(false)
const messagesEl = ref(null)
const inputEl = ref(null)
const wakeIndicatorEl = ref(null)
const weatherData = ref(null)
const isStartFullscreen = ref(false)
const showSettings = ref(false)
const originalSettings = ref(null)
const inCall = ref(false) // Whether we are in live full-duplex mode
const isThinking = ref(false) // AI 处于逻辑推理/工具调用思考中
const isUserSpeaking = ref(false) // 用户正在对着麦克风发言
const visualizerVolume = ref(1.0)
const silenceTimer = ref(null) // 10秒静默挂断计时器
const micErrorMsg = ref('')    // 麦克风异常提示
const micDisabled = ref(false) // 麦克风不可用时置灰
const backendOnline = ref(false) // 后端连接状态

// ── 调试面板状态与辅助函数
const showDebugPanel = ref(false)
const debugLogs = ref([])
const debugContentEl = ref(null)

function clearDebugLogs() {
  debugLogs.value = []
}

function toggleLogDetail(idx) {
  debugLogs.value[idx].collapsed = !debugLogs.value[idx].collapsed
}

function hasDetail(log) {
  return log.step === 'tool_call' || log.step === 'tool_result' || log.step === 'control'
}

function getStepLabel(step) {
  const map = {
    kws: '✨ 唤醒监测',
    interrupt: '⚡ 语音打断',
    stt: '🎙️ 语音转写',
    intent: '🧠 意图决策',
    tool_call: '⚙️ 工具调用',
    tool_result: '📤 执行结果',
    tts: '🔊 语音回复',
    control: '📺 大屏控制'
  }
  return map[step] || step
}

function formatTime(ts) {
  const d = ts ? new Date(ts) : new Date()
  if (isNaN(d.getTime())) return '--:--:--'
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}


function formatJson(obj) {
  if (obj === undefined || obj === null) return ''
  if (typeof obj === 'string') {
    try {
      return JSON.stringify(JSON.parse(obj), null, 2)
    } catch {
      return obj
    }
  }
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
}



const activeTab = ref('general')

// ── 1. 自动扫描 configs/models/text/*.json 作为文字对话模型真实保底选项
const textModelModules = import.meta.glob('../configs/models/text/*.json', { eager: true })
const defaultTextModelOptions = Object.entries(textModelModules).map(([path]) => {
  const filename = path.split('/').pop().replace('.json', '')
  return {
    value: filename,
    label: filename
  }
})

// ── 2. 自动扫描 configs/models/voice_e2e/*.json 作为语音端到端模型真实保底选项与发音人字典
const voiceModelModules = import.meta.glob('../configs/models/voice_e2e/*.json', { eager: true })
const defaultVoiceModelOptions = []
const defaultVoiceOptionsMap = {}

Object.entries(voiceModelModules).forEach(([path, mod]) => {
  const data = (mod && mod.default) ? mod.default : mod
  const filename = path.split('/').pop().replace('.json', '')
  defaultVoiceModelOptions.push({ value: filename, label: filename })
  if (data.voice_options && Array.isArray(data.voice_options)) {
    defaultVoiceOptionsMap[filename] = data.voice_options.map(opt => {
      if (typeof opt === 'string') return { value: opt, label: opt }
      return { value: opt.value, label: opt.label || opt.value }
    })
  }
})

// ── 3. 自动扫描 configs/models/asr/*.json 作为 ASR 识别模式真实保底选项
const asrModelModules = import.meta.glob('../configs/models/asr/*.json', { eager: true })
const defaultAsrModelOptions = Object.entries(asrModelModules).map(([path]) => {
  const filename = path.split('/').pop().replace('.json', '')
  return {
    value: filename,
    label: filename
  }
})

const textModelOptions = ref(defaultTextModelOptions)
const voiceModelOptions = ref(defaultVoiceModelOptions)
const kwsModelOptions = ref([
  { value: 'sherpa/models/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01', label: 'WenetSpeech 3.3M 中文单语' },
  { value: 'sherpa/models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20', label: 'ZH-EN 3M 中英双语' }
])
const asrModelOptions = ref(defaultAsrModelOptions)

const voiceOptionsMap = reactive(defaultVoiceOptionsMap)
const voiceOptions = ref([])


// ── 默认路径（使用项目相对路径）
const defaultModelDir = 'sherpa/models/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01'

const settings = reactive({
  // 客户端本地配置 (从 configs/global.json 动态覆盖)
  wakeWord: '小安小安',
  modelDir: defaultModelDir,
  backendUrl: 'http://127.0.0.1:10850',
  voice: '',
  voiceSpeed: 50,
  // KWS 引擎参数
  kwsMaxActivePaths: 4,
  kwsNumTrailingBlanks: 1,
  kwsScore: 1.5,
  kwsThreshold: 0.25,

  // 后端及全局通用配置
  defaultCity: '',
  textModelName: defaultTextModelOptions.length > 0 ? defaultTextModelOptions[0].value : '',
  voiceCascadeModelName: '',
  voiceModelName: 'qwen-audio-3.0-realtime-flash',
  textModelToolMode: '',
  voiceCascadeModelToolMode: '',
  voiceModelToolMode: '',
  textModelToolStyle: '',
  voiceCascadeModelToolStyle: '',
  enableVisualBroadcast: true,
  showWeatherCard: true,
  asrMode: 'offline',
  localTtsSpeakerId: 0,
  voiceInteractionStyle: 'e2e',
  cascadeTtsType: 'sherpa-vits',
  localTtsSpeedRate: 1.05,
  e2eTemperature: 0.9,
  e2eMaxTokens: 512,
  e2eSilenceDurationMs: 350,
  cascadeSilenceDurationMs: 1200,
  logLevel: 'INFO',
  logFileLevel: 'WARNING',
  sessionIdleTimeoutSec: 30,
  cascadeVadEnergyThreshold: 0.025,
  qwenAudioTurnMode: 'server_vad',
  qwenAudioVadThreshold: 0.5,
  qwenAudioMaxHistoryTurns: 20,
  qwenAudioVoiceprintAudioUrls: '',
  qwenAudioVoiceprintMode: 'static',
  selectedVoiceprintId: 'Ming',
  streamAsrEnabled: true,
  interruptionMode: 'wake_word_only',
  voiceprintServerUrl: 'http://8.141.83.146:8777'
})

function getVoiceprintServerUrl() {
  const url = settings.voiceprintServerUrl || 'http://8.141.83.146:8777'
  return url.replace(/\/+$/, '')
}

// ── 声纹及锁定说话人相关反应式变量 ──
const voiceprints = ref([])
const showVoiceprintRecorder = ref(false)
const voiceprintName = ref('')
const isCreatingNewRole = ref(false)
const isRecordingVoiceprint = ref(false)
const recordingTime = ref(0)
const selectedSampleId = ref('')

const selectedRoleSamples = computed(() => {
  if (!settings.selectedVoiceprintId || !Array.isArray(voiceprints.value)) return []
  const match = voiceprints.value.find(vp => vp && (vp.id === settings.selectedVoiceprintId || vp.name === settings.selectedVoiceprintId))
  return match && Array.isArray(match.samples) ? match.samples : []
})

// 当选中的角色切换时，自动默认选择最新那条采样
watch(() => settings.selectedVoiceprintId, (newVal) => {
  if (newVal && selectedRoleSamples.value.length > 0) {
    selectedSampleId.value = selectedRoleSamples.value[0].id
  } else {
    selectedSampleId.value = ''
  }
}, { immediate: true })

const voiceprintReadingTexts = [
  "今天受暖湿气流影响，全省大部地区维持多云间晴的天气，午后伴有微风，气温适宜，非常适合户外出行与运动。",
  "根据气象台最新监测，预计今夜至明天局部地区将有小到中雨，局地伴有短时强降水，出门前请随身携带雨具。",
  "未来三天受较强冷空气持续影响，各地气温将出现明显下降，风力逐渐增大，请广大市民及时添衣保暖谨防感冒。",
  "受高空槽和低层切变线共同影响，本市未来二十四小时内将迎来一次明显降水过程，局部地区可能伴有短时雷暴。",
  "目前沿海地区风力正在逐步加大，阵风可达七到八级，请海上作业船只及时回港避风，注意防范台风外围影响。",
  "气象部门今日连续发布大雾黄色预警，清晨部分高架及高速公路能见度较低，请广大驾驶员减速慢行保持车距。",
  "本周周末全市气温回升迅速，最高气温有望突破二十八摄氏度，天气晴朗微风，十分适合安排郊游与户外踏青。",
  "受气旋东移影响，明天午后起全市将转为雷阵雨天气，局地可能出现冰雹和短时大风，请公众密切关注预报。",
  "连续阴雨天气将于明日告一段落，后天起全市回归久违的晴好天气，空气质量优良，利于各类洗晒与户外活动。",
  "近期空气相对湿度持续偏低，天干物燥，森林火险等级较高，请相关部门加强巡查，社会公众注意用火用电安全。"
]
const voiceprintText = ref('')
const isGeneratingPromptText = ref(false)
let vpMediaRecorder = null
let vpAudioChunks = []
let vpTimer = null

function reRecordVoiceprint() {
  recordedBlob.value = null
  recordingTime.value = 0
  refreshVoiceprintPromptText()
}


function refreshVoiceprintPromptText() {
  if (voiceprintReadingTexts.length === 0) return
  const currentText = voiceprintText.value
  let nextText = currentText
  let attempts = 0
  while (nextText === currentText && attempts < 10) {
    nextText = voiceprintReadingTexts[Math.floor(Math.random() * voiceprintReadingTexts.length)]
    attempts++
  }
  voiceprintText.value = nextText
}


function isQwenAudioModelActive() {
  const name = (settings.voiceModelName || '').toLowerCase()
  return name.includes('qwen-audio')
}

async function fetchVoiceprints() {
  // 声纹功能专属 Qwen-Audio 实时模型，非 Qwen-Audio 模型静默跳过
  if (!isQwenAudioModelActive()) {
    return
  }

  try {
    const res = await fetch(getVoiceprintServerUrl() + "/api/voiceprints")
    if (res.ok) {
      const list = await res.json()
      voiceprints.value = Array.isArray(list) ? list : []
      
      if (voiceprints.value.length > 0) {
        const currentId = settings.selectedVoiceprintId
        const match = voiceprints.value.find(
          vp => vp && (vp.id === currentId || vp.name === currentId)
        )
        if (match) {
          settings.selectedVoiceprintId = match.id || match.name
        } else {
          settings.selectedVoiceprintId = voiceprints.value[0].id || voiceprints.value[0].name
        }
      }
    }
  } catch (e) {
    console.error('[fetchVoiceprints] 失败:', e)
  }
}




// ── 声纹录制业务流实现 ──
let vpMicStream = null
let vpAudioContext = null
let vpProcessor = null

function startRecordVoiceprintFlow() {
  if (settings.selectedVoiceprintId) {
    const match = voiceprints.value.find(vp => vp.id === settings.selectedVoiceprintId || vp.name === settings.selectedVoiceprintId)
    voiceprintName.value = match ? match.name : settings.selectedVoiceprintId
    isCreatingNewRole.value = false
  } else if (voiceprints.value.length > 0) {
    voiceprintName.value = voiceprints.value[0].name
    isCreatingNewRole.value = false
  } else {
    voiceprintName.value = ''
    isCreatingNewRole.value = true
  }
  voiceprintText.value = voiceprintReadingTexts[Math.floor(Math.random() * voiceprintReadingTexts.length)]
  recordedBlob.value = null
  recordingTime.value = 0
  showVoiceprintRecorder.value = true
  refreshVoiceprintPromptText()
}



const recordedBlob = ref(null)

async function startVpRecording() {
  if (isRecordingVoiceprint.value) return
  
  try {
    try {
      vpMicStream = await navigator.mediaDevices.getUserMedia({ audio: {
        sampleRate: { ideal: 16000 },
        channelCount: { ideal: 1 },
        echoCancellation: true,
        noiseSuppression: true
      }})
    } catch (e) {
      console.warn('[Frontend] 声纹录制尝试高级参数失败，使用 audio: true 兜底:', e)
      vpMicStream = await navigator.mediaDevices.getUserMedia({ audio: true })
    }
    
    vpAudioChunks = []
    vpAudioContext = new AudioContext({ sampleRate: 16000 })
    const source = vpAudioContext.createMediaStreamSource(vpMicStream)
    vpProcessor = vpAudioContext.createScriptProcessor(4096, 1, 1)
    
    vpProcessor.onaudioprocess = (e) => {
      const channelData = e.inputBuffer.getChannelData(0)
      vpAudioChunks.push(new Float32Array(channelData))
    }
    
    source.connect(vpProcessor)
    vpProcessor.connect(vpAudioContext.destination)
    
    isRecordingVoiceprint.value = true
    recordingTime.value = 0
    
    vpTimer = setInterval(() => {
      recordingTime.value++
      // 达到最长 15 秒自动结束录音
      if (recordingTime.value >= 15) {
        stopVpRecording(true)
      }
    }, 1000)
    
  } catch (e) {
    alert('无法获取麦克风，请检查设备权限: ' + e.message)
    console.error('[Voiceprint Recording] Error:', e)
  }
}

function stopVpRecording(force = false) {
  if (!isRecordingVoiceprint.value) return
  
  // 最短 5 秒限制：非到期或非取消状态，录音不满 5 秒时进行拦截阻断
  if (!force && recordingTime.value < 5) {
    alert(`录音时长不足 5 秒（当前仅 ${recordingTime.value} 秒），为了确保声纹特征提取的精准度，请至少朗读 5 秒以上。`)
    return
  }

  isRecordingVoiceprint.value = false
  
  if (vpTimer) {
    clearInterval(vpTimer)
    vpTimer = null
  }
  
  if (vpProcessor) {
    vpProcessor.disconnect()
    vpProcessor = null
  }
  if (vpAudioContext) {
    vpAudioContext.close()
    vpAudioContext = null
  }
  if (vpMicStream) {
    vpMicStream.getTracks().forEach(track => track.stop())
    vpMicStream = null
  }
  
  // 编码合成 WAV 格式数据
  if (vpAudioChunks.length === 0) return
  
  // 1. 合并 Float32 帧
  let totalLength = vpAudioChunks.reduce((acc, chunk) => acc + chunk.length, 0)
  let mergedData = new Float32Array(totalLength)
  let offset = 0
  for (let chunk of vpAudioChunks) {
    mergedData.set(chunk, offset)
    offset += chunk.length
  }
  
  // 2. 转换为 16-bit PCM Int16 数据
  const pcmBuffer = new Int16Array(totalLength)
  for (let i = 0; i < totalLength; i++) {
    const s = Math.max(-1, Math.min(1, mergedData[i]))
    pcmBuffer[i] = s < 0 ? s * 0x8000 : s * 0x7FFF
  }
  
  // 3. 构建 44 字节 WAV 文件头
  const wavBuffer = new ArrayBuffer(44 + pcmBuffer.byteLength)
  const view = new DataView(wavBuffer)
  
  // RIFF identifier
  view.setUint32(0, 0x52494646, false) // "RIFF"
  // file length
  view.setUint32(4, 36 + pcmBuffer.byteLength, true)
  // RIFF type
  view.setUint32(8, 0x57415645, false) // "WAVE"
  // format chunk identifier
  view.setUint32(12, 0x666d7420, false) // "fmt "
  // format chunk length
  view.setUint32(16, 16, true)
  // sample format (raw)
  view.setUint16(20, 1, true) // 1 = PCM
  // channel count
  view.setUint16(22, 1, true) // Mono
  // sample rate
  view.setUint32(24, 16000, true) // 16kHz
  // byte rate (sample rate * block align)
  view.setUint32(28, 16000 * 2, true)
  // block align (channel count * bytes per sample)
  view.setUint16(32, 2, true) // 2 bytes
  // bits per sample
  view.setUint16(34, 16, true) // 16-bit
  // data chunk identifier
  view.setUint32(36, 0x64617461, false) // "data"
  // data chunk length
  view.setUint32(40, pcmBuffer.byteLength, true)
  
  // 4. 拷贝 PCM 数据至 WAV 缓存中
  const wavBytes = new Uint8Array(wavBuffer)
  wavBytes.set(new Uint8Array(pcmBuffer.buffer), 44)
  
  recordedBlob.value = new Blob([wavBuffer], { type: 'audio/wav' })
  console.log('[Voiceprint WAV] 编码合成完成，大小:', recordedBlob.value.size, '字节')
}

function cancelVpRecordingFlow() {
  stopVpRecording(true)
  showVoiceprintRecorder.value = false
  recordedBlob.value = null
  voiceprintName.value = ''
}

async function uploadVoiceprint() {
  if (!voiceprintName.value.trim()) {
    alert('请输入声纹名称！')
    return
  }
  if (!recordedBlob.value) {
    alert('请先进行声纹录音！')
    return
  }
  
  const formData = new FormData()
  formData.append('name', voiceprintName.value.trim())
  formData.append('file', recordedBlob.value, 'voiceprint.wav')
  
  try {
    const res = await fetch(getVoiceprintServerUrl() + "/api/voiceprints", {
      method: 'POST',
      body: formData
    })
    if (res.ok) {
      const data = await res.json()
      alert('声纹录制与注册成功！')
      showVoiceprintRecorder.value = false
      // 切换为静态锁定模式，刷新列表并选中新录制的声纹
      settings.qwenAudioVoiceprintMode = 'static'
      settings.selectedVoiceprintId = data.id || voiceprintName.value.trim()
      await fetchVoiceprints()
      settings.selectedVoiceprintId = data.id || voiceprintName.value.trim()
      recordedBlob.value = null
      voiceprintName.value = ''

    } else {
      const err = await res.json()
      alert('声纹保存失败: ' + (err.detail || '未知原因'))
    }
  } catch (e) {
    alert('保存声纹请求发生网络异常: ' + e.message)
  }
}



async function deleteSingleVoiceprintSample(sampleId) {
  if (!sampleId) {
    alert('请选择要删除的音频采样！')
    return
  }
  const sampleObj = selectedRoleSamples.value.find(s => s.id === sampleId)
  const displayName = sampleObj ? (sampleObj.created_at || sampleObj.filename) : sampleId
  if (!confirm(`确定要删除具体的录音采样『${displayName}』吗？`)) {
    return
  }
  try {
    const res = await fetch(getVoiceprintServerUrl() + `/api/voiceprints/${encodeURIComponent(sampleId)}`, {
      method: 'DELETE'
    })
    if (res.ok) {
      alert(`录音采样『${displayName}』已成功删除！`)
      selectedSampleId.value = ''
      await fetchVoiceprints()
    } else {
      const err = await res.json()
      alert('删除采样失败: ' + (err.detail || '未知原因'))
    }
  } catch (e) {
    alert('删除网络异常: ' + e.message)
  }
}

async function deleteVoiceprintRole(vpId) {
  const match = voiceprints.value.find(vp => vp.id === vpId || vp.name === vpId)
  const roleName = match ? match.name : vpId
  if (!confirm(`确定要删除整个声纹角色『${roleName}』及其下的所有录音采样吗？删除后不可恢复。`)) {
    return
  }
  try {
    const res = await fetch(getVoiceprintServerUrl() + `/api/voiceprints/${encodeURIComponent(vpId)}`, {
      method: 'DELETE'
    })
    if (res.ok) {
      alert(`声纹角色『${roleName}』已成功删除！`)
      if (settings.selectedVoiceprintId === vpId) {
        settings.selectedVoiceprintId = ''
      }
      await fetchVoiceprints()
    } else {
      const err = await res.json()
      alert('删除失败: ' + (err.detail || '未知原因'))
    }
  } catch (e) {
    alert('删除网络异常: ' + e.message)
  }
}

const activeRoleSampleCount = computed(() => {
  const name = voiceprintName.value.trim()
  if (!name) return 0
  const match = voiceprints.value.find(vp => vp.name === name || vp.id === name)
  return match ? (match.sample_count || 1) : 0
})




const quickQuestions = [
  '🌤 今天天气怎么样？',
  '🌧 明天会下雨吗？',
  '🌡 我想看一下卫星云图',
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
    const res = await fetch(settings.backendUrl + "/weather?city=" + encodeURIComponent(city))
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

async function sendMessage(text) {
  const content = (text || inputText.value).trim()
  if (!content) return

  inputText.value = ''
  nextTick(() => { if (inputEl.value) { inputEl.value.style.height = 'auto' } })

  messages.value.push({ role: 'user', content })
  scrollToBottom()

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

    const resp = await fetch(settings.backendUrl + "/chat", {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        message: content,
        history: history.slice(-10),
        system: "你是一个名为“小安”的智能语音助手，请用简洁友好的中文回答问题。"
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
          } else if (obj.type === 'debug_event') {
            // 支持显示后端在文字对话时返回的工具调用调试日志
            debugLogs.value.push({
              step: obj.step,
              name: obj.name,
              content: obj.content,
              arguments: obj.arguments,
              result: obj.result,
              timestamp: Date.now(),
              collapsed: false
            })
            nextTick(() => {
              if (debugContentEl.value) {
                debugContentEl.value.scrollTop = debugContentEl.value.scrollHeight
              }
            })
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
const isPlaying = ref(false)     // 是否正在播放
let pendingSilenceTimer = false  // 是否等待播放完后启动静默计时器
let activeAudioSource = null     // 当前正在播放的 AudioBufferSourceNode
let activeAudioResolve = null    // 当前正在等待的播放 Promise resolve 函数

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

let isAudioLoopRunning = false

// 播放 PCM16 bytes (自适应采样率)
async function enqueueAudio(pcm16bytes) {
  if (!pcm16bytes || pcm16bytes.length === 0) return

  let pcmData = pcm16bytes
  if (pcmData.length > 0 && pcmData[0] === 0x00) {
    pcmData = pcmData.subarray(1)
  }
  if (pcmData.length === 0) return

  const isLocal = settings.voiceModelName === 'sherpa-local'
  const expectedRate = isLocal ? 8000 : 24000

  if (!playCtx || playCtx.sampleRate !== expectedRate) {
    if (playCtx) {
      playCtx.close().catch(() => {})
    }
    playCtx = new AudioContext({ sampleRate: expectedRate })
  }

  if (playCtx.state === 'suspended') {
    await playCtx.resume().catch(() => {})
  }

  playQueue.push(pcmData)

  if (!isAudioLoopRunning) {
    isAudioLoopRunning = true
    isPlaying.value = true
    console.log('[Audio Debug] ▶️ 开始物理播报 AI 回复语音...')
    while (playQueue.length > 0) {
      const chunk = playQueue.shift()
      const numSamples = Math.floor(chunk.byteLength / 2)
      if (numSamples === 0) continue

      const slicedBuffer = chunk.buffer.slice(chunk.byteOffset, chunk.byteOffset + numSamples * 2)
      const int16 = new Int16Array(slicedBuffer)
      const float32 = new Float32Array(int16.length)
      for (let i = 0; i < int16.length; i++) {
        float32[i] = int16[i] / 32768.0
      }
      const buffer = playCtx.createBuffer(1, float32.length, expectedRate)
      buffer.copyToChannel(float32, 0)
      const source = playCtx.createBufferSource()
      source.buffer = buffer
      source.connect(playCtx.destination)
      activeAudioSource = source

      const durationMs = (float32.length / expectedRate) * 1000

      await new Promise(resolve => {
        let isDone = false
        let timerId = null
        const done = () => {
          if (!isDone) {
            isDone = true
            if (timerId) clearTimeout(timerId)
            activeAudioSource = null
            activeAudioResolve = null
            resolve()
          }
        }
        activeAudioResolve = done
        source.onended = done
        if (playCtx.state === 'suspended') {
          playCtx.resume().catch(() => {})
        }
        source.start()

        timerId = setTimeout(done, durationMs + 100)
      })
    }
    isAudioLoopRunning = false
    isPlaying.value = false
    console.log('[Audio Debug] 🎉 AI 回复语音播报完毕！恢复倾听状态。')
    if (inCall.value) {
      isUserSpeaking.value = true
      isThinking.value = false
    }
    if (pendingSilenceTimer) {
      pendingSilenceTimer = false
      startSilenceTimer()
    }
  }
}

function stopAudioPlayback() {
  console.log('[Audio Debug] 🛑 触发 stopAudioPlayback，强行清空播放队列与活动音频源')
  playQueue.length = 0
  if (activeAudioSource) {
    try { activeAudioSource.stop() } catch (e) {}
    activeAudioSource = null
  }
  if (activeAudioResolve) {
    try { activeAudioResolve() } catch (e) {}
    activeAudioResolve = null
  }
  isAudioLoopRunning = false
  isPlaying.value = false
  if (playCtx) {
    try { playCtx.close() } catch (e) {}
    playCtx = null
  }
}

// ── 语音通话控制
function startSilenceTimer() {
  stopSilenceTimer()
  const timeoutSec = Number(settings.sessionIdleTimeoutSec)
  const timeoutVal = isNaN(timeoutSec) ? 30 : timeoutSec
  if (timeoutVal <= 0) {
    return
  }
  const timeoutMs = timeoutVal * 1000
  silenceTimer.value = setTimeout(() => {
    console.log(`[SilenceDetector] ${timeoutVal}秒无语音输入，准备挂断`)
    // 先显示提示消息
    messages.value.push({ role: 'assistant', content: '如果没有其他问题，我先退下了。', isFinal: true })
    scrollToBottom()
    // 延迟2秒后挂断，给用户反应时间
    silenceTimer.value = setTimeout(() => {
      endVoiceCall()
    }, 2000)
  }, timeoutMs)
}

function stopSilenceTimer() {
  if (silenceTimer.value) {
    clearTimeout(silenceTimer.value)
    silenceTimer.value = null
  }
}

async function startVoiceCall() {
  if (inCall.value) {
    console.warn('[startVoiceCall] Already in call, ignoring trigger.')
    return
  }
  inCall.value = true
  isPlaying.value = false // 复位播放标志，保证开启通话时麦克风音轨流立刻正常推送到 WebSocket
  showDebugPanel.value = true // 通话开启时自动打开调试面板
  debugLogs.value = [] // 开启新通话时，清空上一次的调试日志
  try {
    // 保持本地 KWS 监听继续开启，以支持通话中随时叫唤醒词打断
    // 强制枚举设备以刷新 Chrome 内部设备缓存（解决插拔后无法找到默认麦克风的问题）
    await navigator.mediaDevices.enumerateDevices().catch(() => {})
    // 获取麦克风（带参数降级兜底，兼容 Linux / GStreamer 各种后端驱动）
    try {
      micStream = await navigator.mediaDevices.getUserMedia({ audio: {
        sampleRate: { ideal: 16000 },
        channelCount: { ideal: 1 },
        echoCancellation: true,
        noiseSuppression: true
      }})
    } catch (micErr) {
      console.warn('[Frontend] 组合音频参数打开麦克风失败，降级使用 audio: true 兜底:', micErr)
      micStream = await navigator.mediaDevices.getUserMedia({ audio: true })
    }

    // 建立 WebSocket 连接
    const wsUrl = settings.backendUrl
      .replace(/^https?:\/\//, (m) => m === 'http://' ? 'ws://' : 'wss://')
      + `/voice_ws?voice=${settings.voice}`
    voiceWs = new WebSocket(wsUrl)
    voiceWs.binaryType = 'arraybuffer'

    voiceWs.onopen = () => {
      console.log('[voice_ws] 已连接')

      // 唤醒或手动启动后自动切换到对话页面
      if (messages.value.length === 0) {
        messages.value.push({ 
          role: 'assistant', 
          content: '在', 
          isFinal: true, 
          isVoiceWs: true, 
          timestamp: Date.now() 
        })
        scrollToBottom()
      }

      // 开始录音推流
      audioCtx = new AudioContext({ sampleRate: 16000 })

      // 预先创建并唤醒 AI 语音播放用 AudioContext (24kHz/8kHz)，避免异步回调中受到浏览器自动播放策略挂起
      const isLocal = settings.voiceModelName === 'sherpa-local'
      const expectedRate = isLocal ? 8000 : 24000
      if (!playCtx || playCtx.sampleRate !== expectedRate) {
        if (playCtx) { try { playCtx.close() } catch {} }
        playCtx = new AudioContext({ sampleRate: expectedRate })
      }
      if (playCtx.state === 'suspended') {
        playCtx.resume().catch(() => {})
      }

      micSource = audioCtx.createMediaStreamSource(micStream)
      micProcessor = audioCtx.createScriptProcessor(2048, 1, 1)
      micProcessor.onaudioprocess = (e) => {
        const buf = e.inputBuffer.getChannelData(0)
        // 1. 计算当前数据块的 RMS 有效音频能量
        const rms = Math.sqrt(buf.reduce((s, v) => s + v * v, 0) / buf.length)
        
        // 2. 在仅唤醒词打断模式下，当 AI 正在播放回答时，麦克风流切至端侧 KWS，不发往云端/后端
        const isWakeWordOnly = settings.interruptionMode === 'wake_word_only'
        if (isWakeWordOnly && isPlaying.value) {
          visualizerVolume.value = 1.0 + rms * 20
          return
        }

        if (voiceWs && voiceWs.readyState === WebSocket.OPEN) {
          voiceWs.send(float32ToPcm16WithPrefix(buf))
        }
        // 3. 始终更新音量可视化展示
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
      } else if (typeof Blob !== 'undefined' && event.data instanceof Blob) {
        const arrayBuf = await event.data.arrayBuffer()
        await enqueueAudio(new Uint8Array(arrayBuf))
        visualizerVolume.value = 1.5
      } else {
        // 文本 JSON 消息
        try {
          const msg = JSON.parse(event.data)
          if (msg.type === 'debug_event') {
            const lastLog = debugLogs.value[debugLogs.value.length - 1]
            if (lastLog && lastLog.step === msg.step && (msg.step === 'tts' || msg.step === 'stt')) {
              lastLog.content = msg.content
              lastLog.timestamp = Date.now()
            } else {
              debugLogs.value.push({
                step: msg.step,
                name: msg.name,
                content: msg.content,
                arguments: msg.arguments,
                result: msg.result,
                timestamp: Date.now(),
                collapsed: false
              })
            }
            nextTick(() => {
              if (debugContentEl.value) {
                debugContentEl.value.scrollTop = debugContentEl.value.scrollHeight
              }
            })
            return // 拦截调试事件，不要向下执行
          }
          if (msg.type === 'interrupt') {
            stopAudioPlayback()
            // 如果遇到打断，将当前正在输出的 assistant 消息标记为最终，防止后续消息插队
            let lastMsg = messages.value[messages.value.length - 1];
            if (lastMsg && lastMsg.role === 'assistant' && lastMsg.isVoiceWs) {
              lastMsg.isFinal = true;
            }
          } else if (msg.type === 'output_transcript_done') {
            // 后端通知当前 assistant 回复结束
            let lastMsg = messages.value[messages.value.length - 1];
            if (lastMsg && lastMsg.role === 'assistant' && lastMsg.isVoiceWs) {
              lastMsg.isFinal = true;
            }
            if (isPlaying.value) {
              pendingSilenceTimer = true
            } else {
              startSilenceTimer()
            }
          } else if (msg.type === 'input_transcript') {
            // 用户说话的转录（支持流式中间态与最终态）
            const now = Date.now()
            stopSilenceTimer()
            const isFinal = msg.is_final !== false

            const findInterimUserMsg = () => {
              for (let i = messages.value.length - 1; i >= 0; i--) {
                const m = messages.value[i]
                if (m.role === 'user' && m.isVoiceWs && m.isFinal === false) {
                  return m
                }
              }
              return null
            }

            if (!isFinal) {
              // 中间态：复用现有中间态气泡或创建新的
              let interim = findInterimUserMsg()
              if (!interim) {
                interim = {
                  id: 'in-' + now,
                  role: 'user',
                  content: msg.data,
                  isFinal: false,
                  isVoiceWs: true,
                  timestamp: now
                }
                // 若最后一条是 assistant 正在流式输出，插入到它前面
                let lastMsg = messages.value[messages.value.length - 1]
                if (lastMsg && lastMsg.role === 'assistant' && lastMsg.isVoiceWs && !lastMsg.isFinal) {
                  messages.value.splice(messages.value.length - 1, 0, interim)
                } else {
                  messages.value.push(interim)
                }
              }
              if (interim.content !== msg.data) {
                interim.content = msg.data
                interim.timestamp = now
              }
            } else {
              // 最终态：把最近的中间态消息转为最终态；若没有则新建
              const interim = findInterimUserMsg()
              if (interim) {
                interim.content = msg.data
                interim.isFinal = true
                interim.timestamp = now
              } else {
                const newMsg = {
                  id: 'in-' + now,
                  role: 'user',
                  content: msg.data,
                  isFinal: true,
                  isVoiceWs: true,
                  timestamp: now
                }
                let lastMsg = messages.value[messages.value.length - 1]
                if (lastMsg && lastMsg.role === 'assistant' && lastMsg.isVoiceWs && !lastMsg.isFinal) {
                  messages.value.splice(messages.value.length - 1, 0, newMsg)
                } else {
                  messages.value.push(newMsg)
                }
              }
              if (isFinal) {
                isUserSpeaking.value = false
                isThinking.value = true
              } else {
                isUserSpeaking.value = true
              }
            }
            scrollToBottom()

          } else if (msg.type === 'output_transcript' || msg.type === 'weather_summary') {
            isUserSpeaking.value = false
            isThinking.value = false
            // AI 回复的累加流式文本
            let lastMsg = messages.value[messages.value.length - 1];
            if (lastMsg && lastMsg.role === 'assistant' && lastMsg.isVoiceWs && !lastMsg.isFinal) {
              lastMsg.content = msg.data;
            } else {
              messages.value.push({
                id: 'out-' + Date.now(),
                role: 'assistant',
                content: msg.data,
                isFinal: false,
                isVoiceWs: true
              });
            }
            scrollToBottom()
            // AI 文字回复完成，如果语音还在播放，等播放完再启动计时器
            if (isPlaying.value) {
              pendingSilenceTimer = true
            } else {
              startSilenceTimer()
            }
          } else if (msg.type === 'output_transcript_done') {
            let lastMsg = messages.value[messages.value.length - 1];
            if (lastMsg && lastMsg.role === 'assistant' && lastMsg.isVoiceWs) {
              lastMsg.isFinal = true;
              if (msg.data) lastMsg.content = msg.data;
            }
          } else if (msg.type === 'weather_data') {
            weatherData.value = msg.data
            scrollToBottom()
          } else if (msg.type === 'user_info_update') {
            console.log('[voice_ws] 收到用户信息实时更新:', msg)
            if (msg.city) {
              settings.defaultCity = msg.city
            }
            scrollToBottom()
            } else if (msg.type === 'state_change') {
              const state = msg.state
              console.log('[voice_ws] State Change ->', state)
              if (state === 'listening') {
                if (!isPlaying.value) {
                  isUserSpeaking.value = true
                  isThinking.value = false
                }
              } else if (state === 'thinking') {
                isUserSpeaking.value = false
                isThinking.value = true
              } else if (state === 'speaking') {
                isUserSpeaking.value = false
                isThinking.value = false
                isPlaying.value = true
              } else if (state === 'idle' || state === 'sleeping') {
                stopAudioPlayback()
                isUserSpeaking.value = false
                isThinking.value = false
                isPlaying.value = false
              }
            } else if (msg.type === 'hangup') {
              console.log('[voice_ws] Received hangup signal')
              isUserSpeaking.value = false
              isThinking.value = false
              isPlaying.value = false
              playExitAck(() => {
                endVoiceCall()
              })
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
  debugLogs.value.push({
    step: 'kws',
    content: '🚫 退出语音对话，已恢复唤醒监听。',
    timestamp: Date.now()
  })
  inCall.value = false
  isUserSpeaking.value = false
  isThinking.value = false
  isPlaying.value = false
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

  if (wakeIndicatorEl.value) {
    wakeIndicatorEl.value.startListening()
  }
}

// ── 唤醒词触发
function onKwsDebug(msg) {
  console.log('[KWS Debug]', msg)
}

// 唤醒后固定语音回答"在"（播放 zai_female.wav）
function playWakeAck(callback) {
  const audioUrl = settings.backendUrl + "/assets/zai_female.wav"
  const audio = new Audio(audioUrl)
  
  let called = false
  const done = () => {
    if (!called) {
      called = true
      callback()
    }
  }
  
  audio.onended = done
  audio.onerror = (err) => {
    console.warn('[KWS Audio Playback] 唤醒音频加载或播放失败，自动跳过:', err)
    done()
  }
  
  // 1500ms 超时保护，防止网络挂起或卡住
  setTimeout(done, 1500)
  
  audio.play().catch((err) => {
    console.warn('[KWS Audio Playback] 浏览器拦截或无法播放:', err)
    done()
  })
}
// 退出前打印文字“再见”并播放 exit_female.wav
function playExitAck(callback) {
  stopAudioPlayback()
  isUserSpeaking.value = false
  isThinking.value = false
  isPlaying.value = false
  messages.value.push({
    id: 'exit-' + Date.now(),
    role: 'assistant',
    content: '再见',
    isFinal: true,
    isVoiceWs: true
  })
  scrollToBottom()

  const audioUrl = settings.backendUrl + "/assets/exit_female.wav"
  const audio = new Audio(audioUrl)
  
  let called = false
  const done = () => {
    if (!called) {
      called = true
      if (callback) callback()
    }
  }
  
  audio.onended = done
  audio.onerror = (err) => {
    console.warn('[Exit Audio Playback] 退出音频加载或播放失败:', err)
    done()
  }
  
  setTimeout(done, 2000)
  
  audio.play().catch((err) => {
    console.warn('[Exit Audio Playback] 浏览器播放被拦截或播放失败:', err)
    done()
  })
}


let lastWakeTime = 0

function onWakeDetected(payload) {
  const now = Date.now()
  if (now - lastWakeTime < 1000) {
    console.log('[App] 忽略 1000ms 冷却期内的重复唤醒触发:', payload)
    return
  }
  lastWakeTime = now
  console.log('[App] 唤醒词触发，payload：', payload)
  
  // 提取配置中所有的纯文本中文词汇，用于与识别出的 payload 进行匹配
  const isWakeWordMatched = (p) => {
    if (p === 0) return true
    if (typeof p !== 'string') return false
    const rawText = settings.wakeWord || ''
    const words = []
    rawText.split('\n').forEach(line => {
      const l = line.trim()
      if (!l) return
      if (l.includes('@')) {
        const w = l.split('@').pop().trim()
        if (w) words.push(w)
      } else {
        words.push(l)
      }
    })
    if (words.length === 0) {
      words.push('小安')
      words.push('启动')
    }
    return words.some(w => p.includes(w) || w.includes(p))
  }
  
  // 兼容逻辑：若 payload 是数字 0 或匹配了配置项中的任意唤醒词，视为开启通话/触发打断
  const isStart = payload === 0 || isWakeWordMatched(payload);
                   
  // 若 payload 是数字 1 或包含了"退下"等挂断词，视为结束通话
  const isStop = payload === 1 || 
                 (typeof payload === 'string' && 
                  (payload.includes('退下') || payload.includes('挂断') || payload.includes('再见') || 
                   payload.includes('去休息吧') || payload.includes('退出') || payload.includes('别说了') || 
                   payload.includes('闭嘴') || payload.includes('拜拜') || payload.includes('滚蛋')));

  if (isStart) {
    if (!inCall.value) {
      // 场景 A：休眠状态下唤醒 -> 建连通话
      debugLogs.value.push({
        step: 'kws',
        content: `✨ 检测到唤醒词: [${typeof payload === 'string' ? payload : '小安小安'}]，唤醒成功`,
        timestamp: Date.now()
      })
      
      // 先语音回答"在"，播放完毕（或超时）后再启动语音通话，防止麦克风录入"在"的声音导致回声
      playWakeAck(() => {
        startVoiceCall()
        if (messages.value.length === 0) {
          messages.value.push({ role: 'assistant', content: '在', isFinal: true })
          scrollToBottom()
        }
      })
    } else {
      // 场景 B：通话中/正在播报状态 -> 0 延迟本地硬打断重置
      debugLogs.value.push({
        step: 'interrupt',
        content: `⚡ 触发打断指令: [${typeof payload === 'string' ? payload : '小安小安'}]，重置为倾听`,
        timestamp: Date.now()
      })
      
      // 1. 物理切音：停止本地一切正在播放的 AI 语音
      stopAudioPlayback()

      // 2. 0 延迟即时重置前端 UI 状态为“聆听中”
      isUserSpeaking.value = true
      isThinking.value = false
      isPlaying.value = false
      visualizerVolume.value = 1.0

      // 3. 发送 interrupt 信号给后端取消云端生成并重置锁
      if (voiceWs && voiceWs.readyState === WebSocket.OPEN) {
        voiceWs.send(JSON.stringify({ type: 'interrupt' }))
      }

      // 4. 重置静默计时器
      stopSilenceTimer()
      startSilenceTimer()
    }
  } else if (isStop) {
    if (inCall.value) {
      if (voiceWs && voiceWs.readyState === WebSocket.OPEN) {
        voiceWs.send(JSON.stringify({ type: 'query', text: '退下' }))
      } else {
        endVoiceCall()
        messages.value.push({ role: 'assistant', content: '好的，先退下了。', isFinal: true })
        scrollToBottom()
      }
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

function fetchVoices(modelName) {
  if (!modelName) return
  const options = defaultVoiceOptionsMap[modelName] || []
  if (options && Array.isArray(options) && options.length > 0) {
    voiceOptions.value = [...options]
    if (!options.some(opt => opt.value === settings.voice)) {
      settings.voice = options[0].value
    }
  } else {
    voiceOptions.value = []
  }
}

// ── 从本地磁盘配置文件直接读取配置（不依赖后端是否在线）
async function loadDiskConfig() {
  if (!tauriInvoke) return
  
  // 1. 读取 global.json
  try {
    const globalCfg = await tauriInvoke('read_config_file', { relativePath: 'configs/global.json' })
    if (globalCfg) {
      if (globalCfg.log_level !== undefined) settings.logLevel = globalCfg.log_level
      if (globalCfg.log_file_level !== undefined) settings.logFileLevel = globalCfg.log_file_level
      if (globalCfg.session_idle_timeout_sec !== undefined) settings.sessionIdleTimeoutSec = Number(globalCfg.session_idle_timeout_sec)
      if (globalCfg.default_city !== undefined) settings.defaultCity = globalCfg.default_city
      if (globalCfg.voiceprint_server_url !== undefined) settings.voiceprintServerUrl = globalCfg.voiceprint_server_url
      if (globalCfg.backend_url !== undefined) settings.backendUrl = globalCfg.backend_url
      if (globalCfg.visual_terminal !== undefined) settings.visualTerminal = globalCfg.visual_terminal
      if (globalCfg.ui_type !== undefined) settings.visualTerminal = globalCfg.ui_type
    }
  } catch (e) {
    console.warn('[config] 读 global.json 失败:', e)
  }

  // 1.2 读取 frontend_config.json 前端偏好配置
  try {
    const feCfg = await tauriInvoke('read_config_file', { relativePath: 'configs/frontend_config.json' })
    if (feCfg) {
      if (feCfg.start_fullscreen !== undefined) isStartFullscreen.value = Boolean(feCfg.start_fullscreen)
      if (feCfg.show_weather_card !== undefined) settings.showWeatherCard = Boolean(feCfg.show_weather_card)
    }
  } catch (e) {
    console.warn('[config] 读 frontend_config.json 失败:', e)
  }

  // 1.5 读取 kws_config.json 专属唤醒词配置
  try {
    const kwsCfg = await tauriInvoke('read_config_file', { relativePath: 'configs/kws_config.json' })
    if (kwsCfg) {
      if (kwsCfg.wake_word !== undefined) settings.wakeWord = kwsCfg.wake_word
      if (kwsCfg.sherpa_model_dir !== undefined) settings.modelDir = kwsCfg.sherpa_model_dir
      if (kwsCfg.kws_max_active_paths !== undefined) settings.kwsMaxActivePaths = Number(kwsCfg.kws_max_active_paths)
      if (kwsCfg.kws_num_trailing_blanks !== undefined) settings.kwsNumTrailingBlanks = Number(kwsCfg.kws_num_trailing_blanks)
      if (kwsCfg.kws_score !== undefined) settings.kwsScore = Number(kwsCfg.kws_score)
      if (kwsCfg.kws_threshold !== undefined) settings.kwsThreshold = Number(kwsCfg.kws_threshold)
    }
  } catch (e) {
    console.warn('[config] 读 kws_config.json 失败:', e)
  }

  // 2. 读取 model_config.json 确定当前模型名
  let voiceModelName = settings.voiceModelName
  try {
    const modelCfg = await tauriInvoke('read_config_file', { relativePath: 'configs/model_config.json' })
    if (modelCfg?.realtime_voice?.model_name) {
      voiceModelName = modelCfg.realtime_voice.model_name
      settings.voiceModelName = voiceModelName
    }
  } catch (e) {
    console.warn('[config] 读 model_config.json 失败:', e)
  }

  // 3. 读取当前端到端语音模型的专属配置文件
  if (voiceModelName && voiceModelName !== 'sherpa-local') {
    try {
      const voiceCfg = await tauriInvoke('read_config_file', {
        relativePath: `configs/models/voice_e2e/${voiceModelName}.json`
      })
      if (voiceCfg) {
        const silenceMs = voiceCfg.vad_silence_duration_ms ?? voiceCfg.silence_duration_ms ?? voiceCfg.e2e_silence_duration_ms
        if (silenceMs !== undefined) settings.e2eSilenceDurationMs = Number(silenceMs)
        if (voiceCfg.temperature !== undefined) settings.e2eTemperature = Number(voiceCfg.temperature)
        if (voiceCfg.max_tokens !== undefined) settings.e2eMaxTokens = Number(voiceCfg.max_tokens)
        if (voiceCfg.qwen_audio_turn_mode !== undefined) settings.qwenAudioTurnMode = voiceCfg.qwen_audio_turn_mode
        if (voiceCfg.qwen_audio_vad_threshold !== undefined) settings.qwenAudioVadThreshold = Number(voiceCfg.qwen_audio_vad_threshold)
        if (voiceCfg.qwen_audio_max_history_turns !== undefined) settings.qwenAudioMaxHistoryTurns = Number(voiceCfg.qwen_audio_max_history_turns)
        if (voiceCfg.qwen_audio_voiceprint_mode !== undefined) settings.qwenAudioVoiceprintMode = voiceCfg.qwen_audio_voiceprint_mode
        if (voiceCfg.selected_voiceprint_id !== undefined) settings.selectedVoiceprintId = voiceCfg.selected_voiceprint_id
        if (voiceCfg.stream_asr_enabled !== undefined) settings.streamAsrEnabled = Boolean(voiceCfg.stream_asr_enabled)
        fetchVoices(voiceModelName)
        if (voiceCfg.current_voice !== undefined) settings.voice = voiceCfg.current_voice
        if (voiceCfg.voice_speed !== undefined) settings.voiceSpeed = voiceCfg.voice_speed
        if (voiceCfg.tool_mode !== undefined) settings.voiceModelToolMode = voiceCfg.tool_mode
        if (voiceCfg.qwen_audio_voiceprint_audio_urls !== undefined) {
          const urls = voiceCfg.qwen_audio_voiceprint_audio_urls
          settings.qwenAudioVoiceprintAudioUrls = Array.isArray(urls) ? urls.join('\n') : (urls || '')
        }
        console.log(`[config] 成功从磁盘加载端到端配置 ${voiceModelName}.json, silence_duration_ms=${settings.e2eSilenceDurationMs}`)
      }
    } catch (e) {
      console.warn(`[config] 读 configs/models/voice_e2e/${voiceModelName}.json 失败:`, e)
    }
  }
}

// ── 后端配置拉取（可复用于重连后）
async function fetchBackendConfig() {
  // 无论后端是否成功，优先读取磁盘配置
  await loadDiskConfig()

  try {
    const res = await fetch(settings.backendUrl + "/config")
    if (!res.ok) return false
    const cfg = await res.json()

    // ── 后端独占字段（动态选项列表、唤醒词等前端无法从磁盘计算的数据）──
    if (cfg.text_model_name !== undefined) settings.textModelName = cfg.text_model_name
    if (cfg.voice_cascade_model_name !== undefined) settings.voiceCascadeModelName = cfg.voice_cascade_model_name
    if (cfg.voice_model_name !== undefined) {
      settings.voiceModelName = cfg.voice_model_name
      settings.voiceInteractionStyle = (cfg.voice_model_name === 'sherpa-local') ? 'cascade' : 'e2e'
      await fetchVoices(cfg.voice_model_name)
    }
    if (cfg.text_model_tool_mode !== undefined) settings.textModelToolMode = cfg.text_model_tool_mode
    if (cfg.voice_cascade_model_tool_mode !== undefined) settings.voiceCascadeModelToolMode = cfg.voice_cascade_model_tool_mode
    if (cfg.text_model_tool_style !== undefined) settings.textModelToolStyle = cfg.text_model_tool_style
    if (cfg.voice_cascade_model_tool_style !== undefined) settings.voiceCascadeModelToolStyle = cfg.voice_cascade_model_tool_style
    if (cfg.sherpa_model_dir !== undefined) settings.modelDir = cfg.sherpa_model_dir
    if (cfg.wake_word !== undefined) settings.wakeWord = cfg.wake_word
    if (cfg.asr_mode !== undefined) settings.asrMode = cfg.asr_mode
    if (cfg.cascade_tts_type !== undefined) settings.cascadeTtsType = cfg.cascade_tts_type
    if (cfg.cascade_silence_duration_ms !== undefined) settings.cascadeSilenceDurationMs = cfg.cascade_silence_duration_ms
    if (cfg.cascade_vad_energy_threshold !== undefined) settings.cascadeVadEnergyThreshold = cfg.cascade_vad_energy_threshold
    if (cfg.local_tts_speaker_id !== undefined) settings.localTtsSpeakerId = cfg.local_tts_speaker_id
    if (cfg.local_tts_speed_rate !== undefined) settings.localTtsSpeedRate = cfg.local_tts_speed_rate
    if (cfg.text_model_options !== undefined && Array.isArray(cfg.text_model_options)) { textModelOptions.value = cfg.text_model_options }
    if (cfg.voice_model_options !== undefined && Array.isArray(cfg.voice_model_options)) { voiceModelOptions.value = cfg.voice_model_options }
    if (cfg.kws_model_options !== undefined && Array.isArray(cfg.kws_model_options)) { kwsModelOptions.value = cfg.kws_model_options }
    if (cfg.asr_model_options !== undefined && Array.isArray(cfg.asr_model_options)) { asrModelOptions.value = cfg.asr_model_options }

    // ── 磁盘配置文件可直读字段：仅在非 Tauri 浏览器调试模式下从后端回退读取 ──
    if (!tauriInvoke) {
      if (cfg.enable_visual_broadcast !== undefined) settings.enableVisualBroadcast = cfg.enable_visual_broadcast
      if (cfg.visual_terminal !== undefined) settings.visualTerminal = cfg.visual_terminal
      if (cfg.ui_type !== undefined) settings.visualTerminal = cfg.ui_type
      if (cfg.default_city !== undefined) settings.defaultCity = cfg.default_city
      if (cfg.start_fullscreen !== undefined) isStartFullscreen.value = Boolean(cfg.start_fullscreen)
      if (cfg.log_level !== undefined) settings.logLevel = cfg.log_level
      if (cfg.log_file_level !== undefined) settings.logFileLevel = cfg.log_file_level
      if (cfg.session_idle_timeout_sec !== undefined) settings.sessionIdleTimeoutSec = Number(cfg.session_idle_timeout_sec)
      if (cfg.voice !== undefined) settings.voice = cfg.voice
      if (cfg.voice_speed !== undefined) settings.voiceSpeed = cfg.voice_speed
      if (cfg.voice_model_tool_mode !== undefined) settings.voiceModelToolMode = cfg.voice_model_tool_mode
      if (cfg.e2e_temperature !== undefined) settings.e2eTemperature = cfg.e2e_temperature
      if (cfg.e2e_max_tokens !== undefined) settings.e2eMaxTokens = cfg.e2e_max_tokens
      if (cfg.e2e_silence_duration_ms !== undefined) settings.e2eSilenceDurationMs = cfg.e2e_silence_duration_ms
      if (cfg.qwen_audio_turn_mode !== undefined) settings.qwenAudioTurnMode = cfg.qwen_audio_turn_mode
      if (cfg.qwen_audio_vad_threshold !== undefined) settings.qwenAudioVadThreshold = cfg.qwen_audio_vad_threshold
      if (cfg.qwen_audio_max_history_turns !== undefined) settings.qwenAudioMaxHistoryTurns = cfg.qwen_audio_max_history_turns
      if (cfg.qwen_audio_voiceprint_audio_urls !== undefined) {
        const urls = cfg.qwen_audio_voiceprint_audio_urls
        settings.qwenAudioVoiceprintAudioUrls = Array.isArray(urls) ? urls.join('\n') : (urls || '')
      }
      if (cfg.qwen_audio_voiceprint_mode !== undefined) settings.qwenAudioVoiceprintMode = cfg.qwen_audio_voiceprint_mode
      if (cfg.selected_voiceprint_id !== undefined) settings.selectedVoiceprintId = cfg.selected_voiceprint_id
      if (cfg.stream_asr_enabled !== undefined) settings.streamAsrEnabled = Boolean(cfg.stream_asr_enabled)
    }

    // 独立设置窗口自动在加载时创建快照备份
    if (isSettingsWindow.value) {
      originalSettings.value = JSON.parse(JSON.stringify(settings))
    }
    return true
  } catch (e) {
    return false
  }
}

// ── 后端健康轮询（3秒一次，断线自动重连）
let _healthTimer = null
function startHealthPolling() {
  async function poll() {
    const wasOnline = backendOnline.value
    try {
      const res = await fetch(settings.backendUrl + "/health", { signal: AbortSignal.timeout(2000) })
      backendOnline.value = res.ok
    } catch {
      backendOnline.value = false
    }
    // 检测到从离线→在线，自动重新加载配置
    if (!wasOnline && backendOnline.value) {
      console.log('[backend] 后端重新上线，自动重新拉取配置...')
      await fetchBackendConfig()
    }
    _healthTimer = setTimeout(poll, 3000)
  }
  poll()
}

onMounted(async () => {
  // 初始化拉取后端配置，并启动健康轮询（后端未启动时会持续等待并在上线时自动重连）
  const ok = await fetchBackendConfig()
  backendOnline.value = ok
  if (ok && isQwenAudioModelActive() && settings.qwenAudioVoiceprintMode === 'static') {
    fetchVoiceprints()
  }
  startHealthPolling()

  // 初始化窗口启动全屏适应
  await applyFullscreenState(isStartFullscreen.value)

  // 当选定语音端到端模型改变时，自动重新抓取该模型 json 中定义的 voice_options 列表及其 label
  watch(() => settings.voiceModelName, (newModel) => {
    if (newModel) {
      fetchVoices(newModel)
    }
  }, { immediate: true })

  // 仅在当前模型为 Qwen-Audio 且切换为绑定静态声纹时，按需自动刷新拉取角色列表
  watch([() => settings.voiceModelName, () => settings.qwenAudioVoiceprintMode], ([newModel, newMode]) => {
    if (isQwenAudioModelActive() && newMode === 'static') {
      fetchVoiceprints()
    }
  }, { immediate: true })

  watch(() => settings.modelDir, async (newVal) => {
    if (!newVal || newVal === 'custom') return
    try {
      const res = await fetch(settings.backendUrl + "/config?sherpa_model_dir=" + encodeURIComponent(newVal))
      if (res.ok) {
        const data = await res.json()
        if (data.wake_word) {
          settings.wakeWord = data.wake_word
        }
      }
    } catch (e) {
      console.warn('[config] 切换模型时读取新模型唤醒词失败', e)
    }
  })





  if (window.__TAURI__ || window.__tauri_ipc__) {
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
    await listen('settings-saved', (event) => {
      console.log('[Tauri] 监听到设置已由独立窗口保存并分发:', event.payload)
      const payload = event.payload
      if (payload) {
        Object.keys(payload).forEach(key => {
          const camelKey = key.replace(/_([a-z])/g, (g) => g[1].toUpperCase())
          if (settings[camelKey] !== undefined) {
            settings[camelKey] = payload[key]
          } else if (settings[key] !== undefined) {
            settings[key] = payload[key]
          }
        })
        if (payload.sherpa_model_dir !== undefined) {
          settings.modelDir = payload.sherpa_model_dir
        }
        if (payload.wake_word !== undefined) {
          settings.wakeWord = payload.wake_word
        }
        if (payload.voice !== undefined) {
          settings.voice = payload.voice
        }
        if (payload.voice_speed !== undefined) {
          settings.voiceSpeed = payload.voice_speed
        }
      }
    })
  }
})

// ── 统一全屏状态应用逻辑（优先走 Rust 原生指令，零权限拦截风险）
async function applyFullscreenState(fullscreen) {
  if (isSettingsWindow.value) return
  if (tauriInvoke) {
    try {
      await tauriInvoke('set_fullscreen', { fullscreen })
      console.log(`[Window] 成功设置全屏状态: ${fullscreen}`)
      return
    } catch (e) {
      console.warn('[Window] 通过 Rust 命令设置全屏失败，尝试回退 JS API:', e)
    }
  }
  if (appWindow) {
    try {
      await appWindow.setFullscreen(fullscreen)
    } catch (e) {
      console.warn('[Window] 切换全屏状态失败:', e)
    }
  }
}

// ── Tauri 窗口全屏控制
async function onStartFullscreenChange() {
  await applyFullscreenState(isStartFullscreen.value)
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

// ── 文件夹选择
async function pickDirectory(key) {
  try {
    const selected = await open({
      multiple: false,
      directory: true
    })
    if (selected) {
      settings[key] = selected
    }
  } catch (e) {
    console.error('Directory picker error:', e)
  }
}

function clearChat() {
  messages.value = []
  weatherData.value = null
}

async function saveSettings() {

  // 校验模型名称
  if (!settings.textModelName || settings.textModelName === 'custom') {
    alert('请选择并填写文字对话大模型名')
    return
  }
  if (settings.voiceInteractionStyle === 'cascade') {
    if (!settings.voiceCascadeModelName || settings.voiceCascadeModelName === 'custom') {
      alert('请选择并填写级联语音对话大模型名')
      return
    }
  }
  
  let finalVoiceModel = settings.voiceModelName
  if (settings.voiceInteractionStyle === 'cascade') {
    finalVoiceModel = 'sherpa-local'
  } else {
    if (!settings.voiceModelName || settings.voiceModelName === 'custom' || settings.voiceModelName === 'sherpa-local') {
      alert('请填写端到端实时语音模型名')
      return
    }
  }

  if (settings.voiceModelName && (settings.voiceModelName.includes('qwen-audio-3.0')) && settings.qwenAudioVoiceprintMode === 'static' && !settings.selectedVoiceprintId) {
    alert('请选择您要绑定的声纹！如果尚无声纹，请先点击录制声纹。')
    return
  }

  const backendConfig = {
    default_city: settings.defaultCity,
    text_model_name: settings.textModelName,
    voice_cascade_model_name: settings.voiceCascadeModelName,
    voice_model_name: finalVoiceModel,
    text_model_tool_mode: settings.textModelToolMode,
    voice_cascade_model_tool_mode: settings.voiceCascadeModelToolMode,
    voice_model_tool_mode: settings.voiceModelToolMode,
    text_model_tool_style: settings.textModelToolStyle,
    voice_cascade_model_tool_style: settings.voiceCascadeModelToolStyle,
    enable_visual_broadcast: settings.enableVisualBroadcast,
    visual_terminal: settings.visualTerminal,
    start_fullscreen: isStartFullscreen.value,
    show_weather_card: settings.showWeatherCard,
    kws_max_active_paths: settings.kwsMaxActivePaths,
    kws_num_trailing_blanks: settings.kwsNumTrailingBlanks,
    kws_score: settings.kwsScore,
    kws_threshold: settings.kwsThreshold,
    voiceprint_server_url: settings.voiceprintServerUrl,
    backend_url: settings.backendUrl,
    sherpa_model_dir: settings.modelDir,
    wake_word: settings.wakeWord,
    voice: settings.voice,
    voice_speed: settings.voiceSpeed,
    asr_mode: settings.asrMode,
    local_tts_speaker_id: settings.localTtsSpeakerId,
    cascade_tts_type: settings.cascadeTtsType,
    local_tts_speed_rate: settings.localTtsSpeedRate,
    e2e_temperature: settings.e2eTemperature,
    e2e_max_tokens: settings.e2eMaxTokens,
    e2e_silence_duration_ms: settings.e2eSilenceDurationMs,
    cascade_silence_duration_ms: settings.cascadeSilenceDurationMs,
    cascade_vad_energy_threshold: settings.cascadeVadEnergyThreshold,
    qwen_audio_turn_mode: settings.qwenAudioTurnMode,
    qwen_audio_vad_threshold: settings.qwenAudioVadThreshold,
    qwen_audio_max_history_turns: settings.qwenAudioMaxHistoryTurns,
    qwen_audio_voiceprint_audio_urls: settings.qwenAudioVoiceprintAudioUrls
      ? settings.qwenAudioVoiceprintAudioUrls.split('\n').map(u => u.trim()).filter(Boolean)
      : [],
    qwen_audio_voiceprint_mode: settings.qwenAudioVoiceprintMode,
    selected_voiceprint_id: settings.selectedVoiceprintId,
    stream_asr_enabled: settings.streamAsrEnabled,
    log_level: settings.logLevel,
    log_file_level: settings.logFileLevel,
    session_idle_timeout_sec: Number(settings.sessionIdleTimeoutSec || 30)
  }

  showSettings.value = false
  try {
    const res = await fetch(settings.backendUrl + "/config", {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(backendConfig)
    })
    if (res.ok) {
      console.log('[Settings] 保存配置至后端成功')
      if (tauriInvoke) {
        try {
          // 通过 Rust 代理广播 settings-saved 事件，绕过 settings 窗口的 emit 权限限制
          await tauriInvoke('emit_settings_saved', { payload: backendConfig })
        } catch (err) {
          console.warn('[Settings] 调用 Rust 广播中继失败，尝试本地广播:', err)
          if (emitEvent) {
            await emitEvent('settings-saved', backendConfig)
          }
        }
      } else {
        if (emitEvent) {
          await emitEvent('settings-saved', backendConfig)
        }
      }
      
      // 如果是独立设置子窗口，直接自毁关闭
      if (isSettingsWindow.value && appWindow) {
        try {
          await appWindow.close()
        } catch (closeErr) {
          console.warn('[Settings] 尝试关闭设置窗口失败:', closeErr)
        }
      }
    } else {
      console.warn('[Settings] 保存配置至后端失败')
    }
  } catch (e) {
    console.error('[Settings] 保存配置网络连接异常:', e)
  }
}

async function openSettingsWindow() {
  originalSettings.value = JSON.parse(JSON.stringify(settings))
  if (tauriInvoke && typeof window !== 'undefined' && (window.__TAURI__ || window.__tauri_ipc__)) {
    try {
      await tauriInvoke('open_settings_window')
      return
    } catch (e) {
      console.warn('[Tauri] Rust 侧创建原生独立窗口失败，切换至 Modal 弹窗降级:', e)
    }
  }
  showSettings.value = true
}

async function closeSettingsWindow() {
  const hasChanges = originalSettings.value && JSON.stringify(settings) !== JSON.stringify(originalSettings.value)
  if (hasChanges) {
    const confirmClose = confirm('您有未保存的修改，确定要放弃修改并退出吗？')
    if (!confirmClose) {
      return // 留在设置页面
    }
    // 确定放弃，将配置还原到备份状态
    Object.assign(settings, originalSettings.value)
  }

  if (isSettingsWindow.value) {
    // 独立设置窗口：多重策略关闭
    try {
      if (tauriInvoke) {
        await tauriInvoke('close_settings_window')
        return
      }
    } catch (e) {
      console.warn('[Settings] Rust close_settings_window failed:', e)
    }
    try {
      if (appWindow) {
        await appWindow.close()
        return
      }
    } catch (e) {
      console.warn('[Settings] appWindow.close() failed:', e)
    }
    try { window.close() } catch {}
  } else {
    showSettings.value = false
  }
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
.bg-mesh { 
  position: fixed; inset: 0; pointer-events: none; z-index: 0; overflow: hidden; 
  background: radial-gradient(circle at 50% 50%, #060911 0%, #03050a 100%);
}
.bg-mesh::after {
  content: '';
  position: absolute;
  inset: 0;
  background-image: 
    linear-gradient(rgba(255, 255, 255, 0.007) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.007) 1px, transparent 1px);
  background-size: 40px 40px;
  z-index: 1;
}
.orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(120px);
  opacity: 0.85;
}
.orb-1 {
  width: 650px; height: 650px;
  top: -200px; right: -100px;
  background: radial-gradient(circle, rgba(99,179,237,0.12) 0%, transparent 70%);
  animation: float 22s ease-in-out infinite alternate;
}
.orb-2 {
  width: 550px; height: 550px;
  bottom: -150px; left: -100px;
  background: radial-gradient(circle, rgba(167,139,250,0.1) 0%, transparent 70%);
  animation: float 28s ease-in-out infinite alternate-reverse;
}
@keyframes float {
  0% { transform: translate(0,0) scale(1); }
  100% { transform: translate(30px,-40px) scale(1.08); }
}

/* ── 工具栏 */
.toolbar {
  position: relative; z-index: 10;
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 24px;
  background: rgba(10, 16, 28, 0.45);
  backdrop-filter: blur(30px) saturate(1.7);
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  flex-shrink: 0;
  box-shadow: 0 4px 30px rgba(0, 0, 0, 0.2);
}
.toolbar-brand { display: flex; align-items: center; gap: 10px; }
.brand-logo {
  width: 34px; height: 34px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  transition: all var(--transition-fast);
}
.brand-logo:hover {
  border-color: rgba(99, 179, 237, 0.3);
  box-shadow: 0 0 12px rgba(99, 179, 237, 0.15);
  transform: translateY(-0.5px);
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
  color: var(--text-muted);
  transition: all var(--transition-fast);
  position: relative;
  overflow: visible;
}
.btn-clear .trash-svg {
  overflow: visible;
}
.btn-clear .trash-lid {
  transform-origin: 12px 6px;
  transition: transform 0.22s cubic-bezier(0.34, 1.56, 0.64, 1), color 0.2s ease;
}
.btn-clear:hover .trash-lid {
  transform: translateY(-2.5px) rotate(-10deg);
  color: #ef4444;
}
.btn-clear .trash-can {
  transition: transform 0.22s cubic-bezier(0.34, 1.56, 0.64, 1), color 0.2s ease;
}
.btn-clear:hover .trash-can {
  color: #ef4444;
}
.btn-clear:active .trash-can {
  transform: scaleY(0.85);
  transform-origin: bottom;
}
.btn-clear:hover {
  border-color: rgba(239, 68, 68, 0.35) !important;
  background: rgba(239, 68, 68, 0.08) !important;
  box-shadow: 0 0 10px rgba(239, 68, 68, 0.15);
}

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
  padding: 32px 24px;
  display: flex; flex-direction: column; gap: 20px;
  scroll-behavior: smooth;
}

/* ── 空对话极简内嵌提示 */
.empty-chat-placeholder {
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; flex: 1; text-align: center; padding: 60px 40px;
  animation: fadeUp 0.5s ease-out;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.04);
  border-radius: var(--radius-lg);
  backdrop-filter: blur(10px);
  margin: auto;
  max-width: 520px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
}

.collapse-handle {
  position: absolute;
  right: 400px;
  top: 50%;
  transform: translate(50%, -50%);
  width: 24px;
  height: 48px;
  border-radius: 12px 0 0 12px;
  background: rgba(15, 23, 42, 0.85);
  border: 1px solid rgba(99, 179, 237, 0.25);
  border-right: none;
  color: var(--accent-blue);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  z-index: 10;
  transition: right 0.4s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.4s ease, background var(--transition-fast), border-color var(--transition-fast);
  box-shadow: -4px 0 10px rgba(0, 0, 0, 0.3);
  backdrop-filter: blur(10px);
  opacity: 1;
}
.collapse-handle:hover {
  background: rgba(99, 179, 237, 0.15);
  border-color: rgba(99, 179, 237, 0.5);
}
.collapse-handle span {
  display: inline-block;
  transition: transform 0.3s;
}
.collapse-handle:hover span {
  transform: translateX(2px);
}
.collapse-handle.is-collapsed:hover span {
  transform: translateX(-2px);
}

.collapse-handle.is-collapsed {
  right: 0;
  opacity: 1;
  pointer-events: auto;
}
.empty-icon {
  width: 56px; height: 56px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: var(--radius-md);
  display: flex; align-items: center; justify-content: center;
  margin-bottom: 16px;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.2);
}
.empty-title {
  font-family: var(--font-display); 
  font-size: 1.15rem; 
  font-weight: 600;
  margin-bottom: 6px;
  background: var(--accent-gradient);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}
.empty-subtitle { 
  color: var(--text-muted); 
  font-size: 0.8rem; 
  margin-bottom: 20px; 
  line-height: 1.5;
}
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
  padding: 24px 32px 32px;
  background: rgba(10, 16, 28, 0.45);
  backdrop-filter: blur(30px) saturate(1.7);
  border-top: 1px solid rgba(255, 255, 255, 0.05);
  flex-shrink: 0;
  box-shadow: 0 -4px 30px rgba(0, 0, 0, 0.15);
}
.input-wrapper {
  display: flex; align-items: flex-end; gap: 12px;
  background: rgba(8, 12, 20, 0.65);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: var(--radius-lg);
  padding: 10px 10px 10px 20px;
  transition: border-color 0.3s ease, box-shadow 0.3s ease, background 0.3s ease;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
  max-width: 860px;
  margin: 0 auto;
}
.input-wrapper.focused {
  border-color: rgba(99,179,237,0.35);
  background: rgba(8, 12, 20, 0.85);
  box-shadow: 0 0 20px rgba(99, 179, 237, 0.12), 0 4px 20px rgba(0, 0, 0, 0.3);
}
textarea {
  flex: 1; background: none; border: none; outline: none;
  color: var(--text-primary); font-family: var(--font-sans);
  font-size: 1.05rem; resize: none;
  min-height: 28px; max-height: 160px;
  padding: 8px 0; line-height: 1.6;
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
/* ── 模态弹窗 */
.modal-overlay {
  position: fixed; inset: 0; z-index: 100;
  background: rgba(0,0,0,0.6); backdrop-filter: blur(12px);
  display: flex; align-items: center; justify-content: center;
}
.settings-dialog {
  background: rgba(15, 23, 42, 0.85) !important;
  border: 1px solid rgba(255, 255, 255, 0.08) !important;
  border-radius: var(--radius-xl);
  padding: 0 !important;
  width: 90%;
  max-width: 640px;
  height: 520px;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.6);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  backdrop-filter: blur(25px) saturate(1.5);
}
.settings-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 24px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.settings-header h3 {
  font-family: var(--font-display);
  font-size: 1.05rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}
.btn-close-modal {
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 1.2rem;
  cursor: pointer;
  padding: 4px;
  line-height: 1;
  transition: color 0.2s;
}
.btn-close-modal:hover {
  color: #ff4d4f;
}
.settings-container {
  flex: 1;
  display: flex;
  overflow: hidden;
}
.settings-sidebar {
  width: 170px;
  background: rgba(8, 12, 20, 0.5);
  border-right: 1px solid rgba(255, 255, 255, 0.05);
  padding: 16px 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.tab-btn {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 10px 14px;
  background: none;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  font-size: 0.85rem;
  font-family: var(--font-sans);
  cursor: pointer;
  text-align: left;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}
.tab-btn:hover {
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-primary);
}
.tab-btn.active {
  background: rgba(99, 179, 237, 0.08);
  color: var(--accent-blue);
  font-weight: 500;
}
.tab-icon {
  font-size: 1rem;
}
.settings-content {
  flex: 1;
  padding: 24px;
  overflow-y: auto;
  background: transparent;
}
.tab-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
}
.scrollable-panel {
  overflow-y: auto;
  padding-right: 4px;
}
.scrollable-panel::-webkit-scrollbar {
  width: 4px;
}
.scrollable-panel::-webkit-scrollbar-thumb {
  background: rgba(255,255,255,0.1);
  border-radius: 2px;
}
.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.form-label {
  font-size: 0.8rem;
  font-weight: 500;
  color: var(--text-secondary);
}
.form-input, .form-select {
  background: rgba(8, 12, 20, 0.65);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: var(--text-primary);
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  font-family: var(--font-sans);
  font-size: 0.85rem;
  outline: none;
  transition: all 0.2s;
}
.form-input:focus, .form-select:focus {
  border-color: rgba(99, 179, 237, 0.35);
  background: rgba(8, 12, 20, 0.85);
  box-shadow: 0 0 0 3px rgba(99, 179, 237, 0.06);
}
.form-help {
  font-size: 0.72rem;
  color: var(--text-muted);
  line-height: 1.35;
}
.input-readonly-wrapper {
  position: relative;
  display: flex;
  align-items: center;
}
.input-readonly-wrapper input {
  padding-right: 32px;
  width: 100%;
}
.lock-icon {
  position: absolute;
  right: 12px;
  font-size: 0.85rem;
  color: var(--text-muted);
  cursor: help;
}
.form-input.disabled {
  opacity: 0.6;
  cursor: not-allowed;
  background: rgba(255, 255, 255, 0.02);
}
.input-with-btn {
  display: flex;
  gap: 8px;
}
.input-with-btn input {
  flex: 1;
}
.input-with-btn button {
  padding: 0 12px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  cursor: pointer;
  transition: all 0.2s;
}
.input-with-btn button:hover {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(99, 179, 237, 0.3);
}
.settings-fieldset {
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: var(--radius-md);
  padding: 16px;
  background: rgba(255, 255, 255, 0.01);
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.fieldset-legend {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--accent-blue);
  padding: 0 8px;
}
.select-editable-wrapper {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.custom-input {
  animation: fadeUp 0.2s ease-out;
}
.radio-group {
  display: flex;
  gap: 16px;
  padding: 4px 0;
}
.radio-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.82rem;
  color: var(--text-primary);
  cursor: pointer;
  user-select: none;
}
.radio-label input {
  cursor: pointer;
  accent-color: var(--accent-blue);
}
.checkbox-group {
  padding: 8px 0;
}
.form-checkbox {
  width: 16px;
  height: 16px;
  cursor: pointer;
  accent-color: var(--accent-blue);
}
.checkbox-title {
  font-size: 0.85rem;
  font-weight: 500;
  color: var(--text-primary);
  cursor: pointer;
  user-select: none;
}
.checkbox-desc {
  margin-top: 8px;
  margin-left: 26px;
  font-size: 0.75rem;
  color: var(--text-muted);
  line-height: 1.45;
}
.settings-dialog-actions {
  padding: 16px 24px;
  background: rgba(8, 12, 20, 0.4);
  border-top: 1px solid rgba(255, 255, 255, 0.05);
  margin-top: 0 !important;
}
.btn-cancel {
  padding: 8px 16px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 0.82rem;
  transition: all 0.2s;
}
.btn-cancel:hover {
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-primary);
}
.btn-save {
  padding: 8px 20px;
  background: var(--accent-gradient);
  border: none;
  border-radius: var(--radius-sm);
  color: #080c14;
  font-weight: 600;
  cursor: pointer;
  font-size: 0.82rem;
  box-shadow: 0 4px 12px rgba(99, 179, 237, 0.15);
  transition: all 0.2s;
}
.btn-save:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(99, 179, 237, 0.25);
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

/* ── 调试侧边栏 */
.debug-panel {
  position: relative;
  width: 400px;
  background: rgba(10, 16, 28, 0.75);
  backdrop-filter: blur(25px) saturate(1.5);
  border-left: 1px solid rgba(99, 179, 237, 0.15);
  display: flex;
  flex-direction: column;
  height: 100%;
  flex-shrink: 0;
  z-index: 5;
  box-shadow: -10px 0 30px rgba(0, 0, 0, 0.5);
  transition: width 0.4s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.4s ease, border-color 0.4s ease;
  opacity: 1;
  overflow: hidden;
}

.debug-panel.is-collapsed {
  width: 0;
  opacity: 0;
  pointer-events: none;
  border-left-color: transparent;
  box-shadow: none;
}

.debug-inner {
  width: 400px;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.debug-header {
  padding: 16px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.debug-header h3 {
  font-family: var(--font-display);
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.btn-clear-debug {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 0.9rem;
  transition: color var(--transition-fast);
}

.btn-clear-debug:hover {
  color: #ff4d4f;
}

.debug-content {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.debug-empty {
  color: var(--text-muted);
  font-size: 0.82rem;
  text-align: center;
  margin-top: 40px;
  font-style: italic;
}

.debug-timeline {
  display: flex;
  flex-direction: column;
  gap: 16px;
  position: relative;
}

.debug-timeline::before {
  content: '';
  position: absolute;
  left: 14px;
  top: 10px;
  bottom: 10px;
  width: 1px;
  background: rgba(255, 255, 255, 0.06);
}

.debug-item {
  position: relative;
  padding-left: 32px;
}

.debug-item::before {
  content: '';
  position: absolute;
  left: 10px;
  top: 14px;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.2);
  border: 2px solid rgba(10, 16, 28, 0.8);
  box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.05);
  z-index: 1;
  transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.25s ease;
}

.debug-item:hover::before {
  transform: scale(1.35);
}

/* 步骤条不同状态的亮点边框与呼吸灯效果 */
.debug-item.kws::before { background: #ec4899; box-shadow: 0 0 10px #ec4899, 0 0 20px rgba(236,72,153,0.4); }
.debug-item.stt::before { background: #3b82f6; box-shadow: 0 0 10px #3b82f6, 0 0 20px rgba(59,130,246,0.4); }
.debug-item.intent::before { background: #a855f7; box-shadow: 0 0 10px #a855f7, 0 0 20px rgba(168,85,247,0.4); }
.debug-item.tool_call::before { background: #eab308; box-shadow: 0 0 10px #eab308, 0 0 20px rgba(234,179,8,0.4); }
.debug-item.tool_result::before { background: #22c55e; box-shadow: 0 0 10px #22c55e, 0 0 20px rgba(34,197,94,0.4); }
.debug-item.tts::before { background: #06b6d4; box-shadow: 0 0 10px #06b6d4, 0 0 20px rgba(6,182,212,0.4); }
.debug-item.control::before { background: #f97316; box-shadow: 0 0 10px #f97316, 0 0 20px rgba(249,115,22,0.4); }

.debug-item-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  user-select: none;
  margin-bottom: 6px;
}

.debug-tag {
  font-size: 0.8rem;
  font-weight: 600;
  text-shadow: 0 0 8px currentColor;
}

.kws .debug-tag { color: #f472b6; }
.stt .debug-tag { color: #60a5fa; }
.intent .debug-tag { color: #c084fc; }
.tool_call .debug-tag { color: #facc15; }
.tool_result .debug-tag { color: #4ade80; }
.tts .debug-tag { color: #22d3ee; }
.control .debug-tag { color: #fb923c; }

.debug-time {
  font-size: 0.72rem;
  color: var(--text-muted);
  margin-left: auto;
  margin-right: 8px;
}

.debug-toggle {
  font-size: 0.6rem;
  color: var(--text-muted);
}

.debug-item-body {
  background: rgba(255, 255, 255, 0.015);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: var(--radius-sm);
  padding: 12px 14px;
  font-size: 0.8rem;
  line-height: 1.5;
  backdrop-filter: blur(10px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  transition: all 0.3s ease;
}

.debug-item-body:hover {
  background: rgba(255, 255, 255, 0.03);
  border-color: rgba(255, 255, 255, 0.09);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.25);
}

.debug-text-content {
  color: var(--text-secondary);
}

.debug-meta {
  font-size: 0.75rem;
  color: var(--text-muted);
  margin-bottom: 6px;
}

.debug-meta code {
  color: #facc15;
  background: rgba(234, 179, 8, 0.1);
  padding: 1px 4px;
  border-radius: 3px;
  font-family: monospace;
}

.debug-json-content pre {
  margin: 0;
  padding: 8px;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 4px;
  overflow-x: auto;
  max-height: 250px;
}

.debug-json-content code {
  font-family: Consolas, Monaco, 'Andale Mono', 'Ubuntu Mono', monospace;
  color: #e2e8f0;
  font-size: 0.75rem;
  white-space: pre-wrap;
  word-break: break-all;
}

/* ── 弹窗淡入淡出过渡 */
.fade-enter-active, .fade-leave-active {
  transition: opacity 0.25s ease;
}
.fade-enter-from, .fade-leave-to {
  opacity: 0;
}

@keyframes fadeUp {
  from { opacity: 0; transform: translateY(16px); }
  to   { opacity: 1; transform: translateY(0); }
}

:deep(.partial-text) {
  color: #888;
  font-style: italic;
  transition: color 0.3s;
}

/* ── 状态仪表盘面板（完全对齐设计图参数标贴） ── */
.status-dashboard {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 0 16px;
  flex-shrink: 0;
}

.status-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 16px;
  font-size: 11px;
  font-weight: 600;
  font-family: var(--font-display), var(--font-sans);
  background: rgba(15, 23, 42, 0.55);
  border: 1.5px solid rgba(255, 255, 255, 0.08);
  color: var(--text-secondary);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  backdrop-filter: blur(10px);
}

.status-pill:hover {
  background: rgba(15, 23, 42, 0.7);
  border-color: rgba(255, 255, 255, 0.15);
}

.pill-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.4);
  box-shadow: 0 0 4px rgba(255, 255, 255, 0.2);
  transition: all 0.3s;
}

/* 状态色分流 */
.status-pill.on .pill-dot,
.status-pill.ok .pill-dot {
  background: #4ade80;
  box-shadow: 0 0 8px #4ade80;
}
.status-pill.on,
.status-pill.ok {
  color: #a7f3d0;
  border-color: rgba(52, 211, 153, 0.25);
  background: rgba(52, 211, 153, 0.06);
}

.status-pill.off .pill-dot,
.status-pill.error .pill-dot {
  background: #f87171;
  box-shadow: 0 0 8px #f87171;
  animation: pulse-dot-red 1.5s ease-in-out infinite;
}
.status-pill.off,
.status-pill.error {
  color: #fca5a5;
  border-color: rgba(248, 113, 113, 0.25);
  background: rgba(248, 113, 113, 0.06);
}

.status-pill.active .pill-dot {
  background: #60a5fa;
  box-shadow: 0 0 8px #60a5fa;
  animation: pulse-dot-blue 1.2s ease-in-out infinite;
}
.status-pill.active {
  color: #93c5fd;
  border-color: rgba(96, 165, 250, 0.35);
  background: rgba(96, 165, 250, 0.12);
  box-shadow: 0 0 12px rgba(96, 165, 250, 0.2);
}

@keyframes pulse-dot-red {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%       { opacity: 0.45; transform: scale(0.75); }
}

@keyframes pulse-dot-blue {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%       { opacity: 0.45; transform: scale(0.8); }
}

.girl-logo-img {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  object-fit: cover;
  border: 1px solid rgba(255, 255, 255, 0.15);
  box-shadow: 0 0 8px rgba(99, 179, 237, 0.25);
  transition: transform 0.3s ease;
}
.toolbar-brand:hover .girl-logo-img {
  transform: scale(1.1) rotate(5deg);
}

.girl-placeholder-img {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  object-fit: cover;
  border: 1px solid rgba(255, 255, 255, 0.1);
  box-shadow: 0 0 10px rgba(99, 179, 237, 0.3);
}

/* ── 独立设置窗口专属满屏样式 */
.independent-settings-root {
  position: fixed;
  inset: 0;
  background: #080b13; /* 精致暗夜黑 */
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  padding: 0;
  margin: 0;
}

.independent-settings-dialog {
  width: 100vw !important;
  height: 100vh !important;
  max-width: 100vw !important;
  max-height: 100vh !important;
  border-radius: 0 !important;
  border: none !important;
  background: #080b13 !important;
  box-shadow: none !important;
  display: flex;
  flex-direction: column;
  margin: 0 !important;
}

/* 对大屏下主对话框的宽度拉伸与居中优化 */
.messages > * {
  max-width: 860px;
  width: 100%;
  margin-left: auto;
  margin-right: auto;
}

.empty-chat-placeholder {
  max-width: 640px !important; /* 放大空状态引导卡片 */
  padding: 80px 60px !important;
}

.brand-name {
  font-size: 1.15rem !important; /* 放大标志字号 */
}

/* 独立设置小窗滚动条优化 */
.scrollable-panel {
  max-height: calc(100vh - 120px) !important;
  overflow-y: auto;
  padding-right: 8px;
}

.scrollable-panel::-webkit-scrollbar {
  width: 5px;
}
.scrollable-panel::-webkit-scrollbar-track {
  background: transparent;
}
.scrollable-panel::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.1);
  border-radius: 3px;
}
.scrollable-panel::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.2);
}

/* ── 唤醒词文本框 */
.wake-word-textarea {
  resize: vertical !important;
  min-height: 200px;
  width: 100% !important;
  line-height: 1.6;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 12.5px;
  white-space: pre;
  overflow: auto;
}

/* ── 声纹录制按键与波形动画 ── */
.btn-record {
  display: flex;
  align-items: center;
  justify-content: center;
  outline: none;
}
.btn-record:hover {
  transform: scale(1.08);
  box-shadow: 0 0 25px rgba(0, 229, 255, 0.4) !important;
}
.btn-record:active {
  transform: scale(0.95);
}
.btn-record.stop-rec:hover {
  box-shadow: 0 0 25px rgba(255, 77, 79, 0.5) !important;
}

@keyframes pulseWave {
  0% {
    transform: scaleY(0.6);
    opacity: 0.5;
  }
  100% {
    transform: scaleY(2.2);
    opacity: 1;
  }
}
</style>
