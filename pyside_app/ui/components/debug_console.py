import time
import json
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame, QLabel, QTextEdit
)
from qfluentwidgets import CardWidget, SubtitleLabel, CaptionLabel, BodyLabel, TransparentToolButton, FluentIcon as FIF
from loguru import logger


def format_json(obj) -> str:
    """
    100% 对齐原版 App.vue formatJson 逻辑：
    若为 JSON 字符串，先 json.loads 反序列化，再高保真缩进 format 呈现
    """
    if obj is None:
        return ""
    if isinstance(obj, str):
        try:
            parsed = json.loads(obj)
            return json.dumps(parsed, ensure_ascii=False, indent=2)
        except Exception:
            return obj
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        return str(obj)


class DebugLogItemWidget(QWidget):
    """
    单个调试日志项 (100% 参照原版 App.vue：支持 stt/tts 就地覆盖防刷屏更新，以及 tool_call / tool_result / control 的 JSON 精确展示)
    """

    STEP_MAP = {
        "kws": {"label": "✨ 唤醒监测", "color": "#d97706", "bg": "rgba(217, 119, 6, 0.12)"},
        "interrupt": {"label": "⚡ 语音打断", "color": "#dc2626", "bg": "rgba(220, 38, 38, 0.12)"},
        "stt": {"label": "🎙️ 语音转写", "color": "#059669", "bg": "rgba(5, 150, 105, 0.12)"},
        "intent": {"label": "🧠 意图决策", "color": "#0284c7", "bg": "rgba(2, 132, 199, 0.12)"},
        "tool_call": {"label": "⚙️ 工具调用", "color": "#7c3aed", "bg": "rgba(124, 58, 237, 0.12)"},
        "tool_result": {"label": "📤 执行结果", "color": "#db2777", "bg": "rgba(219, 39, 119, 0.12)"},
        "tts": {"label": "🔊 语音回复", "color": "#2563eb", "bg": "rgba(37, 99, 235, 0.12)"},
        "control": {"label": "📺 大屏控制", "color": "#4f46e5", "bg": "rgba(79, 70, 229, 0.12)"},
    }

    def __init__(self, step: str, content_data, parent=None):
        super().__init__(parent)
        self.step = step
        self.content_data = content_data
        self.content_label = None

        cfg = self.STEP_MAP.get(step, {"label": f"⚙️ {step}", "color": "#2563eb", "bg": "rgba(37, 99, 235, 0.12)"})
        self.setStyleSheet(f"background: {cfg['bg']}; border-radius: 6px; border: 1px solid rgba(150,150,150,0.15);")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # 头部: 标签 + 时间
        header_layout = QHBoxLayout()
        tag = QLabel(cfg["label"])
        tag.setStyleSheet(f"color: {cfg['color']}; font-weight: 700; font-size: 12px;")
        header_layout.addWidget(tag)

        header_layout.addStretch()

        self.time_lbl = QLabel(time.strftime("%H:%M:%S", time.localtime()))
        self.time_lbl.setStyleSheet("color: #6b7280; font-size: 11px; font-weight: 500;")
        header_layout.addWidget(self.time_lbl)

        layout.addLayout(header_layout)

        # 正文内容展现
        self.body_widget = self._create_body_widget()
        layout.addWidget(self.body_widget)

    def update_content(self, new_content):
        """就地覆盖更新卡片文字 (防止 stt/tts 产生一长串多条卡片)"""
        self.content_data = new_content
        self.time_lbl.setText(time.strftime("%H:%M:%S", time.localtime()))
        if self.step == "stt" and self.content_label:
            self.content_label.setText(f'识别文本: "{new_content}"')
        elif self.step == "tts" and self.content_label:
            self.content_label.setText(f'语音回复: "{new_content}"')
        elif self.content_label:
            self.content_label.setText(str(new_content))

    def _create_body_widget(self) -> QWidget:
        container = QWidget(self)
        l = QVBoxLayout(container)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(4)

        if self.step == "stt":
            self.content_label = BodyLabel(f'识别文本: "{self.content_data}"', container)
            self.content_label.setStyleSheet("font-size: 13px; font-weight: 600; line-height: 1.4;")
            self.content_label.setWordWrap(True)
            l.addWidget(self.content_label)

        elif self.step == "intent":
            self.content_label = BodyLabel(f'{self.content_data}', container)
            self.content_label.setStyleSheet("font-size: 13px; font-weight: 600; line-height: 1.4;")
            self.content_label.setWordWrap(True)
            l.addWidget(self.content_label)

        elif self.step == "tts":
            self.content_label = BodyLabel(f'语音回复: "{self.content_data}"', container)
            self.content_label.setStyleSheet("font-size: 13px; font-weight: 600; line-height: 1.4;")
            self.content_label.setWordWrap(True)
            l.addWidget(self.content_label)

        # ── ⚙️ 工具调用 (tool_call): 展示 工具名 + arguments 格式化 JSON ──
        elif self.step == "tool_call":
            name = ""
            args_data = None

            if isinstance(self.content_data, dict):
                name = self.content_data.get("name") or self.content_data.get("tool_name") or self.content_data.get("function", {}).get("name", "tool")
                args_data = self.content_data.get("arguments") if "arguments" in self.content_data else self.content_data.get("args") if "args" in self.content_data else self.content_data
            else:
                args_data = self.content_data

            if name:
                name_lbl = QLabel(f"工具名: {name}")
                name_lbl.setStyleSheet("font-size: 12px; font-weight: 700; color: #7c3aed;")
                l.addWidget(name_lbl)

            self.detail_text_edit = QTextEdit(container)
            self.detail_text_edit.setReadOnly(True)
            json_str = format_json(args_data)
            self.detail_text_edit.setPlainText(json_str)
            self.detail_text_edit.setStyleSheet(
                "QTextEdit { background: #18181b; color: #34d399; font-family: Consolas, Monaco, monospace; font-size: 11px; font-weight: 600; border-radius: 4px; border: 1px solid #27272a; padding: 4px; }"
            )
            lines_cnt = json_str.count("\n") + 1
            self.detail_text_edit.setFixedHeight(max(50, min(200, lines_cnt * 16 + 12)))
            l.addWidget(self.detail_text_edit)

        # ── 📤 执行结果 (tool_result): 展示 工具名 + result 格式化 JSON ──
        elif self.step == "tool_result":
            name = ""
            result_data = None

            if isinstance(self.content_data, dict):
                name = self.content_data.get("name") or self.content_data.get("tool_name", "tool")
                result_data = self.content_data.get("result") if "result" in self.content_data else self.content_data.get("output") if "output" in self.content_data else self.content_data
            else:
                result_data = self.content_data

            if name:
                name_lbl = QLabel(f"工具名: {name}")
                name_lbl.setStyleSheet("font-size: 12px; font-weight: 700; color: #db2777;")
                l.addWidget(name_lbl)

            self.detail_text_edit = QTextEdit(container)
            self.detail_text_edit.setReadOnly(True)
            json_str = format_json(result_data)
            self.detail_text_edit.setPlainText(json_str)
            self.detail_text_edit.setStyleSheet(
                "QTextEdit { background: #18181b; color: #34d399; font-family: Consolas, Monaco, monospace; font-size: 11px; font-weight: 600; border-radius: 4px; border: 1px solid #27272a; padding: 4px; }"
            )
            lines_cnt = json_str.count("\n") + 1
            self.detail_text_edit.setFixedHeight(max(50, min(200, lines_cnt * 16 + 12)))
            l.addWidget(self.detail_text_edit)

        # ── 📺 大屏控制 (control): 展示 指令内容 + arguments/payload 格式化 JSON ──
        elif self.step == "control":
            content_desc = ""
            payload_data = None

            if isinstance(self.content_data, dict):
                content_desc = self.content_data.get("content") or self.content_data.get("action") or self.content_data.get("command", "大屏指令")
                payload_data = self.content_data.get("arguments") if "arguments" in self.content_data else self.content_data.get("payload") if "payload" in self.content_data else self.content_data
            else:
                content_desc = str(self.content_data)

            if content_desc:
                desc_lbl = QLabel(f"指令内容: {content_desc}")
                desc_lbl.setStyleSheet("font-size: 12px; font-weight: 700; color: #4f46e5;")
                l.addWidget(desc_lbl)

            if payload_data is not None:
                self.detail_text_edit = QTextEdit(container)
                self.detail_text_edit.setReadOnly(True)
                json_str = format_json(payload_data)
                self.detail_text_edit.setPlainText(json_str)
                self.detail_text_edit.setStyleSheet(
                    "QTextEdit { background: #18181b; color: #34d399; font-family: Consolas, Monaco, monospace; font-size: 11px; font-weight: 600; border-radius: 4px; border: 1px solid #27272a; padding: 4px; }"
                )
                lines_cnt = json_str.count("\n") + 1
                self.detail_text_edit.setFixedHeight(max(50, min(200, lines_cnt * 16 + 12)))
                l.addWidget(self.detail_text_edit)

        else:
            self.content_label = BodyLabel(str(self.content_data), container)
            self.content_label.setStyleSheet("font-size: 13px; font-weight: 500;")
            self.content_label.setWordWrap(True)
            l.addWidget(self.content_label)

        return container


