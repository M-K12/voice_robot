"""
OpenAI-Compatible Text Chat Handler Module for Voice Robot Project

Based on Aliyun Bailian / DashScope OpenAI-compatible API (qwen_openai_chat.md).
Streamlined specifically for text-based chat completions, streaming responses,
optional web search, and tool calling (Function Calling).
"""

from __future__ import annotations

import os
import json
import asyncio
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, AsyncGenerator, Generator, Callable, Union

from openai import OpenAI, AsyncOpenAI
from dotenv import load_dotenv

# Automatically load environment variables from .env file
for env_path in [
    Path.cwd() / ".env",
    Path(__file__).parent / ".env",
    Path(__file__).parent.parent / ".env",
    Path(__file__).parent.parent.parent / ".env",
]:
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)

# Configure logging
logger = logging.getLogger("xiaoan.openai_chat")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )


def get_dashscope_base_url(
    workspace_id: Optional[str] = None,
    region: str = "cn-beijing",
    use_workspace_domain: bool = False
) -> str:
    """
    Construct the DashScope OpenAI-compatible base URL.

    By default, uses the universal stable base URL (https://dashscope.aliyuncs.com/compatible-mode/v1)
    to prevent '400 Workspace endpoint is invalid' errors when using standard Qwen text models.

    :param workspace_id: Bailian workspace ID (optional).
    :param region: Region code ('cn-beijing', 'ap-southeast-1', 'dashscope-us', 'eu-central-1', 'ap-northeast-1').
    :param use_workspace_domain: Whether to force dedicated workspace domain.
    :return: Full base URL string.
    """
    ws_id = workspace_id or os.getenv("DASHSCOPE_WORKSPACE_ID") or os.getenv("WORKSPACE_ID") or ""

    if use_workspace_domain and ws_id:
        if region == "ap-southeast-1":
            return f"https://{ws_id}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
        elif region == "eu-central-1":
            return f"https://{ws_id}.eu-central-1.maas.aliyuncs.com/compatible-mode/v1"
        elif region == "ap-northeast-1":
            return f"https://{ws_id}.ap-northeast-1.maas.aliyuncs.com/compatible-mode/v1"
        else:
            return f"https://{ws_id}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"

    if region == "ap-southeast-1":
        return "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    elif region == "dashscope-us":
        return "https://dashscope-us.aliyuncs.com/compatible-mode/v1"
    else:
        return "https://dashscope.aliyuncs.com/compatible-mode/v1"


def get_default_text_model() -> str:
    """
    Attempt to load text model name from configs/model_config.json if available.
    """
    try:
        from utils import load_config
        config = load_config()
        text_model = config.get("text_model_name") or config.get("text_chat", {}).get("model_name")
        if text_model:
            return text_model
    except Exception:
        pass

    config_file = Path.cwd() / "configs" / "model_config.json"
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("text_chat", {}).get("model_name", "qwen3.6-flash")
        except Exception:
            pass

    return "qwen3.6-flash"


from tools import get_prompt


