"""
Evolver Agent - Analyzes failures and generates improved strategies.

Architecture Decision Record (ADR):
- Single responsibility: take errors and previous strategy, output improved strategy
- Uses M2.7's self-reflection capability
- Stores learned patterns for future sessions
- Strategies are stored in knowledge base for reuse
- Implements retry logic with exponential backoff
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterator

from .m27_client import M27Client, TokenUsage
from .strategy_kb import Strategy, StrategyKB

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert debugging and code improvement specialist working in a self-correction loop.
Your job is to analyze errors from failed code attempts and generate improved strategies.

WHY ROOT CAUSE ANALYSIS: Finding symptoms doesn't fix bugs. Finding the first error that caused cascade failures does.

When you receive errors, follow this analysis framework:
1. ROOT CAUSE ANALYSIS GUIDANCE:
   - Look for the FIRST error that caused cascade failures
   - Distinguish: syntax error (immediate) vs. logic error (runtime)
   - Check: wrong assumption about API/framework behavior
   - Verify: type mismatches, missing null checks, boundary conditions
2. Propose specific fixes for each root cause
3. Generate an improved strategy prompt that will guide the generator to avoid these mistakes

Be precise. Generic advice doesn't work. Focus on specific, actionable improvements.
"""


def _build_evolver_prompt(
    task: str,
    errors: list[str],
    previous_strategy: str | None,
    iteration: int,
    similar_strategies: list[Strategy] | None = None,
) -> str:
    safe_task = _sanitize_for_prompt(task)
    safe_errors: list[str] = [_sanitize_for_prompt(e) for e in errors if e]

    if not safe_errors:
        return "Error: No valid errors provided."

    errors_json = json.dumps(safe_errors, indent=2, ensure_ascii=False)

    prompt_parts = [
        "Analyze the following failed code attempt and generate an improved strategy.",
        "",
        f"Task: {safe_task}",
        f"Iteration: {iteration}",
        "",
        "Errors encountered:",
        errors_json,
        "",
    ]

    if similar_strategies and isinstance(similar_strategies, list):
        prompt_parts.append("Similar past strategies that worked:")
        for s in similar_strategies[:5]:
            if isinstance(s, Strategy):
                prompt_parts.append(
                    f'- Error: "{s.error_pattern}" -> Strategy: "{s.solution_strategy}"'
                )
        prompt_parts.append("")

    if previous_strategy and isinstance(previous_strategy, str):
        safe_prev = _sanitize_for_prompt(previous_strategy)
        prompt_parts.extend(
            [
                "Previous strategy that was used (learn from its failures):",
                safe_prev,
                "",
            ]
        )

    prompt_parts.extend(
        [
            "Your response must be a JSON object with this exact structure:",
            "{",
            '  "root_causes": ["specific root cause of error 1", ...],',
            '  "fixes": ["specific fix for error 1", ...],',
            '  "evolved_strategy": "A complete strategy prompt (2-4 sentences)..."',
            "}",
            "",
            "Analyze carefully and respond with ONLY the JSON object.",
        ]
    )

    return "\n".join(prompt_parts)


def _sanitize_for_prompt(text: str | None) -> str:
    if not text:
        return ""
    if not isinstance(text, str):
        text = str(text)
    text = text.replace("\x00", "")
    text = text.replace("\r\n", "\n")
    if len(text) > 2000:
        text = text[:2000] + "... [truncated]"
    return text.strip()


