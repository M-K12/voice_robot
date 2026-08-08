import os
import sys
from PySide6.QtCore import Qt, QSize, Signal, Slot, QEvent
from PySide6.QtGui import QIcon, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QSplitter,
    QSystemTrayIcon, QMenu, QApplication
)
from PySide6.QtGui import QIcon, QColor, QAction
from qfluentwidgets import (
    FluentWindow, LineEdit, PrimaryPushButton, PushButton, SubtitleLabel,
    CaptionLabel, CardWidget, FluentIcon as FIF, setTheme, Theme
)

from pyside_app.ui.components.weather_card import WeatherCardWidget
from pyside_app.ui.components.chat_view import ChatViewWidget
from pyside_app.ui.components.wake_indicator import WakeIndicatorWidget
from pyside_app.ui.components.settings_dialog import SettingsDialog
from pyside_app.ui.components.debug_console import DebugConsoleWidget


class MainWindow(FluentWindow):
    """
    语音机器人主窗口 (基于 PyQt-Fluent-Widgets)
    """

    def __init__(self, bot_engine, kws_thread=None, hotkey_mgr=None, parent=None):
        super().__init__(parent)
        self.bot_engine = bot_engine
        self.kws_thread = kws_thread
        self.hotkey_mgr = hotkey_mgr

        self.setWindowTitle("小安语音机器人 v2.0")
        self.resize(1120, 720)
        self.setMinimumSize(960, 640)
        self.tray_icon = None
        self._is_force_quitting = False

        # 默认主题
        setTheme(Theme.AUTO)

        # 构建中央交互面板
        self.main_widget = QWidget(self)
        self.main_widget.setObjectName("mainInterface")
        self.addSubInterface(self.main_widget, FIF.CHAT, "小安语音")

        # 左右双栏可拉伸 Splitter 分屏布局 (支持鼠标左侧自由拖拽控制台宽度)
        root_layout = QHBoxLayout(self.main_widget)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(0)

        self.splitter = QSplitter(Qt.Horizontal, self.main_widget)
        self.splitter.setHandleWidth(8)
        self.splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: transparent;
            }
            QSplitter::handle:hover {
                background-color: rgba(2, 132, 199, 0.35);
                border-radius: 4px;
            }
            QSplitter::handle:pressed {
                background-color: #0284c7;
                border-radius: 4px;
            }
        """)

        left_container = QWidget()
        main_layout = QVBoxLayout(left_container)
        main_layout.setContentsMargins(0, 0, 10, 0)
        main_layout.setSpacing(14)

        # 1. 顶部天气展板 (由 configs/frontend_config.json 中的 show_weather_card 驱动)
        self.weather_card = WeatherCardWidget(self)
        main_layout.addWidget(self.weather_card)

        # 2. 通话与唤醒状态发光展板 (展示休眠中/已唤醒/聆听中/回答中/思考中状态)
        self.wake_indicator = WakeIndicatorWidget(self)
        main_layout.addWidget(self.wake_indicator)

        # 3. 中间对话消息流
        self.chat_view = ChatViewWidget(self)
        main_layout.addWidget(self.chat_view, stretch=1)

        # 4. 底部文本输入区与工具栏 (底座卡片封装，层级一体化)
        self.bottom_input_card = CardWidget(self)
        self.bottom_input_card.setBorderRadius(12)
        input_card_layout = QHBoxLayout(self.bottom_input_card)
        input_card_layout.setContentsMargins(12, 10, 12, 10)
        input_card_layout.setSpacing(10)

        # 清空消息按钮
        self.clear_btn = PushButton("清空", self, icon=FIF.DELETE)
        self.clear_btn.clicked.connect(self._on_clear_clicked)
        input_card_layout.addWidget(self.clear_btn)

        # 设置按钮
        self.settings_btn = PushButton("设置", self, icon=FIF.SETTING)
        self.settings_btn.clicked.connect(self._on_settings_clicked)
        input_card_layout.addWidget(self.settings_btn)

        self.input_edit = LineEdit(self)
        self.input_edit.setPlaceholderText("说说看『小安小安』，或者在这里输入问题...")
        self.input_edit.returnPressed.connect(self._on_send_clicked)
        input_card_layout.addWidget(self.input_edit, stretch=1)

        self.mic_btn = PrimaryPushButton("🎤 开启语音", self)
        self.mic_btn.clicked.connect(self._on_mic_clicked)
        input_card_layout.addWidget(self.mic_btn)

        self.send_btn = PrimaryPushButton("发送", self, icon=FIF.SEND)
        self.send_btn.clicked.connect(self._on_send_clicked)
        input_card_layout.addWidget(self.send_btn)

        main_layout.addWidget(self.bottom_input_card)

        self.splitter.addWidget(left_container)

        # 5. 右侧全链路调试控制台 (可自由向左/向右拖拽拉伸，无最大宽度封顶)
        self.debug_console = DebugConsoleWidget(self)
        self.debug_console.setMinimumWidth(260)
        self.splitter.addWidget(self.debug_console)

        # 设置初始分屏尺寸 (左侧 650px, 右侧 350px) 与伸缩因子
        self.splitter.setSizes([650, 350])
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)

        root_layout.addWidget(self.splitter)

        # 关联后端 Engine 与 KWS 线程信号
        self._connect_signals()

        # 应用 frontend_config.json 里的显隐与全屏控制
        self._apply_frontend_config()

        # 初始化跨平台系统托盘
        self._init_system_tray()

    def _apply_frontend_config(self):
        fcfg_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "configs", "frontend_config.json"))
        if os.path.exists(fcfg_path):
            try:
                with open(fcfg_path, "r", encoding="utf-8") as f:
                    fcfg = json.load(f)
                    if fcfg.get("start_fullscreen", False):
                        if not self.isFullScreen():
                            self.showFullScreen()
                    else:
                        if self.isFullScreen():
                            self.showNormal()
            except Exception:
                pass

    def _connect_signals(self):
        # 1. 关联 BotEngine 的消息和状态
        self.bot_engine.signal_chat_message.connect(self._on_chat_message)
        self.bot_engine.signal_weather_updated.connect(self.weather_card.update_weather)
        self.bot_engine.signal_state_changed.connect(self._on_state_changed)
        self.bot_engine.signal_debug_event.connect(self.debug_console.log_event)

        # 连接三状态仪表盘信号 (位于最上方天气展板最左侧，三行排列)
        self.bot_engine.signal_backend_status.connect(self.weather_card.set_backend_online)
        self.bot_engine.audio_player.signal_speaker_status.connect(self.weather_card.set_speaker_playing)

        # 2. 关联 KWS 唤醒与音量波形
        if self.kws_thread:
            self.kws_thread.signal_volume_rms.connect(self.wake_indicator.set_volume)
            self.kws_thread.signal_kws_detected.connect(self.bot_engine.handle_kws_hit)
            self.kws_thread.signal_status.connect(self._on_kws_status)
            self.kws_thread.signal_audio_pcm.connect(self.bot_engine.handle_pcm_chunk)
            self.kws_thread.signal_mic_status.connect(self.weather_card.set_mic_ok)

        # 3. 极速全量同步初始后端状态 (消除由于信号连接晚于首次探针包导致的 Race Condition)
        self.weather_card.set_backend_online(self.bot_engine.is_backend_online())

    @Slot(str, str)
    def _on_chat_message(self, role: str, text: str):
        if role == "user_stream":
            self.chat_view.update_streaming_message("user", text)
        elif role == "bot_stream":
            self.chat_view.update_streaming_message("bot", text)
        elif role == "user":
            if self.chat_view.last_bubble and self.chat_view.last_sender == "user":
                self.chat_view.last_bubble.set_text(text)
            else:
                self.chat_view.add_message("user", text)
            self.chat_view.last_bubble = None
            self.chat_view.last_sender = None
        elif role == "bot":
            if self.chat_view.last_bubble and self.chat_view.last_sender == "bot":
                self.chat_view.last_bubble.set_text(text)
            else:
                self.chat_view.add_message("bot", text)
            self.chat_view.last_bubble = None
            self.chat_view.last_sender = None

    @Slot(str)
    def _on_state_changed(self, state: str):
        self.wake_indicator.set_bot_state(state)
        if state in ["listening", "speaking", "thinking"]:
            self.mic_btn.setText("🛑 挂断")
        else:
            self.mic_btn.setText("🎤 开启语音")

    @Slot()
    def _on_mic_clicked(self):
        if self.bot_engine.is_in_call():
            self.bot_engine.stop_voice_call()
        else:
            self.bot_engine.start_voice_call()

    @Slot()
    def _on_clear_clicked(self):
        self.chat_view.clear_messages()

    @Slot()
    def _on_settings_clicked(self):
        dialog = SettingsDialog(self)
        if dialog.exec():
            dialog.save_all_settings()
            self._apply_frontend_config()

            # 动态实时写重载快捷键
            if self.hotkey_mgr:
                new_shortcut = dialog.shortcut_input.text().strip() or "Alt+X"
                self.hotkey_mgr.update_shortcut(new_shortcut, target_window=self)

            # 重启 KWS 后台线程使新参数和 keywords.txt 内存重载生效
            if self.kws_thread:
                model_dir = dialog.model_dir_input.text().strip()
                if model_dir:
                    self.kws_thread.model_dir = model_dir
                self.kws_thread.stop()
                self.kws_thread.start()

            city = dialog.city_input.text().strip()
            if city:
                self.bot_engine.handle_user_input(f"已更新系统配置，当前默认查询城市: {city}")

    @Slot()
    def _on_send_clicked(self):
        text = self.input_edit.text().strip()
        if not text:
            return
        self.input_edit.clear()
        self.bot_engine.handle_user_input(text)

    def _on_kws_status(self, status: str):
        if status.startswith("error"):
            self.wake_indicator.set_bot_state("error")
        elif status == "ready":
            self.wake_indicator.set_bot_state("ready")
        elif status == "loading":
            self.wake_indicator.set_bot_state("loading")

    def _init_system_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        self.tray_icon = QSystemTrayIcon(self)
        app_icon = QIcon(FIF.CHAT.icon())
        self.tray_icon.setIcon(app_icon)
        self.tray_icon.setToolTip("小安语音机器人 v2.0")

        tray_menu = QMenu(self)
        action_show = QAction("显示/隐藏小安", self)
        action_show.triggered.connect(self.toggle_visibility)

        action_mic = QAction("开启/挂断语音", self)
        action_mic.triggered.connect(self._on_mic_clicked)

        action_settings = QAction("⚙️ 系统设置", self)
        action_settings.triggered.connect(self._on_settings_clicked)

        action_quit = QAction("🛑 彻底退出", self)
        action_quit.triggered.connect(self._force_quit)

        tray_menu.addAction(action_show)
        tray_menu.addAction(action_mic)
        tray_menu.addAction(action_settings)
        tray_menu.addSeparator()
        tray_menu.addAction(action_quit)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _on_tray_activated(self, reason):
        if reason in [QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick]:
            self.toggle_visibility()

    def toggle_visibility(self):
        """纯粹控制主界面窗口的显示与隐藏 (根据配置恢复尺寸，对语音对话流程 0 干扰)"""
        if self.isVisible() and not self.isMinimized() and self.isActiveWindow():
            self.hide()
        else:
            fcfg_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "configs", "frontend_config.json"))
            is_fullscreen = False
            if os.path.exists(fcfg_path):
                try:
                    with open(fcfg_path, "r", encoding="utf-8") as f:
                        is_fullscreen = bool(json.load(f).get("start_fullscreen", False))
                except Exception:
                    pass

            if is_fullscreen:
                self.showFullScreen()
            else:
                self.showNormal()
                if self.width() < 1000 or self.height() < 650:
                    self.resize(1120, 720)

            self.raise_()
            self.activateWindow()

    def _force_quit(self):
        self._is_force_quitting = True
        self.close()
        QApplication.quit()

    def changeEvent(self, event):
        """点击右上角 '-' 最小化按钮时，拦截并隐缩至系统托盘"""
        if event.type() == QEvent.WindowStateChange and self.isMinimized():
            if QSystemTrayIcon.isSystemTrayAvailable():
                event.ignore()
                self.hide()
                if self.tray_icon:
                    self.tray_icon.showMessage(
                        "小安语音机器人", "已缩进系统托盘后台常驻，快捷键 (默认 Alt+X) 可随时唤醒",
                        QSystemTrayIcon.Information, 2000
                    )
                return
        super().changeEvent(event)

    def closeEvent(self, event):
        """点击右上角 '×' 关闭按钮：永远直接释放所有线程并彻底退出控制台程序"""
        if self.kws_thread:
            self.kws_thread.stop()
        self.bot_engine.close()
        super().closeEvent(event)
        QApplication.quit()
