import os
import sys
import glob
import json
from loguru import logger
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame,
    QTabWidget, QTextEdit, QLabel
)
from qfluentwidgets import (
    MessageBoxBase, SubtitleLabel, CaptionLabel, BodyLabel, LineEdit, ComboBox,
    SwitchButton, DoubleSpinBox, SpinBox, PrimaryPushButton, PushButton,
    FluentIcon as FIF, CardWidget
)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CONFIGS_DIR = os.path.join(PROJECT_ROOT, "configs")
GLOBAL_CONFIG_PATH = os.path.join(CONFIGS_DIR, "global.json")
KWS_CONFIG_PATH = os.path.join(CONFIGS_DIR, "kws_config.json")
MODEL_CONFIG_PATH = os.path.join(CONFIGS_DIR, "model_config.json")
FRONTEND_CONFIG_PATH = os.path.join(CONFIGS_DIR, "frontend_config.json")
MODELS_ROOT_DIR = os.path.join(CONFIGS_DIR, "models")


class SettingFormItem(CardWidget):
    """
    优雅的双栏卡片式表单项，具备精美圆角、自适应边距与齐整对齐
    """
    def __init__(self, label_text: str, widget: QWidget, help_text: str = "", parent=None):
        super().__init__(parent)
        self.setBorderRadius(8)
        
        main_layout = QVBoxLayout(self)
        # 根据是否有帮助提示，动态自适应黄金边距
        top_bottom_margin = 10 if help_text else 8
        main_layout.setContentsMargins(16, top_bottom_margin, 16, top_bottom_margin)
        main_layout.setSpacing(4)

        row_layout = QHBoxLayout()
        row_layout.setSpacing(16)

        # 左侧：标题与帮助说明
        left_layout = QVBoxLayout()
        left_layout.setSpacing(2)

        self.label = BodyLabel(label_text, self)
        self.label.setStyleSheet("font-weight: 600; font-size: 13px; color: #1e293b;")
        left_layout.addWidget(self.label)

        if help_text:
            self.help_label = CaptionLabel(help_text, self)
            self.help_label.setStyleSheet("color: #64748b; font-size: 12px; line-height: 1.4;")
            self.help_label.setWordWrap(True)
            left_layout.addWidget(self.help_label)

        row_layout.addLayout(left_layout, stretch=1)

        # 右侧：输入/开关/下拉控件，精准右对齐
        widget.setMinimumWidth(200)
        row_layout.addWidget(widget, alignment=Qt.AlignRight | Qt.AlignVCenter)

        main_layout.addLayout(row_layout)


