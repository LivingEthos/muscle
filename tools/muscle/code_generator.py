"""
Code Generator Agent - Uses M2.7 to generate code based on task and evolved strategies.

Architecture Decision Record (ADR):
- Separates code generation from loop logic for testability
- Uses structured prompts with task + strategy + context
- Returns both generated code and token usage for budget tracking
- Supports multiple programming languages via prompt engineering
- Handles non-code-block responses gracefully
- Implements intelligent code extraction with fallbacks
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .cost_optimizer import CostOptimizer
    from .optimization.context_budgeter import ContextBudgeter

from .m27_client import STREAM_ERROR_PREFIX, M27Client, TokenUsage
from .optimization.prompt_context import build_telemetry_context, compose_prompt_envelope

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert code generator working in a self-improvement loop.
You receive a task to complete, along with evolved strategies from previous failed attempts.
Your goal is to generate code that passes ALL evaluation checks.

WHY THIS MATTERS: Your code will be automatically evaluated. Poor edge-case handling = immediate failure.
This code runs in production without supervision.

IMPORTANT: You MUST output code in proper code blocks with filename comments.

Output format example (use markdown code blocks with language identifier):
  "```python"
  "# filename.py"
  "def function():"
  "    pass"
  "```"

Guidelines:
1. Consider edge cases and error handling
2. Follow best practices for the target language
3. Include comprehensive tests
4. Ensure code is production-ready
5. Do NOT repeat mistakes from previous iterations
6. ALWAYS use code blocks with language identifiers
7. Add brief reasoning comment for complex logic

TASK APPROACH for complex tasks:
1. First understand the structure needed
2. Generate core modules first
3. Then add tests
4. Verify imports are consistent

If context nears capacity, stop and summarize what you completed vs. remaining.
"""


@dataclass
class GenerationResult:
    success: bool
    files_written: list[str]
    token_usage: int
    raw_response: str
    error: str | None = None


