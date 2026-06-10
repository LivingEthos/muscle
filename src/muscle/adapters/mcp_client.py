"""
MiniMax MCP client for MUSCLE.

Provides integration with MiniMax MCP tools (text_to_audio, image generation, etc.)
for enhancing code generation with multimodal capabilities.
"""

from __future__ import annotations

import json
import logging
import os
import select
import subprocess
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MCPClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_path: str | None = None,
        transport: str = "stdio",
        startup_timeout_seconds: float = 5.0,
        request_timeout_seconds: float = 30.0,
    ):
        self.api_key = api_key or os.environ.get("MINIMAX_API_KEY")
        self.base_path = Path(base_path) if base_path else Path.cwd()
        self.transport = transport
        self.process: subprocess.Popen | None = None
        self.startup_timeout_seconds = startup_timeout_seconds
        self.request_timeout_seconds = request_timeout_seconds

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
            started_at = time.time()
            deadline = started_at + self.startup_timeout_seconds
            while time.time() < deadline:
                if self.process.poll() is not None:
                    stderr_output = self._read_available_stderr()
                    logger.error("MCP server exited during startup: %s", stderr_output or "unknown")
                    self.process = None
                    return False
                if time.time() - started_at >= min(0.25, self.startup_timeout_seconds):
                    break
                time.sleep(0.05)
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
            try:
                self.process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5.0)
            stderr_output = self._read_available_stderr()
            if stderr_output:
                logger.debug("MCP server stderr on shutdown: %s", stderr_output)
            logger.info("MCP server stopped")
            self.process = None

    def _send_request(self, tool_name: str, arguments: dict) -> dict:
        if not self.process or not self.process.stdin or not self.process.stdout:
            msg = "MCP server is not running"
            raise RuntimeError(msg)
        if self.process.poll() is not None:
            stderr_output = self._read_available_stderr()
            msg = f"MCP server exited: {stderr_output or 'unknown error'}"
            raise RuntimeError(msg)

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

            response_line = self._readline_with_timeout(stdout, self.request_timeout_seconds)
            response = json.loads(response_line)
            if isinstance(response, dict) and "error" in response:
                error_payload = response.get("error", {})
                msg = str(error_payload.get("message") or "Unknown MCP error")
                raise RuntimeError(msg)
            result = response.get("result")
            if not isinstance(result, dict):
                msg = "MCP response missing result payload"
                raise RuntimeError(msg)
            return result
        except Exception as e:
            logger.error(f"MCP request failed: {e}")
            raise

    def _readline_with_timeout(self, stdout: Any, timeout_seconds: float) -> str:
        ready, _, _ = select.select([stdout], [], [], timeout_seconds)
        if not ready:
            msg = f"MCP request timed out after {timeout_seconds}s"
            raise TimeoutError(msg)
        response_line = stdout.readline()
        if not response_line:
            stderr_output = self._read_available_stderr()
            msg = f"MCP server returned no response: {stderr_output or 'empty stdout'}"
            raise RuntimeError(msg)
        if isinstance(response_line, bytes):
            return response_line.decode("utf-8")
        return str(response_line)

    def _read_available_stderr(self) -> str:
        if not self.process or not self.process.stderr:
            return ""
        stderr: Any = self.process.stderr
        ready, _, _ = select.select([stderr], [], [], 0)
        if not ready:
            return ""
        try:
            fileno = stderr.fileno()
            if not isinstance(fileno, int) or fileno <= 2:
                return ""
            data = os.read(fileno, 4096)
        except OSError:
            return ""
        return data.decode("utf-8", errors="replace").strip()

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