class SettingsDialog(MessageBoxBase):
    """
    全量系统设置中心弹窗 (对应 configs/ 目录 4 大根 JSON 与 models/ 专属模型配置文件)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("⚙️ 小安语音机器人 - 全量系统设置中心", self)
        self.titleLabel.setStyleSheet("font-size: 18px; font-weight: 700; color: #0f172a; padding-bottom: 6px;")
        self.viewLayout.addWidget(self.titleLabel)

        self.tab_widget = QTabWidget(self)
        self.tab_widget.setMinimumWidth(820)
        self.tab_widget.setMinimumHeight(580)
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid rgba(0, 0, 0, 0.08);
                border-radius: 10px;
                background: transparent;
            }
            QTabBar::tab {
                font-weight: 600;
                font-size: 13px;
                padding: 8px 18px;
                margin-right: 4px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                color: #475569;
            }
            QTabBar::tab:selected {
                color: #0284c7;
                border-bottom: 2px solid #0284c7;
            }
        """)
        self.viewLayout.addWidget(self.tab_widget)

        # 1. 准确对应读取 configs/ 下的 4 大根 JSON 文件
        self.global_cfg = self._load_json(GLOBAL_CONFIG_PATH)
        self.kws_cfg = self._load_json(KWS_CONFIG_PATH)
        self.model_cfg = self._load_json(MODEL_CONFIG_PATH)
        self.frontend_cfg = self._load_json(FRONTEND_CONFIG_PATH)

        # 2. 动态扫描 configs/models/ 各分类子目录
        self.text_models = self._scan_model_dir("text")
        self.voice_e2e_models = self._scan_model_dir("voice_e2e")
        self.voice_cascade_models = self._scan_model_dir("voice_cascade")
        self.asr_models = self._scan_model_dir("asr")
        self.tts_models = self._scan_model_dir("tts")

        self._init_basic_tab()
        self._init_kws_tab()
        self._init_model_tab()
        self._init_voiceprint_tab()

        # 信号绑定
        self.interaction_style_combo.currentIndexChanged.connect(self._on_style_changed)
        self.e2e_model_combo.currentIndexChanged.connect(self._on_e2e_model_changed)

        self._on_style_changed()

        self.yesButton.setText("保存并应用设置")
        self.cancelButton.setText("取消")

    def _scan_model_dir(self, sub_dir: str) -> dict:
        """从 configs/models/<sub_dir>/*.json 中扫描全部模型与对应的 label/voice_options 等元数据"""
        res = {}
        target_dir = os.path.join(MODELS_ROOT_DIR, sub_dir)
        if os.path.exists(target_dir):
            json_files = glob.glob(os.path.join(target_dir, "*.json"))
            for jf in json_files:
                data = self._load_json(jf)
                model_key = data.get("value") or os.path.splitext(os.path.basename(jf))[0]
                label = data.get("label") or model_key
                res[model_key] = {
                    "file_path": jf,
                    "label": label,
                    "current_voice": data.get("current_voice", ""),
                    "voice_options": data.get("voice_options", []),
                    "data": data
                }
        return res

    def _init_basic_tab(self):
        """Tab 1: 基础设置 (对应 global.json & frontend_config.json)"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(14)
        layout.setContentsMargins(16, 16, 16, 16)

        # global.json -> default_city
        self.city_input = LineEdit(container)
        self.city_input.setText(str(self.global_cfg.get("default_city", "歙县")))
        layout.addWidget(SettingFormItem("默认查询城市", self.city_input))

        # global.json -> backend_url
        self.backend_url_input = LineEdit(container)
        self.backend_url_input.setText(str(self.global_cfg.get("backend_url", "http://127.0.0.1:10850")))
        layout.addWidget(SettingFormItem("Python 后端 API 地址", self.backend_url_input))

        # global.json -> session_idle_timeout_sec
        self.idle_timeout_spin = SpinBox(container)
        self.idle_timeout_spin.setRange(0, 600)
        self.idle_timeout_spin.setValue(int(self.global_cfg.get("session_idle_timeout_sec", 60)))
        layout.addWidget(SettingFormItem("无语音输入自动挂断时长 (秒)", self.idle_timeout_spin))

        # global.json -> enable_visual_broadcast
        self.visual_switch = SwitchButton(container)
        self.visual_switch.setChecked(bool(self.global_cfg.get("enable_visual_broadcast", True)))
        layout.addWidget(SettingFormItem("开启大屏视觉联动推送", self.visual_switch))

        # global.json -> visual_terminal
        self.terminal_combo = ComboBox(container)
        self.terminal_combo.addItem("demo_ui", userData="demo_ui")
        self.terminal_combo.addItem("app_ui", userData="app_ui")
        cur_terminal = str(self.global_cfg.get("visual_terminal", "demo_ui"))
        if cur_terminal == "app_ui":
            self.terminal_combo.setCurrentIndex(1)
        else:
            self.terminal_combo.setCurrentIndex(0)

        layout.addWidget(SettingFormItem("推送的前端终端类型", self.terminal_combo))

        # global.json -> log_level
        self.log_level_combo = ComboBox(container)
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        cur_log_level = str(self.global_cfg.get("log_level", "INFO")).upper()
        if cur_log_level in ["DEBUG", "INFO", "WARNING", "ERROR"]:
            self.log_level_combo.setCurrentText(cur_log_level)
        layout.addWidget(SettingFormItem("控制台输出日志级别", self.log_level_combo))

        # frontend_config.json -> start_fullscreen
        self.fullscreen_switch = SwitchButton(container)
        self.fullscreen_switch.setChecked(bool(self.frontend_cfg.get("start_fullscreen", False)))
        layout.addWidget(SettingFormItem("启动时自动全屏展示", self.fullscreen_switch, help_text="开启后应用启动时自动开启全屏沉浸模式。"))

        # frontend_config.json -> silent_startup
        self.silent_startup_switch = SwitchButton(container)
        self.silent_startup_switch.setChecked(bool(self.frontend_cfg.get("silent_startup", False)))
        layout.addWidget(SettingFormItem("开启静默启动 (后台常驻/托盘极低占用)", self.silent_startup_switch, help_text="开启后启动程序不主动强占弹窗，静默缩小在系统托盘，极大节省 CPU/内存占用。"))

        # frontend_config.json -> global_shortcut
        self.shortcut_input = LineEdit(container)
        self.shortcut_input.setPlaceholderText("例如 Alt+X 或 Ctrl+Alt+A")
        self.shortcut_input.setText(str(self.frontend_cfg.get("global_shortcut", "Alt+X")))
        layout.addWidget(SettingFormItem("唤醒/显示主界面全局快捷键", self.shortcut_input, help_text="系统全局生效。无论焦点在任何应用前台，按下快捷键随时呼出或隐缩主界面。"))

        layout.addStretch()
        scroll.setWidget(container)
        self.tab_widget.addTab(scroll, "🌐 基础设置")

    def _init_kws_tab(self):
        """Tab 2: 唤醒词设置 (对应 kws_config.json)"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(14)
        layout.setContentsMargins(16, 16, 16, 16)

        self.model_dir_input = LineEdit(container)
        self.model_dir_input.setText(str(self.kws_cfg.get("sherpa_model_dir", "sherpa/models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20")))
        layout.addWidget(SettingFormItem("唤醒词 ONNX 模型路径", self.model_dir_input))

        self.wake_word_text = QTextEdit(container)
        self.wake_word_text.setMaximumHeight(120)
        wake_word_val = self.kws_cfg.get("wake_word", "x iǎo ān x iǎo ān :4.0 #0.03 @小安小安\nx iǎo án x iǎo án :3.5 #0.05 @小安小安")
        self.wake_word_text.setPlainText(str(wake_word_val))
        layout.addWidget(SettingFormItem("本地侦听唤醒词配置", self.wake_word_text))

        self.kws_score_spin = DoubleSpinBox(container)
        self.kws_score_spin.setRange(0.5, 5.0)
        self.kws_score_spin.setSingleStep(0.1)
        self.kws_score_spin.setValue(float(self.kws_cfg.get("kws_score", 2.4)))
        layout.addWidget(SettingFormItem(
            "全局 boosting 分数 (keywords_score)", self.kws_score_spin,
            "唤醒词打分加成，越高灵敏度越高。推荐范围：1.0 ~ 3.5"
        ))

        self.kws_threshold_spin = DoubleSpinBox(container)
        self.kws_threshold_spin.setRange(0.01, 0.5)
        self.kws_threshold_spin.setSingleStep(0.01)
        self.kws_threshold_spin.setValue(float(self.kws_cfg.get("kws_threshold", 0.08)))
        layout.addWidget(SettingFormItem(
            "全局触发阈值 (keywords_threshold)", self.kws_threshold_spin,
            "唤醒触发门限，越低灵敏度越高。推荐范围：0.03 ~ 0.15"
        ))

        self.kws_paths_combo = ComboBox(container)
        self.kws_paths_combo.addItems(["2 — 最快，精度略低", "4 — 平衡 (推荐)", "8 — 较慢，精度更高"])
        paths_val = self.kws_cfg.get("kws_max_active_paths", 4)
        if paths_val == 2: self.kws_paths_combo.setCurrentIndex(0)
        elif paths_val == 8: self.kws_paths_combo.setCurrentIndex(2)
        else: self.kws_paths_combo.setCurrentIndex(1)
        layout.addWidget(SettingFormItem("Beam Search 搜索宽度", self.kws_paths_combo))

        self.kws_blanks_combo = ComboBox(container)
        self.kws_blanks_combo.addItems(["0 — 最快响应", "1 — 默认 (推荐)", "2 — 减少截断误判"])
        blanks_val = self.kws_cfg.get("kws_num_trailing_blanks", 1)
        if blanks_val == 0: self.kws_blanks_combo.setCurrentIndex(0)
        elif blanks_val == 2: self.kws_blanks_combo.setCurrentIndex(2)
        else: self.kws_blanks_combo.setCurrentIndex(1)
        layout.addWidget(SettingFormItem("尾部空白帧限制", self.kws_blanks_combo))

        # frontend_config.json -> aec_filter_length
        self.aec_filter_combo = ComboBox(container)
        self.aec_filter_combo.addItem("头戴/耳麦耳机 (16ms)", userData=256)
        self.aec_filter_combo.addItem("笔记本自带麦克风 (64ms)", userData=1024)
        self.aec_filter_combo.addItem("外置音响 + 桌面麦克风 (128ms 推荐)", userData=2048)
        self.aec_filter_combo.addItem("大音量外放 / 房间混响 (256ms)", userData=4096)
        cur_aec_filter = int(self.frontend_cfg.get("aec_filter_length", 2048))
        aec_map = {256: 0, 1024: 1, 2048: 2, 4096: 3}
        self.aec_filter_combo.setCurrentIndex(aec_map.get(cur_aec_filter, 2))
        layout.addWidget(SettingFormItem(
            "AEC 回声消除设备类型",
            self.aec_filter_combo,
            help_text="根据播放设备选择回声消尾时长。耳机选小值，音响外放选大值，防止 AI 说话时误唤醒。"
        ))

        layout.addStretch()
        scroll.setWidget(container)
        self.tab_widget.addTab(scroll, "🔊 唤醒词设置")

    def _init_model_tab(self):
        """Tab 3: 模型与架构设置"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(14)
        layout.setContentsMargins(16, 16, 16, 16)

        # 1. 动态加载通用文字对话大模型
        self.text_model_combo = ComboBox(container)
        t_keys = list(self.text_models.keys()) if self.text_models else ["qwen3.6-flash", "qwen3.5-flash", "qwen-plus"]
        for k in t_keys:
            lbl = self.text_models.get(k, {}).get("label") or k
            self.text_model_combo.addItem(f"{k} ({lbl})" if lbl != k else k, userData=k)

        curr_text = self.model_cfg.get("text_chat", {}).get("model_name", "qwen3.6-flash")
        for idx in range(self.text_model_combo.count()):
            if self.text_model_combo.itemData(idx) == curr_text or curr_text in self.text_model_combo.itemText(idx):
                self.text_model_combo.setCurrentIndex(idx)
                break
        self.text_model_item = SettingFormItem("文字对话大模型", self.text_model_combo)
        layout.addWidget(self.text_model_item)
        if self.frontend_cfg.get("production_mode", False):
            self.text_model_item.hide()

        # 2. 全局架构选择
        self.interaction_style_combo = ComboBox(container)
        self.interaction_style_combo.addItems(["端到端模式 (Voice-to-Voice)", "级联模式 (ASR + LLM + TTS)"])
        style_val = self.global_cfg.get("voice_interaction_style", "e2e")
        self.interaction_style_combo.setCurrentIndex(0 if style_val == "e2e" else 1)
        self.interaction_style_item = SettingFormItem("语音通话模式", self.interaction_style_combo, help_text="端到端：低延迟拟人语音对话；级联：分段处理，支持单机离线。")
        layout.addWidget(self.interaction_style_item)
        if self.frontend_cfg.get("production_mode", False):
            self.interaction_style_item.hide()

        # ═════════════════════════════════════════════════════════════
        # A 方案：端到端模式 (e2e) 专属配置卡片
        # ═════════════════════════════════════════════════════════════
        self.e2e_container = CardWidget(container)
        el = QVBoxLayout(self.e2e_container)
        el.addWidget(SubtitleLabel("🎙️ 语音模型设置", self.e2e_container))

        # 动态扫描 configs/models/voice_e2e/*.json
        self.e2e_model_combo = ComboBox(self.e2e_container)
        e2e_keys = list(self.voice_e2e_models.keys()) if self.voice_e2e_models else [
            "qwen3.5-omni-flash-realtime", "qwen3.5-omni-plus-realtime",
            "qwen-audio-3.0-realtime-flash", "qwen-audio-3.0-realtime-plus", "xunfei-realtime"
        ]
        for k in e2e_keys:
            lbl = self.voice_e2e_models.get(k, {}).get("label") or k
            self.e2e_model_combo.addItem(f"{k} ({lbl})" if lbl != k else k, userData=k)

        current_e2e = self.model_cfg.get("realtime_voice", {}).get("model_name", "qwen3.5-omni-flash-realtime")
        for idx in range(self.e2e_model_combo.count()):
            if self.e2e_model_combo.itemData(idx) == current_e2e or current_e2e in self.e2e_model_combo.itemText(idx):
                self.e2e_model_combo.setCurrentIndex(idx)
                break

        self.e2e_model_item = SettingFormItem("模型选择", self.e2e_model_combo)
        el.addWidget(self.e2e_model_item)
        if self.frontend_cfg.get("production_mode", False):
            self.e2e_model_item.hide()

        # 动态专属音色下拉框 (从当前模型配置中读取)
        self.voice_combo = ComboBox(self.e2e_container)
        self.voice_item_widget = SettingFormItem("音色选择", self.voice_combo)
        el.addWidget(self.voice_item_widget)

        self.interrupt_mode_combo = ComboBox(self.e2e_container)
        self.interrupt_mode_combo.addItems(["仅唤醒词打断 (推荐)", "任意说话即打断 (全双工)"])
        interrupt_val = self.global_cfg.get("interruption_mode", "wake_word_only")
        self.interrupt_mode_combo.setCurrentIndex(0 if interrupt_val == "wake_word_only" else 1)
        el.addWidget(SettingFormItem("播报打断模式", self.interrupt_mode_combo, help_text="仅唤醒词打断可防止杂音误触；任意说话打断即说即切。"))

        # 模型特有参数 (动态根据当前模型展示)
        self.xf_speed_spin = SpinBox(self.e2e_container)
        self.xf_speed_spin.setRange(0, 100)
        self.xf_speed_spin.setValue(50)
        self.xf_item_widget = SettingFormItem("超拟人合成语速 (0~100)", self.xf_speed_spin)
        el.addWidget(self.xf_item_widget)

        self.vad_silence_spin = SpinBox(self.e2e_container)
        self.vad_silence_spin.setRange(100, 3000)
        self.vad_silence_spin.setValue(450)
        self.vad_item_widget = SettingFormItem("VAD 断句时长 (ms)", self.vad_silence_spin)
        el.addWidget(self.vad_item_widget)

        self.vad_threshold_spin = DoubleSpinBox(self.e2e_container)
        self.vad_threshold_spin.setRange(0.01, 1.0)
        self.vad_threshold_spin.setSingleStep(0.05)
        self.vad_threshold_spin.setValue(float(self.global_cfg.get("vad_threshold", 0.5)))
        self.vad_threshold_widget = SettingFormItem(
            "VAD 人声激活门限 (vad_threshold)", self.vad_threshold_spin,
            "0.01~1.0 之间。越高越能抵御背景噪音误触发，越低响应越敏感"
        )
        el.addWidget(self.vad_threshold_widget)

        # Qwen-Audio 3.0 特有参数面板
        self.qwen_sub_card = QWidget(self.e2e_container)
        ql = QVBoxLayout(self.qwen_sub_card)
        ql.setContentsMargins(0, 0, 0, 0)

        self.stream_asr_switch = SwitchButton(self.qwen_sub_card)
        self.stream_asr_switch.setChecked(bool(self.global_cfg.get("stream_asr_enabled", True)))
        ql.addWidget(SettingFormItem("实时语音识别流式推送 (ASR Stream Push)", self.stream_asr_switch))

        self.qwen_history_spin = SpinBox(self.qwen_sub_card)
        self.qwen_history_spin.setRange(1, 50)
        self.qwen_history_spin.setValue(int(self.global_cfg.get("qwen_audio_max_history_turns", 20)))
        ql.addWidget(SettingFormItem("历史对话参考轮数限制 (1~50)", self.qwen_history_spin))

        self.qwen_turn_combo = ComboBox(self.qwen_sub_card)
        self.qwen_turn_combo.addItems([
            "server_vad (声学 VAD 自动检测)",
            "smart_turn (智能语义轮次 - 推荐)",
            "push_to_talk (手动控制 / 手动提交)"
        ])
        turn_mode = self.global_cfg.get("qwen_audio_turn_mode", "smart_turn")
        if turn_mode == "server_vad": self.qwen_turn_combo.setCurrentIndex(0)
        elif turn_mode == "push_to_talk": self.qwen_turn_combo.setCurrentIndex(2)
        else: self.qwen_turn_combo.setCurrentIndex(1)
        ql.addWidget(SettingFormItem("对话交互轮次检测模式", self.qwen_turn_combo))
        el.addWidget(self.qwen_sub_card)

        self.temp_spin = DoubleSpinBox(self.e2e_container)
        self.temp_spin.setRange(0.0, 2.0)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setValue(float(self.model_cfg.get("realtime_voice", {}).get("temperature", 0.7)))
        el.addWidget(SettingFormItem("采样温度 (Temperature)", self.temp_spin))

        self.max_tokens_spin = SpinBox(self.e2e_container)
        self.max_tokens_spin.setRange(1, 4096)
        self.max_tokens_spin.setValue(int(self.model_cfg.get("realtime_voice", {}).get("max_tokens", 512)))
        el.addWidget(SettingFormItem("最大输出 Token 数", self.max_tokens_spin))

        layout.addWidget(self.e2e_container)

        # ═════════════════════════════════════════════════════════════
        # B 方案：级联模式 (cascade) 专属配置卡片
        # ═════════════════════════════════════════════════════════════
        self.cascade_container = CardWidget(container)
        cl = QVBoxLayout(self.cascade_container)
        cl.addWidget(SubtitleLabel("🧩 级联切分模式 (ASR + LLM + TTS) 专属设置", self.cascade_container))

        # 动态扫描 configs/models/voice_cascade/*.json
        self.cascade_model_combo = ComboBox(self.cascade_container)
        vc_keys = list(self.voice_cascade_models.keys()) if self.voice_cascade_models else ["qwen3.6-flash", "qwen3.5-flash"]
        for k in vc_keys:
            lbl = self.voice_cascade_models.get(k, {}).get("label") or k
            self.cascade_model_combo.addItem(f"{k} ({lbl})" if lbl != k else k, userData=k)

        cascade_brain = self.model_cfg.get("cascade_voice", {}).get("brain_model_name", "qwen3.6-flash")
        for idx in range(self.cascade_model_combo.count()):
            if self.cascade_model_combo.itemData(idx) == cascade_brain or cascade_brain in self.cascade_model_combo.itemText(idx):
                self.cascade_model_combo.setCurrentIndex(idx)
                break
        cl.addWidget(SettingFormItem("级联语音对话大模型", self.cascade_model_combo))

        # 动态扫描 configs/models/asr/*.json
        self.cascade_asr_combo = ComboBox(self.cascade_container)
        asr_keys = list(self.asr_models.keys()) if self.asr_models else ["sherpa-local", "xunfei-realtime"]
        for k in asr_keys:
            lbl = self.asr_models.get(k, {}).get("label") or k
            self.cascade_asr_combo.addItem(f"{k} ({lbl})" if lbl != k else k, userData=k)

        asr_val = self.model_cfg.get("cascade_voice", {}).get("asr_mode", "sherpa-local")
        for idx in range(self.cascade_asr_combo.count()):
            if self.cascade_asr_combo.itemData(idx) == asr_val or asr_val in self.cascade_asr_combo.itemText(idx):
                self.cascade_asr_combo.setCurrentIndex(idx)
                break
        cl.addWidget(SettingFormItem("级联 ASR 语音识别引擎", self.cascade_asr_combo))

        # 动态扫描 configs/models/tts/*.json
        self.cascade_tts_combo = ComboBox(self.cascade_container)
        tts_keys = list(self.tts_models.keys()) if self.tts_models else ["sherpa-vits", "edge-tts"]
        for k in tts_keys:
            lbl = self.tts_models.get(k, {}).get("label") or k
            self.cascade_tts_combo.addItem(f"{k} ({lbl})" if lbl != k else k, userData=k)

        tts_val = self.model_cfg.get("cascade_voice", {}).get("tts_engine", "sherpa-vits")
        for idx in range(self.cascade_tts_combo.count()):
            if self.cascade_tts_combo.itemData(idx) == tts_val or tts_val in self.cascade_tts_combo.itemText(idx):
                self.cascade_tts_combo.setCurrentIndex(idx)
                break
        cl.addWidget(SettingFormItem("级联 TTS 语音合成引擎", self.cascade_tts_combo))

        self.tts_speaker_spin = SpinBox(self.cascade_container)
        self.tts_speaker_spin.setRange(0, 173)
        self.tts_speaker_spin.setValue(int(self.model_cfg.get("cascade_voice", {}).get("local_tts_speaker_id", 0)))
        cl.addWidget(SettingFormItem("本地离线 TTS 发音人 ID (0 ~ 173)", self.tts_speaker_spin))

        self.tts_speed_spin = DoubleSpinBox(self.cascade_container)
        self.tts_speed_spin.setRange(0.5, 2.0)
        self.tts_speed_spin.setSingleStep(0.05)
        self.tts_speed_spin.setValue(float(self.model_cfg.get("cascade_voice", {}).get("local_tts_speed_rate", 1.0)))
        cl.addWidget(SettingFormItem("离线 TTS 合成语速 (0.5x ~ 2.0x)", self.tts_speed_spin))

        layout.addWidget(self.cascade_container)

        layout.addStretch()
        scroll.setWidget(container)
        self.tab_widget.addTab(scroll, "📝 模型与架构设置")

    def _init_voiceprint_tab(self):
        """Tab 4: 声纹感知与身份 (对应 global.json)"""
        if self.frontend_cfg.get("production_mode", False):
            return

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(14)
        layout.setContentsMargins(16, 16, 16, 16)

        self.vp_notice_card = CardWidget(container)
        nl = QVBoxLayout(self.vp_notice_card)
        self.vp_notice_label = CaptionLabel("ℹ️ 声纹感知锁定目前仅对 Qwen-Audio 3.0 系列模型生效。", self.vp_notice_card)
        self.vp_notice_label.setStyleSheet("color: #00e5ff; font-weight: 600;")
        nl.addWidget(self.vp_notice_label)
        layout.addWidget(self.vp_notice_card)

        self.vp_mode_combo = ComboBox(container)
        self.vp_mode_combo.addItems([
            "none — 无锁定 (不限制发言人)",
            "dynamic — 自动锁定首位说话人 (首轮通话录音并动态锁定)",
            "static — 绑定已有静态声纹 (精准锁定录制好的声纹特征)"
        ])
        vp_mode = self.global_cfg.get("qwen_audio_voiceprint_mode", "none")
        idx = 0
        if vp_mode == "dynamic": idx = 1
        elif vp_mode == "static": idx = 2
        self.vp_mode_combo.setCurrentIndex(idx)
        layout.addWidget(SettingFormItem("声纹锁定模式 (Voiceprint Lock)", self.vp_mode_combo))

        self.vp_server_input = LineEdit(container)
        self.vp_server_input.setText(str(self.global_cfg.get("voiceprint_server_url", "http://8.141.83.146:8777")))
        layout.addWidget(SettingFormItem("声纹识别服务器 URL", self.vp_server_input))

        layout.addStretch()
        scroll.setWidget(container)
        self.tab_widget.addTab(scroll, "🎙️ 声纹感知与角色")

    def _on_style_changed(self):
        """端到端 (e2e) 与级联 (cascade) 物理显隐切换"""
        is_e2e = (self.interaction_style_combo.currentIndex() == 0)
        self.e2e_container.setVisible(is_e2e)
        self.cascade_container.setVisible(not is_e2e)
        self._on_e2e_model_changed()

    def _on_e2e_model_changed(self):
        """根据选择的端到端模型，动态从 configs/models/voice_e2e/<model>.json 中读取音色与特定特有属性"""
        is_e2e = (self.interaction_style_combo.currentIndex() == 0)
        model_key = self.e2e_model_combo.itemData(self.e2e_model_combo.currentIndex()) or self.e2e_model_combo.currentText()
        model_info = self.voice_e2e_models.get(model_key, {})
        mdata = model_info.get("data", {})

        # 1. 动态填充音色下拉框 (从专属 JSON 中的 voice_options 填充)
        self.voice_combo.clear()
        voice_opts = model_info.get("voice_options", [])
        if voice_opts:
            for v in voice_opts:
                if isinstance(v, dict):
                    lbl = v.get("label") or v.get("value")
                    val = v.get("value")
                else:
                    lbl = str(v)
                    val = str(v)
                self.voice_combo.addItem(f"{val} ({lbl})" if lbl != val else val, userData=val)
        else:
            self.voice_combo.addItems(["default", "cherry", "qwen", "Tina", "Theo Calm"])

        # 还原选中的音色
        curr_v = model_info.get("current_voice") or self.model_cfg.get("realtime_voice", {}).get("voice", "")
        if curr_v:
            for i in range(self.voice_combo.count()):
                if self.voice_combo.itemData(i) == curr_v or curr_v in self.voice_combo.itemText(i):
                    self.voice_combo.setCurrentIndex(i)
                    break

        # 2. 动态决定模型专属特有参数的显隐
        is_xunfei = is_e2e and ("xunfei" in model_key)
        is_qwen_audio = is_e2e and ("qwen-audio" in model_key)
        is_omni = is_e2e and ("omni" in model_key)

        self.xf_item_widget.setVisible(is_xunfei)
        self.vad_item_widget.setVisible(is_omni or is_xunfei)
        self.vad_threshold_widget.setVisible(is_omni or is_xunfei or is_qwen_audio)
        self.qwen_sub_card.setVisible(is_qwen_audio)

        # 填入特定属性值
        if is_xunfei:
            self.xf_speed_spin.setValue(int(mdata.get("voice_speed", 50)))
        if is_omni or is_xunfei:
            self.vad_silence_spin.setValue(int(mdata.get("vad_silence_duration_ms", self.global_cfg.get("vad_silence_duration_ms", 450))))
            self.vad_threshold_spin.setValue(float(mdata.get("vad_threshold", self.global_cfg.get("vad_threshold", 0.5))))

        # 声纹页面提示语动态更新
        if hasattr(self, "vp_notice_label"):
            try:
                if is_qwen_audio:
                    self.vp_notice_label.setText("✅ 当前已选择 Qwen-Audio 3.0 模型，声纹感知处于完全生效状态！")
                    self.vp_notice_label.setStyleSheet("color: #107c41; font-weight: 600;")
                elif is_e2e:
                    self.vp_notice_label.setText(f"ℹ️ 当前端到端模型为 [{model_key}]。注：声纹感知功能专供 Qwen-Audio 3.0 模型有效。")
                    self.vp_notice_label.setStyleSheet("color: #d83b01; font-weight: 600;")
                else:
                    self.vp_notice_label.setText("ℹ️ 当前处于【级联模式】，声纹感知功能处于禁用状态。")
                    self.vp_notice_label.setStyleSheet("color: #888888; font-weight: 600;")
            except Exception:
                pass

    def _load_json(self, path: str) -> dict:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def save_all_settings(self):
        """保存全量配置项，写回 configs/ 下的所有 4 大根 JSON 及专属模型 JSON"""
        # 1. global.json
        self.global_cfg["default_city"] = self.city_input.text().strip()
        self.global_cfg["backend_url"] = self.backend_url_input.text().strip()
        self.global_cfg["session_idle_timeout_sec"] = self.idle_timeout_spin.value()
        self.global_cfg["enable_visual_broadcast"] = self.visual_switch.isChecked()

        terminals = ["demo_ui", "app_ui"]
        selected_terminal = terminals[self.terminal_combo.currentIndex()]
        self.global_cfg["visual_terminal"] = selected_terminal

        styles = ["e2e", "cascade"]
        self.global_cfg["voice_interaction_style"] = styles[self.interaction_style_combo.currentIndex()]

        interrupts = ["wake_word_only", "any_speech"]
        self.global_cfg["interruption_mode"] = interrupts[self.interrupt_mode_combo.currentIndex()]

        self.global_cfg["stream_asr_enabled"] = self.stream_asr_switch.isChecked()
        self.global_cfg["qwen_audio_max_history_turns"] = self.qwen_history_spin.value()
        self.global_cfg["vad_silence_duration_ms"] = self.vad_silence_spin.value()
        self.global_cfg["vad_threshold"] = self.vad_threshold_spin.value()

        turn_modes = ["server_vad", "smart_turn", "push_to_talk"]
        self.global_cfg["qwen_audio_turn_mode"] = turn_modes[self.qwen_turn_combo.currentIndex()]

        vp_modes = ["none", "dynamic", "static"]
        self.global_cfg["qwen_audio_voiceprint_mode"] = vp_modes[self.vp_mode_combo.currentIndex()]
        self.global_cfg["voiceprint_server_url"] = self.vp_server_input.text().strip()
        
        new_log_level = self.log_level_combo.currentText()
        self.global_cfg["log_level"] = new_log_level
        self.global_cfg["log_file_level"] = "DEBUG"
        self._write_json(GLOBAL_CONFIG_PATH, self.global_cfg)

        try:
            logger.remove()
            logger.add(sys.stderr, level=new_log_level)
        except Exception:
            pass

        # 2. frontend_config.json
        self.frontend_cfg["start_fullscreen"] = self.fullscreen_switch.isChecked()
        self.frontend_cfg["silent_startup"] = self.silent_startup_switch.isChecked()
        self.frontend_cfg["global_shortcut"] = self.shortcut_input.text().strip() or "Alt+X"
        self.frontend_cfg["aec_filter_length"] = self.aec_filter_combo.itemData(self.aec_filter_combo.currentIndex())
        self._write_json(FRONTEND_CONFIG_PATH, self.frontend_cfg)

        # 3. kws_config.json & keywords.txt
        self.kws_cfg["sherpa_model_dir"] = self.model_dir_input.text().strip()
        wake_text = self.wake_word_text.toPlainText().strip()
        self.kws_cfg["wake_word"] = wake_text
        self.kws_cfg["kws_score"] = self.kws_score_spin.value()
        self.kws_cfg["kws_threshold"] = self.kws_threshold_spin.value()

        paths_map = [2, 4, 8]
        self.kws_cfg["kws_max_active_paths"] = paths_map[self.kws_paths_combo.currentIndex()]

        blanks_map = [0, 1, 2]
        self.kws_cfg["kws_num_trailing_blanks"] = blanks_map[self.kws_blanks_combo.currentIndex()]
        self._write_json(KWS_CONFIG_PATH, self.kws_cfg)

        model_dir = self.kws_cfg.get("sherpa_model_dir", "")
        if model_dir and wake_text:
            abs_model_dir = os.path.abspath(model_dir)
            if not os.path.isabs(model_dir):
                abs_model_dir = os.path.join(PROJECT_ROOT, model_dir)
            if os.path.exists(abs_model_dir):
                keywords_file_path = os.path.join(abs_model_dir, "keywords.txt")
                try:
                    with open(keywords_file_path, "w", encoding="utf-8") as f:
                        f.write(wake_text + "\n")
                except Exception as e:
                    print(f"同步写入 keywords.txt 异常: {e}")

        # 4. model_config.json
        if "text_chat" not in self.model_cfg: self.model_cfg["text_chat"] = {}
        selected_text_model = self.text_model_combo.itemData(self.text_model_combo.currentIndex()) or self.text_model_combo.currentText()
        self.model_cfg["text_chat"]["model_name"] = selected_text_model

        if "realtime_voice" not in self.model_cfg: self.model_cfg["realtime_voice"] = {}
        selected_e2e_model = self.e2e_model_combo.itemData(self.e2e_model_combo.currentIndex()) or self.e2e_model_combo.currentText()
        self.model_cfg["realtime_voice"]["model_name"] = selected_e2e_model

        selected_voice = self.voice_combo.itemData(self.voice_combo.currentIndex()) or self.voice_combo.currentText()
        self.model_cfg["realtime_voice"]["voice"] = selected_voice
        self.model_cfg["realtime_voice"]["temperature"] = self.temp_spin.value()
        self.model_cfg["realtime_voice"]["max_tokens"] = self.max_tokens_spin.value()

        if "cascade_voice" not in self.model_cfg: self.model_cfg["cascade_voice"] = {}
        selected_cascade_brain = self.cascade_model_combo.itemData(self.cascade_model_combo.currentIndex()) or self.cascade_model_combo.currentText()
        self.model_cfg["cascade_voice"]["brain_model_name"] = selected_cascade_brain

        selected_asr = self.cascade_asr_combo.itemData(self.cascade_asr_combo.currentIndex()) or self.cascade_asr_combo.currentText()
        self.model_cfg["cascade_voice"]["asr_mode"] = selected_asr

        selected_tts = self.cascade_tts_combo.itemData(self.cascade_tts_combo.currentIndex()) or self.cascade_tts_combo.currentText()
        self.model_cfg["cascade_voice"]["tts_engine"] = selected_tts
        self.model_cfg["cascade_voice"]["local_tts_speaker_id"] = self.tts_speaker_spin.value()
        self.model_cfg["cascade_voice"]["local_tts_speed_rate"] = self.tts_speed_spin.value()

        self._write_json(MODEL_CONFIG_PATH, self.model_cfg)

        # 5. 同步更新并写回端到端模型专属配置文件 configs/models/voice_e2e/<model>.json
        if selected_e2e_model in self.voice_e2e_models:
            model_info = self.voice_e2e_models[selected_e2e_model]
            file_path = model_info["file_path"]
            mdata = model_info["data"]
            mdata["current_voice"] = selected_voice
            mdata["temperature"] = self.temp_spin.value()
            mdata["max_tokens"] = self.max_tokens_spin.value()
            if "xunfei" in selected_e2e_model:
                mdata["voice_speed"] = self.xf_speed_spin.value()
            if "omni" in selected_e2e_model or "xunfei" in selected_e2e_model or "qwen-audio" in selected_e2e_model:
                mdata["vad_silence_duration_ms"] = self.vad_silence_spin.value()
                mdata["vad_threshold"] = self.vad_threshold_spin.value()

            self._write_json(file_path, mdata)

    def _write_json(self, path: str, data: dict):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"保存配置文件 {path} 失败: {e}")
