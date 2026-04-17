"""
Review Workflows - Lightweight YAML DAG loader for MUSCLE review orchestration.

Architecture Decision Record (ADR):
- Use a constrained internal YAML schema instead of a general-purpose workflow engine
- Keep node types limited to review operations MUSCLE actually supports
- Validate dependencies eagerly so workflows fail fast in tests and CI
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

ALLOWED_NODE_TYPES = {"classify", "review_agent", "synthesize", "fix", "validate", "gate"}


@dataclass(frozen=True)
class ReviewWorkflowNode:
    id: str
    node_type: str
    depends_on: list[str] = field(default_factory=list)
    agent: str | None = None
    when: str | None = None


@dataclass(frozen=True)
class ReviewWorkflow:
    name: str
    description: str
    nodes: list[ReviewWorkflowNode]

    def ordered_nodes(self) -> list[ReviewWorkflowNode]:
        """Return nodes in dependency order using a topological sort."""
        id_to_node = {node.id: node for node in self.nodes}
        indegree = {node.id: 0 for node in self.nodes}
        children: dict[str, list[str]] = {node.id: [] for node in self.nodes}
        for node in self.nodes:
            for dep in node.depends_on:
                children.setdefault(dep, []).append(node.id)
                indegree[node.id] += 1

        ready = deque(sorted(node_id for node_id, count in indegree.items() if count == 0))
        ordered: list[ReviewWorkflowNode] = []
        while ready:
            node_id = ready.popleft()
            ordered.append(id_to_node[node_id])
            for child_id in children.get(node_id, []):
                indegree[child_id] -= 1
                if indegree[child_id] == 0:
                    ready.append(child_id)

        if len(ordered) != len(self.nodes):
            msg = f"Workflow '{self.name}' contains a dependency cycle"
            raise ValueError(msg)
        return ordered


@dataclass
class WorkflowExecutionResult:
    executed_nodes: list[str] = field(default_factory=list)
    skipped_nodes: list[str] = field(default_factory=list)
    outputs: dict[str, Any] = field(default_factory=dict)


class ReviewWorkflowLoader:
    """Load built-in review workflows from YAML."""

    def __init__(self, workflows_dir: str | None = None):
        base_dir = (
            Path(workflows_dir)
            if workflows_dir
            else Path(__file__).resolve().parent.parent / "workflows"
        )
        self.workflows_dir = base_dir

    def load(self, workflow_name: str) -> ReviewWorkflow:
        path = self.workflows_dir / f"{workflow_name}.yaml"
        if not path.exists():
            msg = f"Review workflow '{workflow_name}' not found at {path}"
            raise FileNotFoundError(msg)

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        nodes = [
            ReviewWorkflowNode(
                id=node["id"],
                node_type=node["type"],
                depends_on=list(node.get("depends_on", [])),
                agent=node.get("agent"),
                when=node.get("when"),
            )
            for node in data.get("nodes", [])
        ]
        workflow = ReviewWorkflow(
            name=data.get("name", workflow_name),
            description=data.get("description", ""),
            nodes=nodes,
        )
        self._validate(workflow)
        return workflow

    def _validate(self, workflow: ReviewWorkflow) -> None:
        seen_ids: set[str] = set()
        for node in workflow.nodes:
            if node.id in seen_ids:
                msg = f"Duplicate node id '{node.id}' in workflow '{workflow.name}'"
                raise ValueError(msg)
            seen_ids.add(node.id)
            if node.node_type not in ALLOWED_NODE_TYPES:
                msg = f"Unsupported node type '{node.node_type}' in workflow '{workflow.name}'"
                raise ValueError(msg)
        valid_ids = {node.id for node in workflow.nodes}
        for node in workflow.nodes:
            missing = [dep for dep in node.depends_on if dep not in valid_ids]
            if missing:
                msg = f"Workflow '{workflow.name}' has unknown dependency {missing} for node '{node.id}'"
                raise ValueError(msg)
        workflow.ordered_nodes()


class ReviewWorkflowEngine:
    """Execute a constrained review workflow by calling injected node handlers."""

    def execute(
        self,
        workflow: ReviewWorkflow,
        handlers: dict[str, Any],
        should_run: Any,
    ) -> WorkflowExecutionResult:
        result = WorkflowExecutionResult()
        for node in workflow.ordered_nodes():
            if not should_run(node, result.outputs):
                result.skipped_nodes.append(node.id)
                continue
            handler = handlers[node.node_type]
            result.outputs[node.id] = handler(node, result.outputs)
            result.executed_nodes.append(node.id)
        return result