class DebugConsoleWidget(CardWidget):
    """
    全链路调试控制台 (100% 参照原版 App.vue 格式)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(260)

        self.last_step = None
        self.last_item_widget = None

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(10)

        # 头部标题栏与清空按钮
        header_layout = QHBoxLayout()
        title = SubtitleLabel("🛠️ 全链路调试控制台", self)
        title.setStyleSheet("font-size: 15px; font-weight: 800;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        self.clear_btn = TransparentToolButton(FIF.DELETE, self)
        self.clear_btn.setToolTip("清空调试日志")
        self.clear_btn.clicked.connect(self.clear_logs)
        header_layout.addWidget(self.clear_btn)

        main_layout.addLayout(header_layout)

        # 调试日志列表容器
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; }")

        self.log_container = QWidget()
        self.log_layout = QVBoxLayout(self.log_container)
        self.log_layout.setAlignment(Qt.AlignTop)
        self.log_layout.setSpacing(8)

        self.scroll.setWidget(self.log_container)
        main_layout.addWidget(self.scroll, stretch=1)

        # 空白空状态
        self.empty_label = CaptionLabel("等待语音交互启动以捕获链路事件...", self)
        self.empty_label.setStyleSheet("color: #6b7280; font-size: 12px; font-weight: 500; padding: 24px 0;")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.log_layout.addWidget(self.empty_label)

    @Slot(str, object)
    def log_event(self, step: str, content):
        """推送符合原版 DebugConsole 格式的链路日志"""
        logger.debug(f"[DebugConsole Log-Event] Rendering step={step}")
        if self.empty_label and self.empty_label.isVisible():
            self.empty_label.hide()

        # 防刷屏策略：针对 stt (转写) 和 tts (回复)，如果上一条卡片也是相同的 step，就地平滑覆盖更新！
        if step in ["stt", "tts"] and self.last_step == step and self.last_item_widget:
            self.last_item_widget.update_content(content)
        else:
            item = DebugLogItemWidget(step, content, self.log_container)
            self.log_layout.addWidget(item)
            self.last_step = step
            self.last_item_widget = item

            # FIFO 内存优化：控制最大保留 60 条调试卡片，自动回收老旧 Widget 释放内存
            if self.log_layout.count() > 60:
                oldest = self.log_layout.takeAt(0)
                if oldest and oldest.widget():
                    if oldest.widget() == self.last_item_widget:
                        self.last_item_widget = None
                    oldest.widget().deleteLater()

        self._scroll_to_bottom()

    def clear_logs(self):
        """清空所有调试日志"""
        while self.log_layout.count():
            child = self.log_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.last_step = None
        self.last_item_widget = None

        self.empty_label = CaptionLabel("等待语音交互启动以捕获链路事件...", self)
        self.empty_label.setStyleSheet("color: #6b7280; font-size: 12px; font-weight: 500; padding: 24px 0;")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.log_layout.addWidget(self.empty_label)

    def _scroll_to_bottom(self):
        self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum())
