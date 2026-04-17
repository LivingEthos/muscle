"""
Background telemetry recorder for MUSCLE.

Records model-call telemetry without blocking the main execution path. Failures
are logged and intentionally do not interrupt review or generation flows.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from dataclasses import asdict, dataclass
from typing import Any

from ..project_memory import ProjectMemory

logger = logging.getLogger(__name__)


@dataclass
class LLMCallEvent:
    """Serializable telemetry payload for a single LLM call."""

    project_path: str
    call_id: str
    session_id: str
    stage: str
    model: str
    input_tokens: int
    output_tokens: int
    duration_ms: int
    success: bool
    workflow_name: str | None = None
    review_mode: str | None = None
    parse_success: bool | None = None
    validation_success: bool | None = None
    context_chars: int = 0
    context_strategy: str = "default"
    requested_label: str | None = None
    provider_endpoint: str | None = None
    provider_fingerprint: str | None = None
    canonical_model_key: str | None = None
    identity_source: str = "unresolved"
    identity_confidence: float = 0.0
    manual_override: bool = False
    metadata_json: str = "{}"


class TelemetryRecorder:
    """Write optimization telemetry on a background thread."""

    def __init__(self, project_memory: ProjectMemory, max_queue_size: int = 2048):
        self._pm = project_memory
        self._queue: queue.Queue[tuple[str, dict[str, Any] | None]] = queue.Queue(
            maxsize=max_queue_size
        )
        self._stop_event = threading.Event()
        self._worker = threading.Thread(
            target=self._run,
            name="muscle-telemetry-recorder",
            daemon=True,
        )
        self._worker.start()

    def record_llm_call(self, event: LLMCallEvent) -> None:
        """Queue an LLM call insert."""
        self._enqueue("insert_llm_call", asdict(event))

    def update_llm_call(
        self,
        call_id: str,
        parse_success: bool | None = None,
        validation_success: bool | None = None,
        metadata_updates: dict[str, Any] | None = None,
    ) -> None:
        """Queue an LLM call update."""
        self._enqueue(
            "update_llm_call",
            {
                "call_id": call_id,
                "parse_success": parse_success,
                "validation_success": validation_success,
                "metadata_updates": metadata_updates or {},
            },
        )

    def insert_token_savings(self, payload: dict[str, Any]) -> None:
        """Queue a token-savings ledger write."""
        self._enqueue("insert_token_savings", payload)

    def insert_optimization_decision(self, payload: dict[str, Any]) -> None:
        """Queue an optimization decision write."""
        self._enqueue("insert_optimization_decision", payload)

    def record_model_identity_history(self, project_path: str, identity: dict[str, Any]) -> None:
        """Queue a model-identity history insert."""
        self._enqueue(
            "insert_model_identity_history",
            {
                "project_path": project_path,
                "identity": identity,
            },
        )

    def close(self, timeout: float = 2.0) -> None:
        """Stop the background recorder."""
        self._stop_event.set()
        self._enqueue("stop", None)
        self._worker.join(timeout=timeout)

    def _enqueue(self, op_name: str, payload: dict[str, Any] | None) -> None:
        try:
            self._queue.put_nowait((op_name, payload))
        except queue.Full:
            logger.warning("Telemetry queue full; dropping %s event", op_name)

    def _run(self) -> None:
        while True:
            try:
                op_name, payload = self._queue.get(timeout=0.2)
            except queue.Empty:
                if self._stop_event.is_set():
                    return
                continue

            if op_name == "stop":
                self._queue.task_done()
                return

            try:
                if op_name == "insert_llm_call" and payload is not None:
                    self._pm.insert_llm_call(**payload)
                elif op_name == "update_llm_call" and payload is not None:
                    self._pm.update_llm_call(**payload)
                elif op_name == "insert_token_savings" and payload is not None:
                    self._pm.insert_token_savings_entry(**payload)
                elif op_name == "insert_optimization_decision" and payload is not None:
                    recommendation_json = payload.get("recommendation_json")
                    if isinstance(recommendation_json, dict):
                        payload["recommendation_json"] = json.dumps(recommendation_json)
                    outcome_json = payload.get("outcome_json")
                    if isinstance(outcome_json, dict):
                        payload["outcome_json"] = json.dumps(outcome_json)
                    self._pm.insert_optimization_decision(**payload)
                elif op_name == "insert_model_identity_history" and payload is not None:
                    self._pm.insert_model_identity_history(**payload)
            except Exception:
                logger.warning("Telemetry recorder failed for %s", op_name, exc_info=True)
            finally:
                self._queue.task_done()