class OpenAIChatHandler:
    """
    Standard Text Chat Handler for Qwen / OpenAI-compatible Chat API.
    Designed to power the text chat workflow of the Voice Robot project.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        workspace_id: Optional[str] = None,
        region: str = "cn-beijing",
        default_model: Optional[str] = None,
        use_workspace_domain: bool = False
    ):
        """
        Initialize Text Chat Handler.

        :param api_key: DashScope API Key (defaults to env DASHSCOPE_API_KEY).
        :param workspace_id: Workspace ID (defaults to env DASHSCOPE_WORKSPACE_ID).
        :param region: Target region (default 'cn-beijing').
        :param default_model: Target model name (defaults to config text_chat.model_name or 'qwen3.6-flash').
        :param use_workspace_domain: Whether to force workspace domain (defaults to False for universal stability).
        """
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY", "")
        if not self.api_key:
            logger.warning("⚠️ DASHSCOPE_API_KEY is not configured! LLM calls will fail without API key.")

        self.workspace_id = workspace_id or os.getenv("DASHSCOPE_WORKSPACE_ID", "")
        self.region = region
        self.default_model = default_model or get_default_text_model()
        self.base_url = get_dashscope_base_url(self.workspace_id, self.region, use_workspace_domain)

        logger.info(f"✨ [OpenAIChatHandler] Initialized | BaseURL: {self.base_url} | Model: {self.default_model}")

        self._client: Optional[OpenAI] = None
        self._async_client: Optional[AsyncOpenAI] = None

    @property
    def client(self) -> OpenAI:
        """Get or lazy-initialize synchronous OpenAI client."""
        if self._client is None:
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    @property
    def async_client(self) -> AsyncOpenAI:
        """Get or lazy-initialize asynchronous AsyncOpenAI client."""
        if self._async_client is None:
            self._async_client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._async_client

    def format_messages(
        self,
        messages: List[Dict[str, Any]],
        system: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Ensure system prompt is formatted correctly at message index 0.
        """
        formatted = list(messages)
        if system:
            if formatted and formatted[0].get("role") == "system":
                formatted[0] = {"role": "system", "content": system}
            else:
                formatted.insert(0, {"role": "system", "content": system})
        return formatted

    # ─────────────────────────────────────────────────────────────
    # Standard Text Chat Completion (Sync & Async)
    # ─────────────────────────────────────────────────────────────

    def chat(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        enable_search: bool = False,
        tools: Optional[List[Dict[str, Any]]] = None,
        extra_body: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Any:
        """
        Synchronous Text Chat Completion request.
        """
        target_model = model or self.default_model
        formatted_messages = self.format_messages(messages, system)

        req_extra_body = extra_body or {}
        if enable_search:
            req_extra_body["enable_search"] = True

        call_kwargs: Dict[str, Any] = {
            "model": target_model,
            "messages": formatted_messages,
            "temperature": temperature,
        }
        if max_tokens:
            call_kwargs["max_tokens"] = max_tokens
        if tools:
            call_kwargs["tools"] = tools
        if req_extra_body:
            call_kwargs["extra_body"] = req_extra_body
        call_kwargs.update(kwargs)

        return self.client.chat.completions.create(**call_kwargs)

    async def async_chat(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        enable_search: bool = False,
        tools: Optional[List[Dict[str, Any]]] = None,
        extra_body: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Any:
        """
        Asynchronous Text Chat Completion request.
        """
        target_model = model or self.default_model
        formatted_messages = self.format_messages(messages, system)

        req_extra_body = extra_body or {}
        if enable_search:
            req_extra_body["enable_search"] = True

        call_kwargs: Dict[str, Any] = {
            "model": target_model,
            "messages": formatted_messages,
            "temperature": temperature,
        }
        if max_tokens:
            call_kwargs["max_tokens"] = max_tokens
        if tools:
            call_kwargs["tools"] = tools
        if req_extra_body:
            call_kwargs["extra_body"] = req_extra_body
        call_kwargs.update(kwargs)

        return await self.async_client.chat.completions.create(**call_kwargs)

    # ─────────────────────────────────────────────────────────────
    # Streaming Text Chat Completion (Sync & Async)
    # ─────────────────────────────────────────────────────────────

    def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        enable_search: bool = False,
        extra_body: Optional[Dict[str, Any]] = None,
        include_usage: bool = True,
        **kwargs
    ) -> Generator[str, None, None]:
        """
        Synchronous streaming text response generator.
        """
        target_model = model or self.default_model
        formatted_messages = self.format_messages(messages, system)

        req_extra_body = extra_body or {}
        if enable_search:
            req_extra_body["enable_search"] = True

        call_kwargs: Dict[str, Any] = {
            "model": target_model,
            "messages": formatted_messages,
            "temperature": temperature,
            "stream": True,
        }
        if include_usage:
            call_kwargs["stream_options"] = {"include_usage": True}
        if max_tokens:
            call_kwargs["max_tokens"] = max_tokens
        if req_extra_body:
            call_kwargs["extra_body"] = req_extra_body
        call_kwargs.update(kwargs)

        stream = self.client.chat.completions.create(**call_kwargs)
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def async_chat_stream(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        enable_search: bool = False,
        extra_body: Optional[Dict[str, Any]] = None,
        include_usage: bool = True,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """
        Asynchronous streaming text response generator.
        """
        target_model = model or self.default_model
        formatted_messages = self.format_messages(messages, system)

        req_extra_body = extra_body or {}
        if enable_search:
            req_extra_body["enable_search"] = True

        call_kwargs: Dict[str, Any] = {
            "model": target_model,
            "messages": formatted_messages,
            "temperature": temperature,
            "stream": True,
        }
        if include_usage:
            call_kwargs["stream_options"] = {"include_usage": True}
        if max_tokens:
            call_kwargs["max_tokens"] = max_tokens
        if req_extra_body:
            call_kwargs["extra_body"] = req_extra_body
        call_kwargs.update(kwargs)

        stream = await self.async_client.chat.completions.create(**call_kwargs)
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    # ─────────────────────────────────────────────────────────────
    # Function Calling & Project Text Chat Workflow
    # ─────────────────────────────────────────────────────────────

    async def async_chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_executor_map: Optional[Dict[str, Callable[..., Any]]] = None,
        model: Optional[str] = None,
        system: Optional[str] = None,
        max_turns: int = 5
    ) -> Dict[str, Any]:
        """
        Automated multi-turn Tool Calling execution loop for text chat.
        """
        if tools is None:
            try:
                from tools import GLOBAL_TOOLS_SCHEMA
                tools = GLOBAL_TOOLS_SCHEMA
            except Exception:
                tools = []

        history = self.format_messages(messages, system)
        tool_executor_map = tool_executor_map or {}

        turn = 0
        while turn < max_turns:
            turn += 1
            response = await self.async_chat(
                messages=history,
                model=model,
                tools=tools if tools else None
            )

            choice = response.choices[0]
            msg = choice.message

            assistant_msg: Dict[str, Any] = {"role": "assistant"}
            if msg.content:
                assistant_msg["content"] = msg.content
            if msg.tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in msg.tool_calls
                ]

            history.append(assistant_msg)

            if not msg.tool_calls:
                return {
                    "content": msg.content or "",
                    "history": history,
                    "response": response
                }

            for tool_call in msg.tool_calls:
                func_name = tool_call.function.name
                func_args_str = tool_call.function.arguments
                logger.info(f"🛠️ [Tool Call] Invoked '{func_name}' with args: {func_args_str}")

                try:
                    func_args = json.loads(func_args_str) if func_args_str else {}
                except json.JSONDecodeError:
                    func_args = {}

                if func_name in tool_executor_map:
                    try:
                        executor = tool_executor_map[func_name]
                        if asyncio.iscoroutinefunction(executor):
                            result = await executor(**func_args)
                        else:
                            result = executor(**func_args)
                        result_str = json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result
                    except Exception as e:
                        logger.error(f"❌ Error executing tool '{func_name}': {e}")
                        result_str = json.dumps({"error": str(e)}, ensure_ascii=False)
                else:
                    try:
                        from tools import execute_tool, ToolContext
                        ctx = ToolContext(websocket=None, default_city="歙县")
                        result_str = await execute_tool(func_name, func_args_str, ctx)
                    except Exception as e:
                        logger.warning(f"⚠️ Project tool execution failed for '{func_name}': {e}")
                        result_str = json.dumps({"error": f"Tool {func_name} failed: {str(e)}"}, ensure_ascii=False)

                history.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": func_name,
                    "content": result_str
                })

        logger.warning(f"⚠️ Reached maximum tool call turns ({max_turns}). Returning last result.")
        return {
            "content": history[-1].get("content", ""),
            "history": history
        }

    async def stream_project_text_chat(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
        city: str = "歙县",
        model: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """
        Streaming text chat workflow tailored for the Voice Robot UI / WebSocket / SSE response.

        Yields text chunks directly as the LLM generates tokens.
        """
        system_prompt = get_prompt(city)
        formatted_messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]

        if history:
            for item in history:
                formatted_messages.append({"role": item.get("role", "user"), "content": item.get("content", "")})

        formatted_messages.append({"role": "user", "content": message})

        # Step 1: Initial query with tools
        try:
            from tools import GLOBAL_TOOLS_SCHEMA
            tools = GLOBAL_TOOLS_SCHEMA
        except Exception:
            tools = None

        response = await self.async_chat(
            messages=formatted_messages,
            model=model,
            tools=tools
        )

        choice = response.choices[0]
        msg = choice.message

        if msg.tool_calls:
            # Handle tool call & summary step
            assistant_msg = {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                    }
                    for tc in msg.tool_calls
                ]
            }
            second_messages = list(formatted_messages)
            second_messages.append(assistant_msg)

            for tc in msg.tool_calls:
                func_name = tc.function.name
                func_args_str = tc.function.arguments
                logger.info(f"🛠️ [Stream Tool Call] Executing '{func_name}' with args: {func_args_str}")

                try:
                    from tools import execute_tool, ToolContext
                    ctx = ToolContext(websocket=None, default_city=city)
                    res_str = await execute_tool(func_name, func_args_str, ctx)
                except Exception as e:
                    res_str = json.dumps({"error": str(e)}, ensure_ascii=False)

                second_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": func_name,
                    "content": res_str
                })

            # Stream second turn summary response
            async for token in self.async_chat_stream(messages=second_messages, model=model):
                yield token
        else:
            # If content was returned directly, yield content
            if msg.content:
                yield msg.content


# Alias for backward compatibility
QwenOpenAIChatHandler = OpenAIChatHandler
