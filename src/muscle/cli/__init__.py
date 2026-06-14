"""MUSCLE command-line interface.

Historically this was a single ~6k-line ``muscle/cli.py`` module. It is now a
package split by command group, but the public surface is unchanged:

* ``muscle.cli:main`` remains the console-script entry point.
* ``from muscle.cli import cli`` / ``import muscle.cli`` keep working.
* Command functions, groups, and the helper/constant names that tests and
  callers reference on ``muscle.cli`` are re-exported here.

Command modules register their commands against the shared ``cli`` group at
import time, so importing them here wires up the full CLI.
"""

from __future__ import annotations

# Patchable third-party / domain classes re-exported for ``muscle.cli.<name>``
# backward compatibility. Tests that patch behaviour target the submodule where
# a name is *used* (e.g. ``muscle.cli.loop.LoopController``); these re-exports
# keep plain ``from muscle.cli import <Name>`` working.
from pathlib import Path  # noqa: E402

from rich.live import Live  # noqa: E402
from rich.progress import Progress  # noqa: E402

from ..budget_manager import BudgetManager  # noqa: E402
from ..code_generator import CodeGenerator  # noqa: E402
from ..code_review.learning_pipeline import LearningPipeline  # noqa: E402
from ..evolver import Evolver  # noqa: E402
from ..loop_controller import LoopController  # noqa: E402
from ..m27_client import DEFAULT_MODEL, M27Client  # noqa: E402
from ..model_packs import ModelPackManager  # noqa: E402
from ..project_memory import ProjectMemory  # noqa: E402
from ..session_manager import SessionManager  # noqa: E402
from ..strategy_kb import GlobalKnowledgeBase  # noqa: E402

# Importing each command module registers its commands on ``cli`` and exposes
# the command callables for re-export below.
from . import (  # noqa: E402,F401
    cost,
    lifecycle,
    loop,
    memory,
    model,
    plumbing,
    review,
)
from . import provider as _provider_module  # noqa: E402,F401

# Shared state, the root group, helpers, and constants.
from ._shared import (
    MAX_TASK_LENGTH,
    MAX_TASK_PREVIEW_LENGTH,
    MAX_TIMEOUT_SECONDS,
    RELEASE_GATE_TEST_TARGETS,
    TRANSFER_AUDIT_ACTIONS,
    _attach_optimization_runtime,
    _build_context_budgeter,
    _build_lesson_resolver,
    _create_event_handler,
    _create_m27_client,
    _emit_json,
    _event_handler,
    _format_size,
    _format_snapshot_age,
    _get_status_color,
    _is_process_alive,
    _lesson_usage_source_label,
    _parse_budget,
    _parse_json_dict,
    _parse_since,
    _parse_timeout,
    _print_backup_scope_note,
    _provider_endpoint,
    _read_session_pid,
    _refresh_active_review_safe,
    _refresh_project_state_safe,
    _render_discovery_report,
    _render_doctor_report,
    _render_foresight_report,
    _render_savings_report,
    _requested_model_label,
    _resolve_log_level,
    _resolve_model_identity,
    _resolve_project_context,
    _resolve_review_execution_mode,
    _resolve_stage_totals,
    _run_benchmark_release_invariants,
    _serialize_json,
    _session_report_to_dict,
    _source_project_name,
    _suggest_related_projects,
    _truncate,
    cli,
    console,
    logger,
)

# Command functions / groups referenced by name on ``muscle.cli``.
from .cost import (  # noqa: E402
    cost_delegation_report,
    cost_group,
    diagnosis,
    lifeline,
    long_eval_benchmark,
    long_eval_group,
    optimize_group,
    probe,
)
from .lifecycle import (  # noqa: E402
    completion,
    disable,
    discover,
    doctor,
    enable,
    foresight,
    init,
    optimize_host_docs,
    savings,
    status,
    tui,
    uninstall,
    visualize,
)
from .loop import (  # noqa: E402
    abort,
    check,
    history,
    resume,
    run,
)
from .memory import (  # noqa: E402
    improve_group,
    kb_group,
    memory_group,
    memory_history,
    memory_status,
    notes_group,
)
from .model import (  # noqa: E402
    agents_group,
    agents_list,
    audit_group,
    backups_group,
    model_group,
    settings_group,
    skills_group,
    skills_list,
)
from .plumbing import (  # noqa: E402
    crush,
    expand,
    filters_group,
    route_cmd,
)
from .provider import (  # noqa: E402
    provider,
    provider_list,
    provider_login,
    provider_setup,
    provider_show,
    provider_use,
    setup,
)


def main() -> None:
    cli()


__all__ = [
    "cli",
    "main",
    "console",
    "logger",
    # constants
    "MAX_TASK_LENGTH",
    "MAX_TIMEOUT_SECONDS",
    "MAX_TASK_PREVIEW_LENGTH",
    "TRANSFER_AUDIT_ACTIONS",
    "RELEASE_GATE_TEST_TARGETS",
    "DEFAULT_MODEL",
    # patchable classes
    "BudgetManager",
    "CodeGenerator",
    "Evolver",
    "GlobalKnowledgeBase",
    "LearningPipeline",
    "Live",
    "LoopController",
    "M27Client",
    "ModelPackManager",
    "Path",
    "Progress",
    "ProjectMemory",
    "SessionManager",
    # helpers
    "_attach_optimization_runtime",
    "_build_context_budgeter",
    "_build_lesson_resolver",
    "_create_event_handler",
    "_create_m27_client",
    "_emit_json",
    "_event_handler",
    "_format_size",
    "_format_snapshot_age",
    "_get_status_color",
    "_is_process_alive",
    "_lesson_usage_source_label",
    "_parse_budget",
    "_parse_json_dict",
    "_parse_since",
    "_parse_timeout",
    "_print_backup_scope_note",
    "_provider_endpoint",
    "_read_session_pid",
    "_refresh_active_review_safe",
    "_refresh_project_state_safe",
    "_render_discovery_report",
    "_render_doctor_report",
    "_render_foresight_report",
    "_render_savings_report",
    "_requested_model_label",
    "_resolve_log_level",
    "_resolve_model_identity",
    "_resolve_project_context",
    "_resolve_review_execution_mode",
    "_resolve_stage_totals",
    "_run_benchmark_release_invariants",
    "_serialize_json",
    "_session_report_to_dict",
    "_source_project_name",
    "_suggest_related_projects",
    "_truncate",
    # commands & groups
    "abort",
    "agents_group",
    "agents_list",
    "audit_group",
    "backups_group",
    "check",
    "completion",
    "cost_delegation_report",
    "cost_group",
    "crush",
    "diagnosis",
    "disable",
    "discover",
    "doctor",
    "enable",
    "expand",
    "filters_group",
    "foresight",
    "history",
    "improve_group",
    "init",
    "kb_group",
    "lifeline",
    "long_eval_benchmark",
    "long_eval_group",
    "memory_group",
    "memory_history",
    "memory_status",
    "model_group",
    "notes_group",
    "optimize_group",
    "optimize_host_docs",
    "probe",
    "provider",
    "provider_login",
    "provider_list",
    "provider_show",
    "provider_setup",
    "provider_use",
    "resume",
    "route_cmd",
    "run",
    "savings",
    "setup",
    "settings_group",
    "skills_group",
    "skills_list",
    "status",
    "tui",
    "uninstall",
    "visualize",
]
