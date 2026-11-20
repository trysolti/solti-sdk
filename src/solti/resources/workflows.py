"""Workflows namespace: DAG submission, node inspection and cancellation
(workflows API, api OpenAPI 0.3.0 — change 086; SDK surface per change 091 WS1)."""

from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from .._client import SoltiClient
from ..types import (
    CreateWorkflowRequest,
    VmStatus,
    WorkflowStatus,
    WorkloadStatus,
)


class WorkflowNode(BaseModel):
    """One workflow node job — a live projection of the jobs row (`GET
    /1/workflows/{id_or_name}`)."""

    model_config = ConfigDict(extra="allow")

    job_id: str | None = None
    #: Node job name (`<workflow-name>--<node-name>`, suffixed with the
    #: sanitized item on fan-out).
    name: str | None = None
    status: WorkloadStatus | None = None
    vm_status: VmStatus | None = None
    #: Node error summary (dependency failures surface here).
    error_message: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    estimated_cost: float | None = None
    actual_cost: float | None = None
    ondemand_cost: float | None = None


class Workflow(BaseModel):
    """A workflow API response (snake_case fields). The create/cancel
    response's `workflow_id` is normalized to `.id`.

    `nodes` carries both wire shapes of the same key: the detail endpoint's
    live node list (`list[WorkflowNode]`) and, on the create response, the
    materialized node map (node job name → `{job_id, name}`), kept verbatim
    so neither variant is dropped.
    """

    model_config = ConfigDict(extra="allow")

    id: str | None = Field(None, validation_alias=AliasChoices("id", "workflow_id"))
    organization_id: str | None = None
    project_id: str | None = None
    name: str | None = None
    status: WorkflowStatus | None = None
    #: Workflow-level error summary (`None` while running).
    error_message: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    #: Terminal timestamp (`None` while running).
    ended_at: str | None = None
    #: Number of materialized node jobs.
    node_count: int | None = None
    nodes: list[WorkflowNode] | dict[str, Any] | None = None
    #: Aggregate cost sums over the nodes (detail endpoint; `None` when no
    #: node reports one).
    estimated_cost: float | None = None
    actual_cost: float | None = None
    ondemand_cost: float | None = None


class WorkflowsResource:
    """`/1/workflows` — submit DAG workflows and manage their node jobs.

    All methods addressing an existing workflow accept either its unique
    UUID (`id`) or its unique `name`.
    """

    def __init__(self, client: SoltiClient) -> None:
        self._client = client

    def create(
        self,
        templates: list[dict[str, Any]],
        *,
        name: str | None = None,
        name_prefix: str | None = None,
    ) -> Workflow:
        """Submits a DAG workflow. Each `templates` entry is a standard job
        definition (`job`) plus its node `name`, optional `dependencies` edges
        referencing other template names, and optional static fan-out
        (`withItems` / `withSequence`); root nodes provision immediately,
        dependents wait for ALL upstream nodes to succeed. Templates dicts
        pass through to the API verbatim (it validates slug names, fan-out
        forms and the ≤ 50 node-job budget). Request payloads use camelCase
        wire keys (`namePrefix`).

        Args:
            templates: Non-empty list of template dicts (client-side shape
                check only).
            name: Unique workflow name (slug format); `409` on duplicate.
            name_prefix: Generate `<prefix>-<random suffix>` instead (ignored
                when `name` is set).
        """
        if not isinstance(templates, list) or not templates:
            raise ValueError("templates must be a non-empty list of template dicts.")
        if not all(isinstance(entry, dict) for entry in templates):
            raise ValueError(
                "Every templates entry must be a dict "
                "(template `name` + `job` definition, optional `dependencies`)."
            )
        request = CreateWorkflowRequest(
            templates=templates,
            name=name,
            name_prefix=name_prefix,
        )
        payload = request.model_dump(by_alias=True, exclude_none=True)
        return Workflow.model_validate(self._client.request("workflows", "POST", json_body=payload))

    def get(self, workflow_id_or_name: str) -> Workflow:
        """Fetches workflow state — status, live node jobs and aggregate
        costs — by UUID or unique name (UUID takes precedence)."""
        return Workflow.model_validate(
            self._client.request(f"workflows/{workflow_id_or_name}", "GET")
        )

    def list(
        self,
        *,
        limit: int | None = None,
        offset: int | None = None,
        status: WorkflowStatus | None = None,
    ) -> list[Workflow]:
        """Lists workflows, newest first. Pagination uses `limit`/`offset`
        (api defaults: limit 50); `status` filters by workflow status
        (`running`/`succeeded`/`failed`/`cancelled`).
        """
        payload = self._client.request(
            "workflows",
            "GET",
            params={"limit": limit, "offset": offset, "status": status},
        )
        items = payload.get("workflows") if isinstance(payload, dict) else payload
        return [Workflow.model_validate(item) for item in (items or [])]

    def cancel(self, workflow_id_or_name: str) -> Workflow | None:
        """Cancels a workflow: every non-terminal node job (queued, booting,
        running) is cancelled, succeeded nodes are untouched. Raises
        `ConflictError` (409) when the workflow is already terminal."""
        response = self._client.request(f"workflows/{workflow_id_or_name}/cancel", "POST")
        return Workflow.model_validate(response) if isinstance(response, dict) else None
