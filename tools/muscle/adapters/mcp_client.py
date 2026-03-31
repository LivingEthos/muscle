"""
MiniMax MCP client for MUSCLE.

Provides integration with MiniMax MCP tools (text_to_audio, image generation, etc.)
for enhancing code generation with multimodal capabilities.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MCPClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_path: str | None = None,
        transport: str = "stdio",
    ):
        self.api_key = api_key or os.environ.get("MINIMAX_API_KEY")
        self.base_path = Path(base_path) if base_path else Path.cwd()
        self.transport = transport
        self.process: subprocess.Popen | None = None

        if not self.api_key:
            logger.warning("MINIMAX_API_KEY not set - MCP tools will not be available")

    def _get_env(self) -> dict:
        return {
            "MINIMAX_API_KEY": self.api_key or "",
            "MINIMAX_MCP_BASE_PATH": str(self.base_path),
            "MINIMAX_API_HOST": os.environ.get("MINIMAX_API_HOST", "https://api.minimaxi.com"),
        }

    def start_server(self) -> bool:
        try:
            self.process = subprocess.Popen(
                ["uvx", "minimax-mcp"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, **self._get_env()},
            )
            logger.info("MCP server started")
            return True
        except FileNotFoundError:
            logger.warning("uvx not found - MCP server not started")
            return False
        except Exception as e:
            logger.error(f"Failed to start MCP server: {e}")
            return False

    def stop_server(self) -> None:
        if self.process:
            self.process.terminate()
            self.process.wait()
            logger.info("MCP server stopped")

    def _send_request(self, tool_name: str, arguments: dict) -> dict | None:
        if not self.process or not self.process.stdin or not self.process.stdout:
            return None

        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }

        try:
            stdin: Any = self.process.stdin
            stdout: Any = self.process.stdout
            stdin.write(json.dumps(request).encode() + b"\n")
            stdin.flush()

            response_line = stdout.readline()
            if response_line:
                response = json.loads(response_line)
                return response.get("result")  # type: ignore[no-any-return]
        except Exception as e:
            logger.error(f"MCP request failed: {e}")

        return None

    def text_to_speech(
        self,
        text: str,
        voice_id: str = "female-shaonv",
        model: str = "speech-02-hd",
        speed: float = 1.0,
    ) -> str | None:
        result = self._send_request(
            "text_to_audio",
            {
                "text": text,
                "voice_id": voice_id,
                "model": model,
                "speed": speed,
            },
        )

        if result and "content" in result:
            return result["content"][0].get("text")  # type: ignore[no-any-return]
        return None

    def generate_image(
        self,
        prompt: str,
        model: str = "image-01",
        aspect_ratio: str = "1:1",
    ) -> str | None:
        result = self._send_request(
            "text_to_image",
            {
                "prompt": prompt,
                "model": model,
                "aspect_ratio": aspect_ratio,
            },
        )

        if result and "content" in result:
            return result["content"][0].get("text")  # type: ignore[no-any-return]
        return None

    def generate_video(
        self,
        prompt: str,
        model: str = "T2V-01",
        duration: int = 6,
    ) -> str | None:
        result = self._send_request(
            "generate_video",
            {
                "prompt": prompt,
                "model": model,
                "duration": duration,
            },
        )

        if result and "content" in result:
            return result["content"][0].get("text")  # type: ignore[no-any-return]
        return None

    def list_voices(self, voice_type: str = "all") -> list[dict]:
        result = self._send_request(
            "list_voices",
            {
                "voice_type": voice_type,
            },
        )

        if result and "content" in result:
            import json

            return json.loads(result["content"][0].get("text", "[]"))  # type: ignore[no-any-return]
        return []

    def voice_clone(
        self,
        file_path: str,
        voice_id: str,
        text: str | None = None,
    ) -> str | None:
        result = self._send_request(
            "voice_clone",
            {
                "file": file_path,
                "voice_id": voice_id,
                "text": text or "This is a test.",
            },
        )

        if result and "content" in result:
            return result["content"][0].get("text")  # type: ignore[no-any-return]
        return None

    def __enter__(self) -> MCPClient:
        self.start_server()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop_server()