def _build_user_prompt(
    task: str,
    evolved_strategy: str,
    output_dir: str,
    language: str | None,
    project_structure: str | None = None,
) -> str:
    safe_task = _sanitize_for_prompt(task)
    safe_output_dir = _sanitize_for_prompt(output_dir)
    safe_language = _sanitize_for_prompt(language) if language else None

    prompt_parts = [f"Task: {safe_task}", ""]

    prompt_parts.append(f"Output directory: {safe_output_dir}")

    if safe_language:
        prompt_parts.append(f"Language: {safe_language}")
    else:
        prompt_parts.append("(Auto-detect language from task)")

    prompt_parts.append("")

    if project_structure:
        safe_structure = _sanitize_for_prompt(project_structure)
        prompt_parts.append(f"Project Structure:\n{safe_structure}\n")

    if evolved_strategy:
        safe_strategy = _sanitize_for_prompt(evolved_strategy)
        prompt_parts.append(
            f"Previous evolved strategy (learn from this to avoid same mistakes):\n{safe_strategy}\n"
        )

    prompt_parts.extend(
        [
            "Generate the complete code solution.",
            "CRITICAL: Output code in proper code blocks with filename comments.",
            "",
            "Example format:",
            "```python",
            "# filename.py",
            "def hello():",
            '    print("Hello World")',
            "```",
            "",
            "Write all necessary files to the output directory.",
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
    if len(text) > 5000:
        text = text[:5000] + "... [truncated]"
    return text.strip()


class CodeGenerator:
    def __init__(
        self,
        m27_client: M27Client,
        max_retries: int = 3,
        retry_delay: float = 2.0,
        cost_optimizer: CostOptimizer | None = None,
        context_budgeter: ContextBudgeter | None = None,
        project_path: str | None = None,
        lesson_resolver: object | None = None,
    ):
        self.client = m27_client
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.cost_optimizer = cost_optimizer
        self.context_budgeter = context_budgeter
        self.project_path = project_path or str(Path.cwd())
        self.lesson_resolver = lesson_resolver

    def generate(
        self,
        task: str,
        evolved_strategy: str,
        output_dir: str,
        project_structure: str | None = None,
        session_id: str | None = None,
    ) -> tuple[str, TokenUsage]:
        if not task or not task.strip():
            logger.error("Empty task provided to generate()")
            return "Error: Task cannot be empty", TokenUsage()

        safe_task = task.strip()
        if len(safe_task) > 10000:
            safe_task = safe_task[:10000]
            logger.warning("Task truncated to 10000 characters")

        try:
            output_path = Path(output_dir).resolve()
            output_path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Cannot create output directory: {e}")
            return f"Error: Cannot access output directory: {e}", TokenUsage()

        max_tokens = 8192
        trimmed_strategy = (
            self.context_budgeter.trim_strategy_text(evolved_strategy)
            if self.context_budgeter
            else (evolved_strategy or "")
        )
        trimmed_structure = (
            self.context_budgeter.trim_project_structure(project_structure)
            if self.context_budgeter
            else project_structure
        )
        cache_lookup_task = self._build_cache_lookup_task(
            safe_task,
            trimmed_strategy,
            trimmed_structure,
        )
        if self.cost_optimizer:
            cached = self.cost_optimizer.get_from_cache(cache_lookup_task)
            cached_files = cached.get("files", []) if cached else []
            if cached and self._cached_files_available(cached_files, output_path):
                logger.info(
                    "Using cached result for task: %s...",
                    safe_task[:50],
                )
                for filename in cached_files:
                    if not isinstance(filename, str):
                        continue
                    logger.info(f"Using cached file: {filename}")
                return f"Generated {len(cached_files)} files (from cache)", TokenUsage()
            if cached:
                logger.info(
                    "Cache entry for task %s is stale or incomplete, regenerating",
                    safe_task[:50],
                )

            tier = self.cost_optimizer.estimate_tier(safe_task)
            max_tokens = self.cost_optimizer.get_max_tokens(tier)

        user_prompt = _build_user_prompt(
            safe_task,
            trimmed_strategy,
            str(output_path),
            None,
            trimmed_structure,
        )
        base_context_strategy = (
            "trimmed_generation_prompt" if self.context_budgeter else "default_generation_prompt"
        )
        prompt_envelope = compose_prompt_envelope(
            base_prompt=user_prompt,
            lesson_resolver=self.lesson_resolver,
            query_text=safe_task,
            stage="generate",
            base_context_strategy=base_context_strategy,
            session_id=session_id,
        )
        user_prompt = prompt_envelope.prompt

        logger.info(f"Generating code for task: {safe_task[:50]}...")

        response = ""
        usage = TokenUsage()
        last_error = None
        telemetry_context = None

        for attempt in range(self.max_retries):
            try:
                telemetry_context = build_telemetry_context(
                    project_path=self.project_path,
                    session_id=session_id,
                    stage="generate",
                    prompt_envelope=prompt_envelope,
                )
                response, usage = self.client.chat(
                    messages=[{"role": "user", "content": user_prompt}],
                    system=SYSTEM_PROMPT,
                    max_tokens=max_tokens,
                    telemetry_context=telemetry_context,
                )

                if not response or response.strip() == "":
                    last_error = "Empty response from API"
                    logger.warning(f"Attempt {attempt + 1}: Empty response, retrying...")
                    time.sleep(self.retry_delay)
                    continue

                parse_success = bool(response and response.strip())
                if telemetry_context:
                    self.client.update_telemetry_call(
                        telemetry_context.call_id,
                        parse_success=parse_success,
                    )

                break

            except Exception as e:
                last_error = str(e)
                logger.warning(f"Attempt {attempt + 1} failed: {last_error}")

                if "429" in str(e) or "rate limit" in str(e).lower():
                    time.sleep(self.retry_delay * 2)
                elif "timeout" in str(e).lower():
                    time.sleep(self.retry_delay)
                else:
                    time.sleep(self.retry_delay)

        if not response:
            logger.error(f"All {self.max_retries} attempts failed. Last error: {last_error}")
            return f"Generation failed: {last_error}", TokenUsage()

        logger.info(f"Generated {len(response)} chars, used {usage.total} tokens")

        code_output, files_written = self._parse_and_write(response, output_path)

        if telemetry_context:
            self.client.update_telemetry_call(
                telemetry_context.call_id,
                parse_success=bool(files_written),
                metadata_updates={"files_written": len(files_written)},
            )

        if self.cost_optimizer and files_written:
            self.cost_optimizer.save_to_cache(cache_lookup_task, code_output, files_written)

        return code_output, usage

    @staticmethod
    def _cached_files_available(files: list[object], output_path: Path) -> bool:
        """Return True when every cached file still exists in the target output directory."""
        valid_files = [str(filename) for filename in files if isinstance(filename, str)]
        if not valid_files:
            return False
        return all((output_path / filename).exists() for filename in valid_files)

    @staticmethod
    def _build_cache_lookup_task(
        task: str,
        evolved_strategy: str,
        project_structure: str | None,
    ) -> str:
        """Build a stable cache key payload that includes retry-relevant generation context."""
        cache_parts = [f"task={task.strip()}"]
        if evolved_strategy.strip():
            cache_parts.append(f"strategy={evolved_strategy.strip()}")
        if project_structure and project_structure.strip():
            cache_parts.append(f"structure={project_structure.strip()}")
        return "\n---\n".join(cache_parts)

    def _parse_and_write(self, response: str, output_dir: Path) -> tuple[str, list[str]]:
        if not response:
            logger.error("Empty response provided to _parse_and_write")
            return "Error: Empty response", []

        files_written = []

        try:
            code_blocks = self._extract_code_blocks(response)
        except (OSError, UnicodeError, re.error) as e:
            # Fix: CG-04. Narrow to expected I/O and regex errors so that
            # programming errors (e.g. TypeError, AttributeError) propagate.
            logger.error(f"Error extracting code blocks: {e}")
            code_blocks = []

        if code_blocks:
            for filename, content in code_blocks:
                try:
                    safe_filename = self._write_output_file(
                        output_dir,
                        filename,
                        content,
                        default_filename="generated_code.py",
                    )
                    files_written.append(safe_filename)
                    logger.info("Wrote code block: %s", safe_filename)
                except (OSError, ValueError) as e:
                    logger.error("Cannot write file %s: %s", filename, e)
                    continue
        else:
            logger.warning("No code blocks found. Attempting alternative extraction...")

            try:
                alt_files = self._extract_alternative(response, output_dir)
                if alt_files:
                    files_written.extend(alt_files)
                else:
                    plain_code = self._extract_plain_code(response)
                    if plain_code:
                        # Fix: CG-05. Round-trip through UTF-8 with replacement to
                        # strip any non-encodable surrogates or lone high bytes that
                        # could cause write_text() to raise on some platforms.
                        safe_plain = plain_code.encode("utf-8", "replace").decode("utf-8")
                        if safe_plain != plain_code:
                            logger.warning(
                                "Plain-code fallback: replaced non-UTF-8 characters before emit"
                            )
                        written_name = self._write_output_file(
                            output_dir,
                            "generated_code.py",
                            safe_plain,
                            default_filename="generated_code.py",
                        )
                        files_written.append(written_name)
                        logger.info("Wrote extracted code as generated_code.py")
            except Exception as e:
                logger.error(f"Error in alternative extraction: {e}")

        if not files_written:
            logger.warning("No files parsed. Writing raw response.")
            try:
                written_name = self._write_output_file(
                    output_dir,
                    "generated_output.txt",
                    response,
                    default_filename="generated_output.txt",
                )
                files_written.append(written_name)
            except (OSError, ValueError) as e:
                logger.error(f"Cannot write fallback file: {e}")
                return "Error: Cannot write files", []

        logger.info(f"Wrote {len(files_written)} files: {', '.join(files_written)}")
        return f"Generated {len(files_written)} files", files_written

    def _write_output_file(
        self,
        output_dir: Path,
        filename: str,
        content: str,
        *,
        default_filename: str,
    ) -> str:
        relative_name = self._normalize_output_relative_path(filename, default_filename)
        file_path = self._resolve_output_path(output_dir, relative_name)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        safe_content = self._sanitize_content(content)
        file_path.write_text(safe_content, encoding="utf-8")
        return relative_name

    def _normalize_output_relative_path(self, filename: str, default_filename: str) -> str:
        normalized = unicodedata.normalize("NFC", filename or default_filename)
        normalized = normalized.replace("\x00", "").strip()
        if not normalized:
            normalized = default_filename

        if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
            raise ValueError(f"Absolute output paths are not allowed: {filename}")
        if "\\" in normalized:
            raise ValueError(f"Backslash-separated output paths are not allowed: {filename}")

        parts = [part for part in normalized.split("/") if part]
        if not parts:
            parts = [default_filename]
        if any(part in {".", ".."} for part in parts):
            raise ValueError(f"Traversal output paths are not allowed: {filename}")

        relative_path = "/".join(parts)
        if len(relative_path) > 255:
            relative_path = relative_path[:255]
        return relative_path

    @staticmethod
    def _resolve_output_path(output_dir: Path, relative_name: str) -> Path:
        root = output_dir.resolve()
        target = (root / relative_name).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            msg = f"Output path escapes target directory: {relative_name}"
            raise ValueError(msg) from exc
        return target

    def _sanitize_content(self, content: str) -> str:
        if not content:
            return ""
        content = content.replace("\x00", "")
        content = content.replace("\r\n", "\n")
        return content.encode("utf-8", errors="replace").decode("utf-8")

    def generate_streaming(
        self,
        task: str,
        evolved_strategy: str,
        output_dir: str,
        progress_callback: Callable[[str], None] | None = None,
        project_structure: str | None = None,
    ) -> Iterator[tuple[str, TokenUsage]]:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        user_prompt = _build_user_prompt(
            task, evolved_strategy, output_dir, None, project_structure
        )

        logger.info(f"Generating code for task: {task[:50]}... (streaming)")

        previous_text = ""
        final_usage = TokenUsage()

        stream_error: str | None = None
        for accumulated_text, usage in self.client.chat_streaming(
            messages=[{"role": "user", "content": user_prompt}],
            system=SYSTEM_PROMPT,
            max_tokens=8192,
        ):
            if usage is not None:
                final_usage = usage

            if not accumulated_text:
                continue

            # Fix: M27-04. Detect streaming-error sentinel emitted by M27Client
            # when all retries failed, so we surface a real error rather than
            # silently returning an empty response.
            if accumulated_text.startswith(STREAM_ERROR_PREFIX):
                stream_error = accumulated_text[len(STREAM_ERROR_PREFIX) :]
                logger.error(f"Streaming failed: {stream_error}")
                break

            delta = accumulated_text[len(previous_text) :]
            previous_text = accumulated_text
            if progress_callback and delta:
                progress_callback(delta)
            if delta and not progress_callback:
                yield delta, final_usage

        # Fix: [CG-02] Assign full_response once after the loop completes.
        # Moving this out of the loop body eliminates the redundant O(n) string
        # copy that previously occurred on every streaming chunk.
        full_response = previous_text

        if stream_error:
            yield f"Generation failed: {stream_error}", final_usage
        elif full_response:
            logger.info(f"Generated {len(full_response)} chars")
            code_output, _ = self._parse_and_write(full_response, output_path)
            yield code_output, final_usage
        else:
            yield "Generation failed: empty response", TokenUsage()

    # Fix: CG-03. Cap input size before running ``re.DOTALL`` patterns on
    # untrusted model output to bound regex backtracking cost.
    _MAX_REGEX_INPUT_BYTES = 1_048_576  # 1 MiB

    def _extract_code_blocks(self, text: str) -> list[tuple[str, str]]:
        blocks = []

        if len(text) > self._MAX_REGEX_INPUT_BYTES:
            logger.warning(
                "Code block extraction truncated input from %d to %d bytes",
                len(text),
                self._MAX_REGEX_INPUT_BYTES,
            )
            text = text[: self._MAX_REGEX_INPUT_BYTES]

        pattern = r"```(\w+)?\s*(?:\/\/\s*([^\n]+?))?\s*\n(.*?)```"
        matches = re.finditer(pattern, text, re.DOTALL)

        for match in matches:
            lang = match.group(1) or ""
            content = match.group(3)
            embedded_filename, content = self._extract_embedded_filename(content)
            filename = match.group(2) or embedded_filename or self._infer_filename(lang, content)

            if content:
                blocks.append((filename, content))

        if not blocks:
            simple_pattern = r"```\s*\n(.*?)```"
            simple_matches = re.finditer(simple_pattern, text, re.DOTALL)
            for match in simple_matches:
                content = match.group(1)
                if content and len(content) > 20:
                    lang = self._detect_language(content)
                    embedded_filename, content = self._extract_embedded_filename(content)
                    filename = embedded_filename or self._infer_filename(lang, content)
                    blocks.append((filename, content))

        if not blocks:
            blocks = self._extract_inline_code_blocks(text)

        return blocks

    @staticmethod
    def _extract_embedded_filename(content: str) -> tuple[str | None, str]:
        """Extract a filename from the first meaningful line inside a fenced code block."""
        lines = content.splitlines()
        if not lines:
            return None, content

        filename_patterns = [
            r"^(?:#|//)\s*([a-zA-Z_][a-zA-Z0-9_./-]*\.(?:py|js|ts|go|java|rs|cpp|c|h|cs))\s*$",
            r"^/\*\s*([a-zA-Z_][a-zA-Z0-9_./-]*\.(?:py|js|ts|go|java|rs|cpp|c|h|cs))\s*\*/$",
        ]

        for index, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            for pattern in filename_patterns:
                match = re.match(pattern, stripped)
                if match:
                    remaining_lines = lines[:index] + lines[index + 1 :]
                    remaining_content = "\n".join(remaining_lines).lstrip("\n")
                    return match.group(1), remaining_content
            break

        return None, content

    def _extract_inline_code_blocks(self, text: str) -> list[tuple[str, str]]:
        blocks = []

        here_is_code_pattern = r"(?:Here\s+is\s+(?:the\s+)?code(?:s?)|Here(?:\'s| is) (?:the )?code(?:s?)|(?:Below|Below\s+is)(?:\s+the)? code):?\s*\n+(.*?)(?:\n\n|\Z)"
        matches = re.finditer(here_is_code_pattern, text, re.IGNORECASE | re.DOTALL)
        for match in matches:
            content = match.group(1).strip()
            if content and len(content) > 20:
                lang = self._detect_language(content)
                filename = self._infer_filename(lang, content)
                blocks.append((filename, content))
                break

        if not blocks:
            code_after_title = re.finditer(
                r"^#+\s*.+?\n(.*?)(?=^#|\Z)", text, re.DOTALL | re.MULTILINE
            )
            for match in code_after_title:
                content = match.group(1).strip()
                if content and len(content) > 30 and self._looks_like_code(content):
                    lang = self._detect_language(content)
                    filename = self._infer_filename(lang, content)
                    blocks.append((filename, content))
                    break

        return blocks

    def _looks_like_code(self, text: str) -> bool:
        code_indicators = [
            r"\bdef\s+\w+\s*\(",
            r"\bclass\s+\w+",
            r"\bfunction\s+\w+\s*\(",
            r"\bfunc\s+\w+\s*\(",
            r"\bfn\s+\w+\s*\(",
            r"\bconst\s+\w+\s*=",
            r"\blet\s+\w+\s*=",
            r"\bpublic\s+(?:static\s+)?(?:void|class)",
            r"\bprivate\s+(?:void|class)",
            r"\bpackage\s+\w+",
            r"\bimport\s+\w+",
            r"\bfrom\s+\w+\s+import",
            r'\bif\s+__name__\s*==\s*["\']__main__["\']',
            r"=>\s*\{",
            r"\{\s*\n",
        ]
        score = sum(1 for pattern in code_indicators if re.search(pattern, text))
        return score >= 1

    def _extract_alternative(self, text: str, output_dir: Path) -> list[str]:
        files = []

        file_pattern = (
            r"(?:^|\n)([a-zA-Z_][a-zA-Z0-9_]*\.(?:py|js|ts|go|java|rs|cpp|c|h|cs))(?:\s*:|,|\n)"
        )
        matches = re.findall(file_pattern, text)

        for filename in set(matches):
            if any(ext in filename for ext in [".py", ".js", ".ts", ".go", ".java", ".rs", ".cpp"]):
                pos = text.find(filename)
                if pos != -1:
                    start = text.rfind("\n", 0, pos + 1)
                    section = text[start : start + 2000]
                    written_name = self._write_output_file(
                        output_dir,
                        filename,
                        section,
                        default_filename="generated_code.py",
                    )
                    files.append(written_name)

        if not files:
            files = self._extract_filelist_alternative(text, output_dir)

        return files

    def _extract_filelist_alternative(self, text: str, output_dir: Path) -> list[str]:
        files = []

        file_list_pattern = (
            r"(?:^|\n)([a-zA-Z_][a-zA-Z0-9_]*\.(?:py|js|ts|go|java|rs|cpp|c|h|cs))(?:\s*\n|$)"
        )
        matches = re.findall(file_list_pattern, text, re.MULTILINE)

        seen = set()
        for filename in matches:
            if filename in seen:
                continue
            seen.add(filename)

            pos = text.find(filename)
            if pos == -1:
                continue

            code_start = pos + len(filename)
            code_section = text[code_start : code_start + 5000]

            fence_match = re.search(r"```", code_section)
            if fence_match:
                code_section = code_section[: fence_match.start()]

            code_section = code_section.strip()
            if code_section and len(code_section) > 10:
                lang = self._detect_language(code_section)
                if lang:
                    written_name = self._write_output_file(
                        output_dir,
                        filename,
                        code_section,
                        default_filename="generated_code.py",
                    )
                    files.append(written_name)
                    continue

            code_start = text.rfind("\n", 0, pos)
            next_section_start = text.find("\n\n", pos)
            if next_section_start == -1:
                next_section_start = len(text)
            section = text[code_start:next_section_start].strip()
            if section and len(section) > 20:
                written_name = self._write_output_file(
                    output_dir,
                    filename,
                    section,
                    default_filename="generated_code.py",
                )
                files.append(written_name)

        return files

    def _extract_plain_code(self, text: str) -> str | None:
        lines = text.split("\n")
        code_lines = []
        in_code = False

        code_start_patterns = [
            (r"^\s*def\s+\w+\s*\(", "python"),
            (r"^\s*class\s+\w+", "python"),
            (r"^\s*function\s+\w+\s*\(", "javascript"),
            (r"^\s*const\s+\w+\s*=", "javascript"),
            (r"^\s*let\s+\w+\s*=", "javascript"),
            (r"^\s*func\s+\w+\s*\(", "go"),
            (r"^\s*fn\s+\w+\s*\(", "rust"),
            (r"^\s*pub\s+fn\s+\w+\s*\(", "rust"),
            (r"^\s*use\s+\w+", "rust"),
            (r"^\s*public\s+(?:static\s+)?(?:void|class)", "java"),
            (r"^\s*private\s+(?:void|class)", "java"),
            (r"^\s*package\s+\w+", "java"),
            (r"^\s*import\s+", "java"),
            (r"^\s*#include\s*", "cpp"),
            (r"^\s*#ifndef\s+\w+", "c"),
            (r"^\s*export\s+", "typescript"),
        ]

        name_main_pattern = re.compile(r'^\s*if\s+__name__\s*==\s*["\']__main__["\']\s*:\s*$')
        main_func_patterns = [
            (r"^\s*def\s+main\s*\(", "python"),
            (r"^\s*func\s+main\s*\(", "go"),
            (r"^\s*fn\s+main\s*\(", "rust"),
            (r"^\s*int\s+main\s*\(", "cpp"),
            (r"^\s*public\s+static\s+void\s+main\s*\(", "java"),
        ]

        for i, line in enumerate(lines):
            stripped = line.strip()

            if not in_code:
                for pattern, _ in code_start_patterns:
                    if re.match(pattern, stripped):
                        in_code = True
                        break

                if not in_code and name_main_pattern.match(stripped):
                    in_code = True

                if not in_code:
                    for pattern, _ in main_func_patterns:
                        if re.match(pattern, stripped):
                            in_code = True
                            break

            if in_code:
                code_lines.append(line)
            elif (
                code_lines
                and len(code_lines) > 0
                and stripped
                and not stripped.startswith("#")
                and not stripped.startswith("//")
            ):
                if any(re.match(p, stripped) for p, _ in code_start_patterns):
                    code_lines = []
                    in_code = True
                    code_lines.append(line)
                    continue
                if name_main_pattern.match(stripped):
                    code_lines = []
                    in_code = True
                    code_lines.append(line)

            if in_code and len(code_lines) > 5:
                next_lines = "\n".join(lines[i + 1 : i + 3])
                if not stripped and not next_lines.strip():
                    break

        if len(code_lines) > 3:
            return "\n".join(code_lines)

        if not code_lines:
            code_lines = self._extract_code_lines_by_indentation(lines)

        if len(code_lines) > 3:
            return "\n".join(code_lines)

        return None

    def _extract_code_lines_by_indentation(self, lines: list[str]) -> list[str]:
        if not lines:
            return []

        code_lines = []
        in_code = False
        indent_threshold = 0

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            leading_spaces = len(line) - len(line.lstrip())

            if not in_code:
                if (
                    stripped.startswith("def ")
                    or stripped.startswith("class ")
                    or stripped.startswith("function ")
                    or stripped.startswith("func ")
                    or stripped.startswith("fn ")
                ):
                    in_code = True
                    code_lines.append(line)
                    indent_threshold = leading_spaces
                    continue

            if in_code:
                if (
                    leading_spaces >= indent_threshold
                    or not stripped
                    or stripped.startswith("#")
                    or stripped.startswith("//")
                    or stripped.startswith("*")
                ):
                    code_lines.append(line)
                else:
                    if len(code_lines) > 10:
                        break
                    code_lines = []
                    in_code = False

        return code_lines

    def _detect_language(self, code: str) -> str:
        patterns = {
            "python": [
                r"\bdef\s+\w+\s*\(",
                r"\bclass\s+\w+.*:",
                r"\bimport\s+\w+",
                r"\bfrom\s+\w+\s+import",
                r'\bif\s+__name__\s*==\s*["\']__main__["\']',
                r"\bprint\s*\(",
                r"\belif\s+\w+",
                r"\basync\s+def\s+",
                r"\bawait\s+",
                r":\s*$",
            ],
            "javascript": [
                r"\bfunction\s+\w+\s*\(",
                r"\bconst\s+\w+\s*=",
                r"\blet\s+\w+\s*=",
                r"\bconsole\.(log|error|warn)\s*\(",
                r"=>\s*\{",
                r"\brequire\s*\(",
                r"\bmodule\.exports\s*=",
                r"\bexport\s+(?:default|const|let|function)",
                r'\bimport\s+.*\s+from\s+["\']',
            ],
            "typescript": [
                r":\s*(?:string|number|boolean|any|void|never)\b",
                r"\binterface\s+\w+",
                r"\btype\s+\w+\s*=",
                r"<\w+>\s*\(",
                r"\bas\s+\w+",
                r":\s*\w+\[\]",
            ],
            "go": [
                r"\bfunc\s+\w+\s*\(",
                r"\bpackage\s+\w+",
                r"\bimport\s+\(",
                r"\bfmt\.Print",
                r"\berr\s*!=?\s*nil",
                r"\bgo\s+func\s*\(",
                r":=\s*$",
            ],
            "java": [
                r"\bpublic\s+class\s+\w+",
                r"\bprivate\s+(?:static\s+)?(?:void|int|String)",
                r"\bSystem\.out\.print",
                r"\bpublic\s+static\s+void\s+main\s*\(",
                r"\bnew\s+\w+\s*\(",
                r"\bextends\s+\w+",
                r"\bimplements\s+\w+",
            ],
            "rust": [
                r"\bfn\s+\w+\s*\(",
                r"\bpub\s+fn\s+",
                r"\blet\s+mut\s+",
                r"\bimpl\s+\w+",
                r"\buse\s+\w+::",
                r"\bmatch\s+\w+",
                r"->\s*(?:\w+|Self)",
                r"\bprintln!\s*\(",
                r"\bvec!\[",
                r"\bSome\(",
                r"\bNone\b",
            ],
            "cpp": [
                r"#include\s*<",
                r"\bstd::",
                r"\bcout\s*<<",
                r"\bcin\s*>>",
                r"\bint\s+main\s*\(",
                r"\bvoid\s+\w+\s*\(",
                r"\bclass\s+\w+\s*\{",
                r"\btemplate\s*<",
            ],
            "c": [
                r"#include\s*<stdio\.h>",
                r"#include\s*<stdlib\.h>",
                r"\bprintf\s*\(",
                r"\bmalloc\s*\(",
                r"\bint\s+main\s*\(",
                r"#ifndef\s+\w+",
            ],
        }

        scores = {}
        for lang, lang_patterns in patterns.items():
            scores[lang] = sum(1 for p in lang_patterns if re.search(p, code))

        if max(scores.values()) == 0:
            if "def " in code and ":" in code:
                return "python"
            if "function " in code or "const " in code or "let " in code:
                return "javascript"
            if "func " in code:
                return "go"
            if "fn " in code:
                return "rust"
            if "public class" in code:
                return "java"
            return "python"

        return max(scores, key=lambda k: scores[k]) if scores else "python"

    def _infer_filename(self, lang: str, content: str) -> str:
        comment_filename_patterns = [
            r"^[#\/]\s*(?:file(?:name)?|file):\s*([a-zA-Z_][a-zA-Z0-9_]*\.(?:py|js|ts|go|java|rs|cpp|c|h|cs))",
            r"^[#\/]\s*(?:name):\s*([a-zA-Z_][a-zA-Z0-9_]*\.(?:py|js|ts|go|java|rs|cpp|c|h|cs))",
            r'^"""\s*([a-zA-Z_][a-zA-Z0-9_]*\.(?:py|js|ts|go|java|rs|cpp|c|h|cs))\s*"""',
        ]

        for pattern in comment_filename_patterns:
            match = re.search(pattern, content, re.MULTILINE)
            if match:
                return match.group(1)

        if lang in ["python", "py"]:
            if "Flask" in content or "fastapi" in content.lower():
                return "app.py"
            if "django" in content.lower():
                return "views.py"
            if "unittest" in content or "pytest" in content:
                return "test_main.py"
            return "main.py"

        if lang in ["javascript", "js"]:
            if "express" in content.lower():
                return "server.js"
            if "react" in content.lower():
                return "App.js"
            if "node" in content.lower():
                return "index.js"
            return "index.js"

        lang_map = {
            "javascript": "index.js",
            "js": "index.js",
            "typescript": "index.ts",
            "ts": "index.ts",
            "go": "main.go",
            "java": "Main.java",
            "rust": "main.rs",
            "cpp": "main.cpp",
            "c": "main.c",
        }

        return lang_map.get(lang, f"main.{lang}" if lang else "main.py")
