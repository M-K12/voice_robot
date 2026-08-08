from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QFrame
)
from qfluentwidgets import CardWidget, BodyLabel, SubtitleLabel


class ChatBubble(CardWidget):
    """
    单个对话气泡卡片，提供极高对比度的文字样式与自适应夜间/白天主题
    """
    def __init__(self, sender: str, text: str, parent=None):
        super().__init__(parent)
        self.sender = sender
        self.setBorderRadius(12)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(6)

        self.header = QLabel("👤 您" if sender == "user" else "🤖 小安")
        if sender == "user":
            self.header.setStyleSheet("font-weight: 700; font-size: 13px; color: #0284c7; letter-spacing: 0.5px;")
        else:
            self.header.setStyleSheet("font-weight: 700; font-size: 13px; color: #059669; letter-spacing: 0.5px;")
        layout.addWidget(self.header)

        self.content_label = BodyLabel(text, self)
        self.content_label.setWordWrap(True)
        self.content_label.setStyleSheet("font-size: 14px; font-weight: 500; line-height: 1.6; color: #1e293b;")
        layout.addWidget(self.content_label)

        if sender == "user":
            self.setStyleSheet("""
                ChatBubble { 
                    background-color: rgba(2, 132, 199, 0.09); 
                    border-radius: 12px; 
                    border: 1px solid rgba(2, 132, 199, 0.2); 
                }
            """)
        else:
            self.setStyleSheet("""
                ChatBubble { 
                    background-color: rgba(16, 185, 129, 0.09); 
                    border-radius: 12px; 
                    border: 1px solid rgba(16, 185, 129, 0.2); 
                }
            """)

    def set_text(self, text: str):
        self.content_label.setText(text)


class ChatViewWidget(QWidget):
    """
    对话消息流布局容器 (支持高对比度流式文本更新)
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; }")

        self.container = QWidget()
        self.container.setStyleSheet("QWidget { background: transparent; }")
        self.layout_list = QVBoxLayout(self.container)
        self.layout_list.setAlignment(Qt.AlignTop)
        self.layout_list.setSpacing(14)

        self.scroll.setWidget(self.container)
        main_layout.addWidget(self.scroll)

        self.last_bubble = None
        self.last_sender = None

    def add_message(self, sender: str, text: str):
        """新增一条完整消息气泡"""
        row_layout = QHBoxLayout()
        bubble = ChatBubble(sender, text)

        if sender == "user":
            row_layout.addStretch()
            row_layout.addWidget(bubble)
        else:
            row_layout.addWidget(bubble)
            row_layout.addStretch()

        self.layout_list.addLayout(row_layout)
        self.last_bubble = bubble
        self.last_sender = sender
        self._scroll_to_bottom()

    def update_streaming_message(self, sender: str, text: str):
        """流式动态更新或新建气泡"""
        if self.last_bubble and self.last_sender == sender:
            self.last_bubble.set_text(text)
        else:
            self.add_message(sender, text)
        self._scroll_to_bottom()

    def clear_messages(self):
        """清空对话历史记录"""
        while self.layout_list.count():
            item = self.layout_list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()
        self.last_bubble = None
        self.last_sender = None

    def _scroll_to_bottom(self):
        """平滑自动滚动到消息列表的最底部"""
        self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum())
