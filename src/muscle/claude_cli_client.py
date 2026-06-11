"""Execution client for the claude-subscription provider.

Shells out to the OFFICIAL `claude` CLI in headless print mode (`claude -p`),
so usage draws on the user's Claude plan ("Agent SDK credit" pool).

COMPLIANCE (verified against code.claude.com/docs legal-and-compliance, June
2026): invoking the official binary is permitted; what is banned is a
third-party tool using subscription OAuth tokens directly against the API.
This module therefore ONLY spawns the binary; it never reads, stores, or
transmits Claude OAuth tokens or credentials and never offers claude.ai login.
The subprocess inherits the parent environment untouched (no env= override),
so MUSCLE never sees or handles whatever credentials the CLI manages itself.

Billing semantics: headless `claude -p` on subscription plans draws from a
separate monthly "Agent SDK credit" pool (Pro $20/mo, Max $100-200/mo, no
rollover) — errors and cost reporting label consumption as Agent SDK credit,
never the interactive plan quota.

Auth-probe deviation: a no-op invocation would itself consume Agent SDK
credit, so __init__ verifies only that the binary exists; authentication
failures surface at the first real call with a clear error.

Flags verified live against claude CLI v2.1.163: `-p`, `--output-format json`,
`--model`, `--effort low|medium|high|xhigh|max`, `--tools ""` (disables all
built-in tools), `--no-session-persistence`, `--system-prompt <text>`.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

from .m27_client import CachePlan, M27Client, TokenUsage
from .providers import ProviderBillingError, ProviderError

if TYPE_CHECKING:
    from .optimization.types import TelemetryContext

logger = logging.getLogger("muscle.claude_cli_client")

DEFAULT_CLI_MODEL = "claude-opus-4-8"

# MUSCLE thinking-policy stage mode -> claude CLI --effort level. Mirrors the
# anthropic_client mapping: adaptive/enabled stages get high effort, disabled
# and unspecified stages run at the medium default.
_EFFORT_FOR_THINKING: dict[str | None, str] = {
    "adaptive": "high",
    "enabled": "high",
    "disabled": "medium",
    None: "medium",
}

# Lowercased substrings that classify a CLI failure (stderr/stdout/result text).
_BILLING_MARKERS = ("usage limit", "credit", "out of credits", "extra usage")
_AUTH_MARKERS = ("log in", "login", "logged in", "authenticate", "api key")

# Headless turns can run long (the CLI does its own multi-step reasoning).
DEFAULT_CLI_TIMEOUT = 600

# Max chars of CLI stderr/stdout echoed into error messages.
_ERROR_DETAIL_LIMIT = 500


class ClaudeCliClient(M27Client):
    """M27Client variant that executes via the official `claude` CLI.

    Inherits chat_structured() (schema hints, validation, response cache) from
    M27Client because chat() is fully overridden to spawn the binary instead
    of HTTP. chat_streaming() is a single-chunk parity shim.
    """

    def __init__(
        self,
        model: str = DEFAULT_CLI_MODEL,
        binary: str = "claude",
        timeout: int = DEFAULT_CLI_TIMEOUT,
        cache_db_path: Path | None = None,
        cache_pack_id: str | None = None,
    ) -> None:
        resolved = shutil.which(binary)
        if resolved is None:
            raise ProviderError(
                "claude-subscription provider needs the official `claude` CLI on PATH. "
                "Install it (https://claude.com/claude-code) and run `claude` once to "
                "log in, then retry."
            )
        self._binary = resolved
        # Placeholder key/base satisfy the parent's invariants; HTTP is never
        # used because chat()/chat_streaming() are fully overridden below.
        super().__init__(
            api_key="claude-cli-subprocess",
            base_url="claude-cli://local",
            model=model,
            cache_db_path=cache_db_path,
            cache_pack_id=cache_pack_id,
        )
        # Override the parent's HTTP-oriented clamp (<=300s): headless CLI
        # turns legitimately run longer.
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
        response_format: dict[str, Any] | None = None,
        _metadata_sink: dict[str, Any] | None = None,
        cache_plan: CachePlan | None = None,
    ) -> tuple[str, TokenUsage]:
        # max_tokens/temperature/stream/response_format/cache_plan are accepted
        # for interface parity with the base chat() but intentionally unused:
        # Claude Code manages its own sampling, output limits, and caching.
        if not self._validate_messages(messages):
            return "", TokenUsage()

        prompt = self._render_prompt(messages)
        mode = str(thinking).strip().lower() if thinking is not None else None
        effort = _EFFORT_FOR_THINKING.get(mode, "medium")

        cmd = [
            self._binary,
            "-p",
            "--output-format",
            "json",
            "--model",
            self.model,
            "--effort",
            effort,
            "--tools",
            "",
            "--no-session-persistence",
        ]
        if system:
            cmd.extend(["--system-prompt", system])

        try:
            # COMPLIANCE: no env= kwarg — the environment passes through
            # untouched; MUSCLE never injects or reads CLI credentials.
            proc = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProviderError(
                f"claude CLI call timed out after {self.timeout}s. Long headless turns "
                "can exceed the limit; raise the provider timeout or narrow the prompt."
            ) from exc

        if proc.returncode != 0:
            detail = f"{proc.stderr or ''}\n{proc.stdout or ''}".strip()
            self._raise_for_failure(detail)

        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            stderr_excerpt = (proc.stderr or "").strip()[:_ERROR_DETAIL_LIMIT]
            raise ProviderError(
                f"claude CLI returned non-JSON output: {proc.stdout[:200]!r}. "
                f"stderr: {stderr_excerpt}"
            ) from exc
        if not isinstance(data, dict):
            raise ProviderError(f"claude CLI returned unexpected JSON type: {type(data).__name__}")

        text = str(data.get("result") or "")
        if data.get("is_error"):
            self._raise_for_failure(text)

        if _metadata_sink is not None:
            _metadata_sink["stop_reason"] = data.get("stop_reason")
            _metadata_sink.setdefault("truncated", False)

        usage = self._parse_usage(data.get("usage"))
        if usage.input_tokens == 0 and usage.output_tokens == 0 and text:
            # The CLI omitted usage — estimate from prompt/response size
            # (~4 chars/token, same heuristic as the HTTP path) so Agent SDK
            # credit consumption stays visible in cost accounting.
            prompt_chars = len(prompt) + len(system or "")
            usage = TokenUsage(
                input_tokens=max(1, prompt_chars // 4),
                output_tokens=max(1, len(text) // 4),
            )
            if _metadata_sink is not None:
                _metadata_sink["usage_estimated"] = True
            logger.info(
                "claude CLI omitted usage; estimated %d input / %d output tokens "
                "(Agent SDK credit accounting)",
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
        """Parity shim: the CLI path has no token stream, so yield the single
        final (text, usage) from one blocking chat() call."""
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
    def _render_prompt(messages: list[dict]) -> str:
        """Render the message list deterministically for stdin delivery.

        A single user message passes through as its bare content; multi-turn
        histories render as "[role]\\ncontent" blocks joined by blank lines.
        """
        if len(messages) == 1 and messages[0].get("role") == "user":
            return str(messages[0].get("content", ""))
        return "\n\n".join(
            f"[{message.get('role', 'user')}]\n{message.get('content', '')}" for message in messages
        )

    @staticmethod
    def _parse_usage(usage_payload: Any) -> TokenUsage:
        """Map the CLI usage block to TokenUsage with cache_read folding.

        Same invariant as the HTTP path: input_tokens is normalized to the
        FULL prompt size (fresh + cached) and cached_input_tokens is the
        cached subset, so cached_input_tokens <= input_tokens always holds.
        """
        if not isinstance(usage_payload, dict):
            return TokenUsage()
        input_tokens = int(usage_payload.get("input_tokens") or 0)
        output_tokens = int(usage_payload.get("output_tokens") or 0)
        cache_read = int(usage_payload.get("cache_read_input_tokens") or 0)
        cache_creation = int(usage_payload.get("cache_creation_input_tokens") or 0)
        if cache_read or cache_creation:
            input_tokens += cache_read + cache_creation
        return TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cache_read,
            cache_creation_input_tokens=cache_creation,
        )

    @staticmethod
    def _raise_for_failure(detail: str) -> NoReturn:
        """Classify a CLI failure (stderr/stdout/result text) and raise."""
        lowered = detail.lower()
        excerpt = detail.strip()[:_ERROR_DETAIL_LIMIT]
        if any(marker in lowered for marker in _BILLING_MARKERS):
            raise ProviderBillingError(
                "Agent SDK credit exhausted: headless `claude -p` calls draw from the "
                "separate monthly Agent SDK credit pool on subscription plans (no "
                "rollover), not the interactive plan quota. Wait for the monthly reset "
                f"or enable extra usage billing. CLI said: {excerpt}"
            )
        if any(marker in lowered for marker in _AUTH_MARKERS):
            raise ProviderError(
                "The `claude` CLI is not authenticated. Run `claude` interactively, "
                f"authenticate, then retry. CLI said: {excerpt}"
            )
        raise ProviderError(f"claude CLI call failed: {excerpt}")
