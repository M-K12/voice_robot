import math
from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QLinearGradient, QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from qfluentwidgets import CardWidget, BodyLabel, CaptionLabel, SubtitleLabel


class WakeIndicatorWidget(CardWidget):
    """
    状态指示展板卡片：展示【休眠中/已唤醒/聆听中/回答中/思考中】发光徽章
    """

    STATE_CONFIG = {
        "idle": {
            "title": "💤 休眠中 (待唤醒)",
            "desc": "喊出『小安小安』即可自动唤醒，或点击右下角 🎤 开启对话",
            "title_color": "#0284c7",
            "bg_style": "background: rgba(2, 132, 199, 0.12); border: 1px solid rgba(2, 132, 199, 0.35);"
        },
        "ready": {
            "title": "💤 休眠中 (就绪)",
            "desc": "『小安』已准备就绪，随时呼唤我",
            "title_color": "#0284c7",
            "bg_style": "background: rgba(2, 132, 199, 0.12); border: 1px solid rgba(2, 132, 199, 0.35);"
        },
        "wake_hit": {
            "title": "🔥 已唤醒 (响应中)",
            "desc": "在呢！小安已响应您的唤醒，请开始说话...",
            "title_color": "#d97706",
            "bg_style": "background: rgba(217, 119, 6, 0.15); border: 1px solid rgba(217, 119, 6, 0.45);"
        },
        "listening": {
            "title": "🎙️ 聆听中...",
            "desc": "小安正在倾听您的说话，您可以随时对话或随时打字...",
            "title_color": "#059669",
            "bg_style": "background: rgba(5, 150, 105, 0.15); border: 1px solid rgba(5, 150, 105, 0.45);"
        },
        "speaking": {
            "title": "🗣️ 小安回答中...",
            "desc": "小安正在播放语音应答，您可以喊『小安小安』随时打断",
            "title_color": "#7c3aed",
            "bg_style": "background: rgba(124, 58, 237, 0.15); border: 1px solid rgba(124, 58, 237, 0.45);"
        },
        "thinking": {
            "title": "🧠 正在思考中...",
            "desc": "大模型正在检索气象知识库与生成推演回答...",
            "title_color": "#0891b2",
            "bg_style": "background: rgba(8, 145, 178, 0.15); border: 1px solid rgba(8, 145, 178, 0.45);"
        },
        "error": {
            "title": "⚠️ 异常与重试",
            "desc": "麦克风或后端服务异常，请检查配置",
            "title_color": "#dc2626",
            "bg_style": "background: rgba(220, 38, 38, 0.15); border: 1px solid rgba(220, 38, 38, 0.45);"
        }
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(68)
        self.setMaximumHeight(74)

        self.volume_level = 0.0
        self.target_volume = 0.0
        self.phase = 0.0
        self.bot_state = "idle"

        # 内部水平布局
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(14)

        # 左侧状态文案容器
        text_layout = QVBoxLayout()
        text_layout.setSpacing(3)

        self.state_title_label = BodyLabel("💤 休眠中 (待唤醒)", self)
        self.state_title_label.setStyleSheet("font-weight: 800; font-size: 15px; color: #0284c7;")
        text_layout.addWidget(self.state_title_label)

        self.state_desc_label = CaptionLabel("喊出『小安小安』即可自动唤醒，或点击右下角 🎤 开启对话", self)
        self.state_desc_label.setStyleSheet("font-size: 12px; font-weight: 500;")
        text_layout.addWidget(self.state_desc_label)

        layout.addLayout(text_layout, stretch=1)

        # 右侧画布容器 (自定义绘制跳动波形与发光灯)
        self.wave_canvas = WaveCanvasWidget(self)
        self.wave_canvas.setFixedSize(140, 44)
        layout.addWidget(self.wave_canvas)

        self.set_bot_state("idle")

    def set_volume(self, norm_volume: float):
        self.wave_canvas.set_volume(norm_volume)

    def set_bot_state(self, state: str):
        self.bot_state = state
        cfg = self.STATE_CONFIG.get(state, self.STATE_CONFIG["idle"])
        self.state_title_label.setText(cfg["title"])
        self.state_title_label.setStyleSheet(f"font-weight: 800; font-size: 15px; color: {cfg['title_color']};")
        self.state_desc_label.setText(cfg["desc"])
        self.setStyleSheet(cfg["bg_style"])
        self.wave_canvas.set_bot_state(state)


class WaveCanvasWidget(QWidget):
    """
    波形与发光呼吸圆圈画布控件
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.volume_level = 0.0
        self.target_volume = 0.0
        self.phase = 0.0
        self.bot_state = "idle"

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_animation)
        self.timer.start(16)

    def set_volume(self, norm_volume: float):
        self.target_volume = max(0.0, min(1.0, norm_volume))

    def set_bot_state(self, state: str):
        self.bot_state = state
        self.update()

    def _update_animation(self):
        self.volume_level += (self.target_volume - self.volume_level) * 0.2
        self.phase += 0.08
        if self.phase > 2 * math.pi:
            self.phase -= 2 * math.pi
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        cy = h / 2.0

        colors = {
            "idle": QColor(2, 132, 199),
            "ready": QColor(2, 132, 199),
            "wake_hit": QColor(217, 119, 6),
            "listening": QColor(5, 150, 105),
            "speaking": QColor(124, 58, 237),
            "thinking": QColor(8, 145, 178),
            "error": QColor(220, 38, 38),
        }
        accent = colors.get(self.bot_state, QColor(2, 132, 199))

        # 绘制 5 根跳动动态波形柱
        bars_count = 5
        bar_width = 4
        gap = 6
        total_w = bars_count * bar_width + (bars_count - 1) * gap
        start_x = w - total_w - 8

        for i in range(bars_count):
            x = start_x + i * (bar_width + gap)
            offset = math.sin(self.phase + i * 0.8) * 0.5 + 0.5
            if self.bot_state in ["listening", "speaking"]:
                bar_h = 6 + self.volume_level * 24 + offset * 10
            elif self.bot_state == "thinking":
                bar_h = 8 + offset * 18
            else:
                bar_h = 4 + offset * 4

            bar_h = min(h - 8, max(4, bar_h))
            y = cy - bar_h / 2.0

            painter.setBrush(QBrush(accent))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(QRectF(x, y, bar_width, bar_h), 2, 2)
