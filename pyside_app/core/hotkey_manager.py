import os
import sys
import threading
from PySide6.QtCore import QObject, Signal, Slot, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from loguru import logger


class GlobalHotkeyManager(QObject):
    """
    跨平台全局快捷键管理器 (支持 Windows 与 Ubuntu Openbox/X11 环境)。
    具备零崩溃防护与优雅降级。
    """
    signal_hotkey_triggered = Signal()

    def __init__(self, parent=None, shortcut_str: str = "Alt+X"):
        super().__init__(parent)
        self.shortcut_str = shortcut_str
        self.active_shortcut = shortcut_str
        self._keyboard_listener_thread = None
        self._listener_running = False
        self._qt_shortcut = None

    def register_qt_shortcut(self, target_window):
        """为 Qt 主窗口绑定应用级兜底快捷键"""
        try:
            if self._qt_shortcut:
                self._qt_shortcut.deleteLater()
            self._qt_shortcut = QShortcut(QKeySequence(self.active_shortcut), target_window)
            self._qt_shortcut.activated.connect(self._on_hotkey_activated)
            logger.info(f"[HotkeyManager] 已绑定应用级快捷键兜底: '{self.active_shortcut}'")
        except Exception as e:
            logger.warning(f"[HotkeyManager] 绑定应用级快捷键失败: {e}")

    def start_global_listener(self):
        """开启系统级全局热键监听 (跨平台 keyboard 库支持)"""
        if self._listener_running:
            return

        def _listen():
            try:
                import keyboard
                self._listener_running = True
                logger.info(f"[HotkeyManager] ⚡ 成功建立跨平台系统级全局热键监听: '{self.active_shortcut}'")
                
                # 规范化按键名并注册
                hk_name = self.active_shortcut.lower().replace("alt", "alt").replace("ctrl", "ctrl")
                keyboard.add_hotkey(hk_name, self._on_hotkey_activated, suppress=False)
                keyboard.wait()
            except ImportError:
                logger.warning("[HotkeyManager] 未安装 keyboard 模块，已优雅降级为 Qt 应用内快捷键")
            except Exception as e:
                logger.warning(f"[HotkeyManager] 系统级热键注册受限 ({e})，已降级为 Qt 快捷键模式")

        self._keyboard_listener_thread = threading.Thread(target=_listen, daemon=True)
        self._keyboard_listener_thread.start()

    def _on_hotkey_activated(self):
        """热键触发主线程 Signal 回调"""
        logger.info(f"[HotkeyManager] 🔥 全局快捷键被触发: '{self.active_shortcut}'")
        self.signal_hotkey_triggered.emit()

    def stop_global_listener(self):
        """停止系统级全局热键监听"""
        self._listener_running = False
        try:
            import keyboard
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass

    def update_shortcut(self, new_shortcut_str: str, target_window=None):
        """动态修改并实时刷新热键绑定"""
        if not new_shortcut_str or not new_shortcut_str.strip():
            return
        new_shortcut_str = new_shortcut_str.strip()
        if new_shortcut_str == self.active_shortcut:
            return

        logger.info(f"[HotkeyManager] 🔄 快捷键变更: '{self.active_shortcut}' -> '{new_shortcut_str}'")
        self.active_shortcut = new_shortcut_str

        # 1. 尝试清空 keyboard 绑定的热键
        try:
            import keyboard
            keyboard.unhook_all_hotkeys()
            hk_name = self.active_shortcut.lower()
            keyboard.add_hotkey(hk_name, self._on_hotkey_activated, suppress=False)
        except Exception:
            pass

        # 2. 重新注册 Qt 快捷键
        if target_window:
            self.register_qt_shortcut(target_window)