class Evolver:
    def __init__(
        self,
        m27_client: M27Client,
        max_retries: int = 3,
        retry_delay: float = 2.0,
        use_kb: bool = True,
        kb_path: str | None = None,
    ):
        self.client = m27_client
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._strategy_history: list[str] = []
        self.use_kb = use_kb
        self.kb = StrategyKB(kb_path=kb_path) if use_kb else None

    def evolve(
        self,
        task: str,
        errors: list[str],
        previous_strategy: str | None,
        iteration: int = 1,
    ) -> tuple[str, TokenUsage]:
        if not errors or not any(e for e in errors if e and str(e).strip()):
            logger.warning("Evolver called with no valid errors")
            return "No errors to analyze. Continue with current approach.", TokenUsage()

        safe_task = _sanitize_for_prompt(task)
        safe_errors = [str(e).strip() for e in errors if e and str(e).strip()]

        if not safe_errors:
            return "No errors to analyze. Continue with current approach.", TokenUsage()

        logger.info(f"Evolving strategy for {len(safe_errors)} errors (iteration {iteration})")

        similar_strategies: list[Strategy] = []
        if self.kb:
            try:
                error_combined = " ".join(safe_errors[:10])
                if error_combined:
                    similar_strategies = (
                        self.kb.find_similar_strategies(error_combined, top_k=3) or []
                    )
                    if similar_strategies:
                        logger.info(f"Found {len(similar_strategies)} similar strategies from KB")
            except Exception as e:
                logger.warning(f"Failed to query strategy KB: {e}")
                similar_strategies = []

        prompt = _build_evolver_prompt(
            safe_task, safe_errors, previous_strategy, iteration, similar_strategies
        )

        response = ""
        usage = TokenUsage()
        last_error = None

        for attempt in range(self.max_retries):
            try:
                response, usage = self.client.chat(
                    messages=[{"role": "user", "content": prompt}],
                    system=SYSTEM_PROMPT,
                    max_tokens=2048,
                )

                if not response or response.strip() == "":
                    last_error = "Empty response from API"
                    logger.warning(f"Attempt {attempt + 1}: Empty response, retrying...")
                    time.sleep(self.retry_delay)
                    continue

                break

            except Exception as e:
                last_error = str(e)
                logger.warning(f"Attempt {attempt + 1} failed: {last_error}")

                if "429" in str(e) or "rate limit" in str(e).lower():
                    time.sleep(self.retry_delay * 2)
                else:
                    time.sleep(self.retry_delay)

        if not response:
            logger.error(f"All {self.max_retries} attempts failed")
            return f"Evolution failed after {self.max_retries} attempts: {last_error}", TokenUsage()

        evolved_strategy: str | None = self._parse_strategy(response)

        if evolved_strategy:
            safe_strategy = _sanitize_for_prompt(evolved_strategy)
            self._strategy_history.append(safe_strategy)
            logger.info(f"Evolved strategy: {safe_strategy[:100]}...")

            if self.kb and safe_errors:
                try:
                    root_causes = self._extract_root_causes(response)
                    error_combined = "; ".join(safe_errors[:3])
                    self.kb.add_strategy(
                        error_pattern=error_combined,
                        root_cause=root_causes,
                        solution_strategy=safe_strategy,
                    )
                except Exception as e:
                    logger.warning(f"Failed to save strategy to KB: {e}")
        else:
            logger.warning("Failed to parse evolved strategy from response")
            evolved_strategy = "Analyze errors and try a different approach."

        return evolved_strategy, usage

    def _parse_strategy(self, response: str) -> str | None:
        try:
            start = response.find("{")
            end = response.rfind("}") + 1
            if start == -1 or end == 0:
                return self._extract_fallback_strategy(response)

            json_str = response[start:end]
            data = json.loads(json_str)
            strategy = data.get("evolved_strategy")

            if strategy:
                return strategy  # type: ignore[no-any-return]

            root_causes = data.get("root_causes", [])
            fixes = data.get("fixes", [])
            if root_causes or fixes:
                combined = (
                    " ".join(str(r) for r in root_causes) + " " + " ".join(str(f) for f in fixes)
                )
                return combined[:500]

            return self._extract_fallback_strategy(response)

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse JSON from evolver response: {e}")
            return self._extract_fallback_strategy(response)

    def _extract_root_causes(self, response: str) -> str:
        try:
            start = response.find("{")
            end = response.rfind("}") + 1
            if start == -1 or end == 0:
                return "Unknown root cause"
            json_str = response[start:end]
            data = json.loads(json_str)
            root_causes = data.get("root_causes", [])
            if root_causes:
                return "; ".join(str(r) for r in root_causes)
        except Exception:
            pass
        return "Unknown root cause"

    def _extract_fallback_strategy(self, response: str) -> str | None:
        if len(response) > 20:
            cleaned = response.strip()
            if len(cleaned) > 500:
                cleaned = cleaned[:500]
            return cleaned
        return None

    def get_strategy_history(self) -> list[str]:
        return self._strategy_history.copy()

    def evolve_streaming(
        self,
        task: str,
        errors: list[str],
        previous_strategy: str | None,
        iteration: int = 1,
        progress_callback: Callable[[str], None] | None = None,
    ) -> Iterator[tuple[str, TokenUsage]]:
        if not errors:
            logger.warning("Evolver called with no errors")
            yield "No errors to analyze. Continue with current approach.", TokenUsage()
            return

        logger.info(
            f"Evolving strategy for {len(errors)} errors (iteration {iteration}) (streaming)"
        )

        prompt = _build_evolver_prompt(task, errors, previous_strategy, iteration)

        full_response = ""

        for accumulated_text, _usage in self.client.chat_streaming(
            messages=[{"role": "user", "content": prompt}],
            system=SYSTEM_PROMPT,
            max_tokens=2048,
        ):
            full_response = accumulated_text
            if progress_callback and accumulated_text:
                progress_callback(accumulated_text)
            yield "", TokenUsage()

        if full_response:
            evolved_strategy: str | None = self._parse_strategy(full_response)
            if evolved_strategy:
                self._strategy_history.append(evolved_strategy)
                logger.info(f"Evolved strategy: {evolved_strategy[:100]}...")
            else:
                logger.warning("Failed to parse evolved strategy from response")
                evolved_strategy = "Analyze errors and try a different approach."
            yield evolved_strategy, TokenUsage()
        else:
            yield f"Evolution failed after {self.max_retries} attempts", TokenUsage()
