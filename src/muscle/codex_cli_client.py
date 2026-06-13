"""Execution client for the codex-subscription provider.

Architecture Decision Record (ADR):
- Use the official ``codex`` CLI as the subscription-compliant execution surface.
- Keep ChatGPT OAuth and refresh-token handling entirely inside Codex.
- Preserve MUSCLE's synchronous ``M27Client`` contract for review orchestration,
  telemetry, structured retries, and response caching.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

from .m27_client import CachePlan, M27Client, TokenUsage
from .providers import ProviderBillingError, ProviderError

if TYPE_CHECKING:
    from .optimization.types import TelemetryContext

logger = logging.getLogger("muscle.codex_cli_client")

DEFAULT_CODEX_MODEL = "gpt-5.5"
DEFAULT_CODEX_TIMEOUT = 600
CODEX_AUTH_TIMEOUT = 15
_ERROR_DETAIL_LIMIT = 500

_BILLING_MARKERS = (
    "usage limit",
    "rate limit",
    "quota",
    "out of credits",
    "allowance",
)
_AUTH_MARKERS = (
    "not logged in",
    "please log in",
    "log in to",
    "authenticate",
    "not authenticated",
    "unauthorized",
)


def codex_login_status(binary: str = "codex", timeout: int = CODEX_AUTH_TIMEOUT) -> str:
    """Return ``codex login status`` output without exposing secrets."""
    proc = subprocess.run(
        [binary, "login", "status"],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return f"{proc.stdout or ''}\n{proc.stderr or ''}".strip()


def is_chatgpt_login_status(status: str) -> bool:
    """True when Codex reports ChatGPT-managed authentication."""
    return "logged in using chatgpt" in status.lower()


def ensure_chatgpt_login(binary: str = "codex") -> str:
    """Require Codex CLI ChatGPT sign-in for subscription execution."""
    try:
        status = codex_login_status(binary)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProviderError(
            "codex-subscription provider could not check Codex login status. "
            "Run `codex login` and retry."
        ) from exc

    lowered = status.lower()
    if is_chatgpt_login_status(status):
        return status
    if "api key" in lowered or "apikey" in lowered:
        raise ProviderError(
            "codex-subscription requires Codex ChatGPT login. The current Codex login "
            "appears to use an API key, which would be billed as OpenAI API usage. "
            "Run `muscle provider login codex-subscription` to use ChatGPT sign-in."
        )
    raise ProviderError(
        "codex-subscription requires Codex ChatGPT login. Run "
        "`muscle provider login codex-subscription` and retry. "
        f"Codex status: {status[:_ERROR_DETAIL_LIMIT]}"
    )


class CodexCliClient(M27Client):
    """M27Client variant that executes through the official ``codex`` CLI."""

    def __init__(
        self,
        model: str = DEFAULT_CODEX_MODEL,
        binary: str = "codex",
        timeout: int = DEFAULT_CODEX_TIMEOUT,
        cache_db_path: Path | None = None,
        cache_pack_id: str | None = None,
        verify_auth: bool = True,
    ) -> None:
        resolved = shutil.which(binary)
        if resolved is None:
            raise ProviderError(
                "codex-subscription provider needs the official `codex` CLI on PATH. "
                "Install Codex, run `codex login`, then retry."
            )
        if verify_auth:
            ensure_chatgpt_login(resolved)
        self._binary = resolved
        super().__init__(
            api_key="codex-cli-subprocess",
            base_url="codex-cli://local",
            model=model,
            cache_db_path=cache_db_path,
            cache_pack_id=cache_pack_id,
        )
        self.timeout = max(30, timeout)

    def chat(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        stream: bool = False,
        telemetry_context: TelemetryContext | None = None,
        thinking: str | None = None,
        stage: str | None = None,
        response_format: dict[str, Any] | None = None,
        _metadata_sink: dict[str, Any] | None = None,
        cache_plan: CachePlan | None = None,
        tools: list[dict[str, Any]] | None = None,
        functions: list[dict[str, Any]] | None = None,
    ) -> tuple[str, TokenUsage]:
        # max_tokens/temperature/stream/thinking/stage/cache_plan/tools/functions are
        # accepted for interface parity; Codex manages its own generation
        # controls here.
        if not self._validate_messages(messages):
            return "", TokenUsage()

        prompt = self._render_prompt(messages, system=system)

        with tempfile.TemporaryDirectory(prefix="muscle-codex-") as tmp:
            tmp_path = Path(tmp)
            workdir = tmp_path / "workspace"
            workdir.mkdir()
            output_path = tmp_path / "last-message.txt"
            cmd = [
                self._binary,
                "exec",
                "-",
                "--model",
                self.model,
                "--json",
                "--output-last-message",
                str(output_path),
                "--ephemeral",
                "--ignore-rules",
                "--ignore-user-config",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "--ask-for-approval",
                "never",
                "--color",
                "never",
                "--cd",
                str(workdir),
            ]
            if response_format is not None:
                schema_path = tmp_path / "output-schema.json"
                schema_path.write_text(json.dumps(response_format), encoding="utf-8")
                cmd.extend(["--output-schema", str(schema_path)])

            try:
                proc = subprocess.run(
                    cmd,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                )
            except subprocess.TimeoutExpired as exc:
                raise ProviderError(
                    f"codex CLI call timed out after {self.timeout}s. Narrow the prompt "
                    "or raise the provider timeout."
                ) from exc

            if proc.returncode != 0:
                detail = f"{proc.stderr or ''}\n{proc.stdout or ''}".strip()
                self._raise_for_failure(detail)

            try:
                text = output_path.read_text(encoding="utf-8")
            except OSError as exc:
                raise ProviderError(
                    "codex CLI completed but did not write the final response file."
                ) from exc

        if not text.strip():
            raise ProviderError("codex CLI completed with an empty final response.")

        if _metadata_sink is not None:
            _metadata_sink.setdefault("truncated", False)

        usage = self._parse_usage_jsonl(proc.stdout)
        if usage.input_tokens == 0 and usage.output_tokens == 0 and text:
            usage = TokenUsage(
                input_tokens=max(1, len(prompt) // 4),
                output_tokens=max(1, len(text) // 4),
            )
            if _metadata_sink is not None:
                _metadata_sink["usage_estimated"] = True
            logger.info(
                "codex CLI omitted usage; estimated %d input / %d output tokens",
                usage.input_tokens,
                usage.output_tokens,
            )
        return text, usage

    def chat_streaming(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        timeout: int | None = None,
        telemetry_context: TelemetryContext | None = None,
        thinking: str | None = None,
    ) -> Iterator[tuple[str, TokenUsage | None]]:
        """Codex CLI execution is blocking; yield one final chunk."""
        text, usage = self.chat(
            messages,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            telemetry_context=telemetry_context,
            thinking=thinking,
        )
        yield text, usage

    @staticmethod
    def _render_prompt(messages: list[dict], system: str | None = None) -> str:
        blocks: list[str] = []
        if system:
            blocks.append(f"[system]\n{system}")
        blocks.extend(
            f"[{message.get('role', 'user')}]\n{message.get('content', '')}" for message in messages
        )
        if len(blocks) == 1 and len(messages) == 1 and messages[0].get("role") == "user":
            return str(messages[0].get("content", ""))
        return "\n\n".join(blocks)

    @staticmethod
    def _parse_usage_jsonl(stdout: str) -> TokenUsage:
        """Parse the latest Codex token_count event from JSONL stdout."""
        latest: dict[str, Any] | None = None
        for raw_line in stdout.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            payload = event.get("payload")
            if not isinstance(payload, dict) or payload.get("type") != "token_count":
                continue
            info = payload.get("info")
            if not isinstance(info, dict):
                continue
            usage = info.get("last_token_usage")
            if isinstance(usage, dict):
                latest = usage
        if latest is None:
            return TokenUsage()

        input_tokens = int(latest.get("input_tokens") or 0)
        output_tokens = int(latest.get("output_tokens") or 0)
        cached_input_tokens = int(latest.get("cached_input_tokens") or 0)
        reasoning_tokens = int(latest.get("reasoning_output_tokens") or 0)
        return TokenUsage(
            input_tokens=max(input_tokens, cached_input_tokens),
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            cached_input_tokens=cached_input_tokens,
        )

    @staticmethod
    def _raise_for_failure(detail: str) -> NoReturn:
        lowered = detail.lower()
        excerpt = detail.strip()[:_ERROR_DETAIL_LIMIT]
        if any(marker in lowered for marker in _BILLING_MARKERS):
            raise ProviderBillingError(
                "Codex subscription allowance or rate limit blocked the request. "
                f"CLI said: {excerpt}"
            )
        if any(marker in lowered for marker in _AUTH_MARKERS):
            raise ProviderError(
                "The `codex` CLI is not authenticated with ChatGPT. Run "
                "`muscle provider login codex-subscription` and retry. "
                f"CLI said: {excerpt}"
            )
        raise ProviderError(f"codex CLI call failed: {excerpt}")
