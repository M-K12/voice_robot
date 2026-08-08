"""
Compatibility Layer for OpenAIChatHandler
Redirects imports to handlers.openai_chat_handler
"""
from handlers.openai_chat_handler import (
    OpenAIChatHandler,
    QwenOpenAIChatHandler,
    get_dashscope_base_url,
    get_default_text_model,
    get_prompt
)

__all__ = [
    "OpenAIChatHandler",
    "QwenOpenAIChatHandler",
    "get_dashscope_base_url",
    "get_default_text_model",
    "get_prompt"
]
