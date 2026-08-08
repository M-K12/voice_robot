from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
)
from qfluentwidgets import CardWidget, TitleLabel, BodyLabel, CaptionLabel, IconWidget, FluentIcon as FIF


class StatusPillLabel(QLabel):
    """单只动态胶囊微型标贴 (完全参照 App.vue .status-pill 样式)"""
    def __init__(self, text: str, status_type: str = "ok", parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self.setFixedWidth(85)
        self.setAlignment(Qt.AlignCenter)
        self.update_status(text, status_type)

    def update_status(self, text: str, status_type: str):
        styles = {
            "ok": "background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4); font-size: 11px; font-weight: 700; border-radius: 11px;",
            "active": "background: rgba(124, 58, 237, 0.2); color: #8b5cf6; border: 1px solid rgba(124, 58, 237, 0.5); font-size: 11px; font-weight: 800; border-radius: 11px;",
            "error": "background: rgba(239, 68, 68, 0.18); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.4); font-size: 11px; font-weight: 700; border-radius: 11px;",
            "off": "background: rgba(100, 116, 139, 0.18); color: #64748b; border: 1px solid rgba(100, 116, 139, 0.35); font-size: 11px; font-weight: 600; border-radius: 11px;",
        }
        self.setStyleSheet(styles.get(status_type, styles["ok"]))
        self.setText(text)


class WeatherCardWidget(CardWidget):
    """
    顶部天气与状态综合展板卡片控件
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(110)
        self.setStyleSheet("CardWidget { border-radius: 12px; background: rgba(255, 255, 255, 0.6); }")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 18, 10)
        layout.setSpacing(14)

        # 1. 最左侧：三行垂直排列的状态仪表盘区域
        status_box = QVBoxLayout()
        status_box.setSpacing(4)
        status_box.setAlignment(Qt.AlignVCenter)

        self.backend_pill = StatusPillLabel("后端 OFF", "off", self)
        self.backend_pill.setToolTip("FastAPI 后端 WebSocket 与 HTTP 健康探针")
        status_box.addWidget(self.backend_pill)

        self.mic_pill = StatusPillLabel("麦克风 ON", "ok", self)
        self.mic_pill.setToolTip("麦克风音频采集设备状态")
        status_box.addWidget(self.mic_pill)

        self.speaker_pill = StatusPillLabel("扬声器 ON", "ok", self)
        self.speaker_pill.setToolTip("纯净高保真语音播报引擎状态")
        status_box.addWidget(self.speaker_pill)

        layout.addLayout(status_box)

        # 2. 半透明竖向分割线
        v_line = QFrame(self)
        v_line.setFrameShape(QFrame.VLine)
        v_line.setFrameShadow(QFrame.Sunken)
        v_line.setStyleSheet("background-color: rgba(125, 125, 125, 0.2); width: 1px; border: none;")
        layout.addWidget(v_line)

        # 3. 天气图标
        self.icon_widget = IconWidget(FIF.CLOUD, self)
        self.icon_widget.setFixedSize(44, 44)
        layout.addWidget(self.icon_widget)

        # 4. 中间城市与描述
        mid_layout = QVBoxLayout()
        mid_layout.setSpacing(2)
        mid_layout.setAlignment(Qt.AlignVCenter)
        self.label_city = TitleLabel("歙县", self)
        self.label_city.setStyleSheet("font-size: 18px; font-weight: bold;")
        self.label_desc = BodyLabel("晴朗 · 风向西南 2级", self)
        self.label_desc.setStyleSheet("color: #666666;")
        mid_layout.addWidget(self.label_city)
        mid_layout.addWidget(self.label_desc)
        layout.addLayout(mid_layout)

        layout.addStretch()

        # 5. 右侧温度大字
        right_layout = QVBoxLayout()
        right_layout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.label_temp = TitleLabel("25°C", self)
        self.label_temp.setStyleSheet("font-size: 28px; font-weight: bold; color: #0082c8;")
        self.label_sub = CaptionLabel("湿度: 65%", self)
        right_layout.addWidget(self.label_temp)
        right_layout.addWidget(self.label_sub)
        layout.addLayout(right_layout)

    def update_weather(self, data: dict):
        city = data.get("city", "歙县")
        temp = data.get("temp", "25")
        desc = data.get("text", "晴朗")
        humidity = data.get("humidity", "65%")

        self.label_city.setText(city)
        self.label_temp.setText(f"{temp}°C")
        self.label_desc.setText(desc)
        self.label_sub.setText(f"湿度: {humidity}")

    def set_backend_online(self, online: bool):
        """更新后端服务在线状态 (ON / OFF)"""
        self.backend_pill.update_status("后端 ON" if online else "后端 OFF", "ok" if online else "off")

    def set_mic_ok(self, ok: bool):
        """更新麦克风工作状态 (ON / OFF)"""
        self.mic_pill.update_status("麦克风 ON" if ok else "麦克风 OFF", "ok" if ok else "error")

    def set_speaker_playing(self, playing: bool):
        """更新扬声器播放状态 (PLAY / ON)"""
        self.speaker_pill.update_status("扬声器 PLAY" if playing else "扬声器 ON", "active" if playing else "ok")
