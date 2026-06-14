"""
Host risk preflight for Fable-aware orchestration.

Architecture Decision Record (ADR):
- Keep the first Fable safeguard deterministic so routing is cheap, auditable,
  and cache-stable before any host model receives the task.
- Treat normal software engineering and code review as an explicit benign path.
- Preserve reason codes and confirmation requirements instead of hiding low
  confidence behind a generic host escalation.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

REQUESTED_FABLE_MODEL = "claude-fable-5"
FALLBACK_HOST_MODEL = "claude-opus-4-8"
DEFAULT_EXECUTOR_MODEL = "minimax-m3"


class HostRiskReasonCode(str, Enum):
    """Deterministic reason codes for Fable safeguard/fallback risk."""

    CYBER_DUAL_USE = "cyber_dual_use"
    BIO_CHEM = "bio_chem"
    DISTILLATION = "distillation"
    FRONTIER_LLM_DEVELOPMENT = "frontier_llm_development"
    BINARY_RECONSTRUCTION_OR_EXPLOIT_LIKE = "binary_reconstruction_or_exploit_like"
    BENIGN_SOFTWARE_ENGINEERING = "benign_software_engineering"


@dataclass(frozen=True)
class HostRiskPreflightInput:
    """Inputs used by the deterministic host-risk preflight."""

    task_text: str
    target_paths: list[str] = field(default_factory=list)
    workflow_mode: str | None = None
    static_issue_categories: list[str] = field(default_factory=list)
    requested_tools: list[str] = field(default_factory=list)
    user_declared_domain: str | None = None


@dataclass(frozen=True)
class HostRiskPreflightDecision:
    """Decision produced before spending expensive host tokens."""

    safe_for_fable: bool
    likely_fallback: bool
    reason_codes: list[HostRiskReasonCode]
    recommended_host: str
    recommended_executor: str
    needs_user_confirmation: bool
    rationale: str

    def to_dict(self) -> dict[str, object]:
        """Serialize the decision for route JSON, artifacts, and metadata."""
        return {
            "safe_for_fable": self.safe_for_fable,
            "likely_fallback": self.likely_fallback,
            "reason_codes": [code.value for code in self.reason_codes],
            "recommended_host": self.recommended_host,
            "recommended_executor": self.recommended_executor,
            "needs_user_confirmation": self.needs_user_confirmation,
            "rationale": self.rationale,
            "requested_host_model": REQUESTED_FABLE_MODEL,
            "fallback_policy": fallback_policy_for(self),
        }


_TOKEN_RE = re.compile(r"[a-z0-9_.+-]+")

_BENIGN_SOFTWARE_TERMS = frozenset(
    {
        "api",
        "bug",
        "build",
        "ci",
        "cli",
        "code",
        "coverage",
        "debug",
        "docs",
        "format",
        "lint",
        "mypy",
        "parser",
        "pytest",
        "refactor",
        "review",
        "ruff",
        "test",
        "typecheck",
        "unit",
        "validation",
        "verify",
    }
)

_CYBER_TERMS = frozenset(
    {
        "botnet",
        "credential",
        "credentials",
        "exfiltrate",
        "exfiltration",
        "keylogger",
        "malware",
        "payload",
        "phishing",
        "privilege",
        "ransomware",
        "reverse-shell",
        "shell",
        "shellcode",
        "steal",
        "token",
        "tokens",
    }
)

_CYBER_PHRASES = (
    "bypass authentication",
    "credential theft",
    "exploit chain",
    "privilege escalation",
    "reverse shell",
    "steal cookies",
    "steal credentials",
)

_DUAL_USE_SECURITY_TERMS = frozenset(
    {
        "attack",
        "exploit",
        "intrusion",
        "metasploit",
        "offensive",
        "pentest",
        "poc",
        "redteam",
        "vulnerability",
    }
)

_BINARY_TERMS = frozenset(
    {
        "binary",
        "decompile",
        "decompiler",
        "disassemble",
        "disassembler",
        "firmware",
        "ghidra",
        "ida",
        "rop",
        "shellcode",
    }
)

_BIO_CHEM_TERMS = frozenset(
    {
        "anthrax",
        "biohazard",
        "chemical",
        "chemistry",
        "crispr",
        "explosive",
        "gene",
        "genetic",
        "pathogen",
        "synthesis",
        "toxin",
        "venom",
        "virus",
        "wetlab",
        "wet-lab",
    }
)

_BIO_CHEM_PHRASES = (
    "chemical synthesis",
    "gene editing",
    "pathogen protocol",
    "wet lab",
)

_DISTILLATION_TERMS = frozenset(
    {
        "clone",
        "distill",
        "distillation",
        "imitate",
        "student",
        "teacher",
    }
)

_DISTILLATION_PHRASES = (
    "copy proprietary model",
    "distill claude",
    "distill gpt",
    "extract model",
    "teacher model",
    "train a student",
)

_FRONTIER_LLM_TERMS = frozenset(
    {
        "agi",
        "frontier",
        "llm",
        "pretrain",
        "pretraining",
        "rlhf",
        "scaling",
        "transformer",
        "weights",
    }
)

_FRONTIER_LLM_PHRASES = (
    "frontier model",
    "large language model",
    "model weights",
    "pretrain an llm",
    "train a foundation model",
)

_AMBIGUITY_TERMS = frozenset(
    {
        "authorized",
        "ctf",
        "defensive",
        "internal",
        "lab",
        "sandbox",
        "training",
    }
)


def preflight_host_risk(inputs: HostRiskPreflightInput) -> HostRiskPreflightDecision:
    """Classify whether a task is likely to degrade or fall back on Fable."""
    text = _join_inputs(inputs)
    tokens = set(_TOKEN_RE.findall(text))
    reason_codes: list[HostRiskReasonCode] = []

    if _contains_any(tokens, _BIO_CHEM_TERMS) or _contains_phrase(text, _BIO_CHEM_PHRASES):
        reason_codes.append(HostRiskReasonCode.BIO_CHEM)

    if _contains_any(tokens, _DISTILLATION_TERMS) or _contains_phrase(text, _DISTILLATION_PHRASES):
        reason_codes.append(HostRiskReasonCode.DISTILLATION)

    if _frontier_llm_risk(text, tokens):
        reason_codes.append(HostRiskReasonCode.FRONTIER_LLM_DEVELOPMENT)

    if _binary_or_exploit_risk(text, tokens):
        reason_codes.append(HostRiskReasonCode.BINARY_RECONSTRUCTION_OR_EXPLOIT_LIKE)

    if _cyber_dual_use_risk(text, tokens):
        reason_codes.append(HostRiskReasonCode.CYBER_DUAL_USE)

    has_risk = bool(reason_codes)
    benign_software = _benign_software_engineering(inputs, tokens)
    if benign_software and not has_risk:
        reason_codes.append(HostRiskReasonCode.BENIGN_SOFTWARE_ENGINEERING)

    ambiguous_dual_use = _ambiguous_dual_use(tokens, reason_codes)
    likely_fallback = any(
        code != HostRiskReasonCode.BENIGN_SOFTWARE_ENGINEERING for code in reason_codes
    )
    safe_for_fable = not likely_fallback
    needs_user_confirmation = ambiguous_dual_use or (
        likely_fallback and not _clearly_disallowed(tokens)
    )
    recommended_host = FALLBACK_HOST_MODEL if likely_fallback else REQUESTED_FABLE_MODEL
    recommended_executor = DEFAULT_EXECUTOR_MODEL

    if likely_fallback:
        rationale = _risk_rationale(reason_codes, ambiguous_dual_use)
    elif benign_software:
        rationale = (
            "Normal software-engineering work is safe for Fable when host synthesis is needed."
        )
    else:
        needs_user_confirmation = True
        rationale = "Task domain is unclear; confirm before spending Fable host tokens."

    return HostRiskPreflightDecision(
        safe_for_fable=safe_for_fable,
        likely_fallback=likely_fallback,
        reason_codes=reason_codes,
        recommended_host=recommended_host,
        recommended_executor=recommended_executor,
        needs_user_confirmation=needs_user_confirmation,
        rationale=rationale,
    )


def host_risk_metadata(decision: HostRiskPreflightDecision) -> dict[str, object]:
    """Return the standardized delegation metadata keys for a preflight decision."""
    return {
        "requested_host_model": REQUESTED_FABLE_MODEL,
        "recommended_host_model": decision.recommended_host,
        "host_risk_safe_for_fable": decision.safe_for_fable,
        "host_risk_likely_fallback": decision.likely_fallback,
        "host_risk_reason_codes": [code.value for code in decision.reason_codes],
        "host_risk_needs_user_confirmation": decision.needs_user_confirmation,
        "fallback_policy": fallback_policy_for(decision),
    }


def fallback_policy_for(decision: HostRiskPreflightDecision) -> str:
    """Return a stable fallback-policy label for reports and artifacts."""
    if decision.likely_fallback and decision.needs_user_confirmation:
        return "confirm_before_fable_or_use_executor"
    if decision.likely_fallback:
        return "avoid_fable_prefer_executor_or_opus"
    if decision.needs_user_confirmation:
        return "confirm_domain_before_fable"
    return "fable_ok_when_host_needed"


def build_host_risk_input(
    task_text: str,
    *,
    target_paths: list[str] | None = None,
    workflow_mode: str | None = None,
    static_issue_categories: list[str] | None = None,
    requested_tools: list[str] | None = None,
    user_declared_domain: str | None = None,
) -> HostRiskPreflightInput:
    """Construct a normalized preflight input from route/review call sites."""
    return HostRiskPreflightInput(
        task_text=task_text,
        target_paths=[str(Path(path)) for path in target_paths or [] if path],
        workflow_mode=workflow_mode,
        static_issue_categories=list(static_issue_categories or []),
        requested_tools=list(requested_tools or []),
        user_declared_domain=user_declared_domain,
    )


def stable_preflight_digest(inputs: HostRiskPreflightInput) -> str:
    """Return a stable short digest for traceability without storing raw content."""
    payload = "\n".join(
        [
            inputs.task_text,
            "|".join(inputs.target_paths),
            inputs.workflow_mode or "",
            "|".join(sorted(inputs.static_issue_categories)),
            "|".join(sorted(inputs.requested_tools)),
            inputs.user_declared_domain or "",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _join_inputs(inputs: HostRiskPreflightInput) -> str:
    parts = [
        inputs.task_text,
        " ".join(inputs.target_paths),
        inputs.workflow_mode or "",
        " ".join(inputs.static_issue_categories),
        " ".join(inputs.requested_tools),
        inputs.user_declared_domain or "",
    ]
    return " ".join(part.lower() for part in parts if part)


def _contains_any(tokens: set[str], needles: frozenset[str]) -> bool:
    return bool(tokens & needles)


def _contains_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _benign_software_engineering(inputs: HostRiskPreflightInput, tokens: set[str]) -> bool:
    if inputs.workflow_mode and inputs.workflow_mode.lower() in {
        "auto-fix",
        "hybrid",
        "plan",
        "pressure",
        "review",
    }:
        return True
    if tokens & _BENIGN_SOFTWARE_TERMS:
        return True
    return any(
        Path(path).suffix.lower() in {".go", ".js", ".jsx", ".md", ".py", ".rs", ".ts", ".tsx"}
        for path in inputs.target_paths
    )


def _cyber_dual_use_risk(text: str, tokens: set[str]) -> bool:
    if _contains_phrase(text, _CYBER_PHRASES):
        return True
    if "proof of concept" in text and tokens & {"exploit", "pentest", "vulnerability"}:
        return True
    if "exploit" in tokens and tokens & {"attack", "offensive", "pentest", "poc"}:
        return True
    return bool(tokens & _CYBER_TERMS and tokens & _DUAL_USE_SECURITY_TERMS)


def _binary_or_exploit_risk(text: str, tokens: set[str]) -> bool:
    if "reconstruct exploit" in text or "weaponize exploit" in text:
        return True
    return bool(tokens & _BINARY_TERMS and tokens & _DUAL_USE_SECURITY_TERMS)


def _frontier_llm_risk(text: str, tokens: set[str]) -> bool:
    if _contains_phrase(text, _FRONTIER_LLM_PHRASES):
        return True
    return bool("frontier" in tokens and tokens & _FRONTIER_LLM_TERMS)


def _ambiguous_dual_use(
    tokens: set[str],
    reason_codes: list[HostRiskReasonCode],
) -> bool:
    dual_use_codes = {
        HostRiskReasonCode.CYBER_DUAL_USE,
        HostRiskReasonCode.BINARY_RECONSTRUCTION_OR_EXPLOIT_LIKE,
    }
    return bool(tokens & _AMBIGUITY_TERMS and any(code in dual_use_codes for code in reason_codes))


def _clearly_disallowed(tokens: set[str]) -> bool:
    return bool(tokens & {"malware", "ransomware", "phishing", "keylogger", "exfiltrate"})


def _risk_rationale(
    reason_codes: list[HostRiskReasonCode],
    ambiguous_dual_use: bool,
) -> str:
    labels = ", ".join(code.value for code in reason_codes)
    if ambiguous_dual_use:
        return f"Task has ambiguous dual-use host-risk signals: {labels}."
    return f"Task has Fable fallback-risk signals: {labels}."
