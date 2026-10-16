"""Cronjobs namespace: periodic task definitions with UTC schedules (api spec §3.3)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .._client import SoltiClient
from ..types import (
    CreateCronjobRequest,
    JobDefinition,
    PatchCronjobRequest,
)


class Cronjob(BaseModel):
    """A cronjob API response (snake_case fields)."""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    name: str | None = None
    #: UTC crontab expression.
    cron_spec: str | None = None
    is_active: bool | None = None
    last_triggered_at: str | None = None
    job_definition: JobDefinition | None = None
    created_at: str | None = None


class CronjobsResource:
    """`/1/cronjobs` — manage periodic workloads.

    All methods addressing an existing cronjob accept either its unique UUID
    (`id`) or its unique `name`.
    """

    def __init__(self, client: SoltiClient) -> None:
        self._client = client

    def create(
        self,
        *,
        name: str,
        cron_spec: str,
        job_definition: dict | JobDefinition,
        is_active: bool | None = None,
    ) -> Cronjob:
        """Creates a cronjob. `cron_spec` is evaluated strictly in UTC; the
        `job_definition` template must not contain a fixed `name` field."""
        request = CreateCronjobRequest(
            name=name,
            cron_spec=cron_spec,
            job_definition=job_definition,
            is_active=is_active,
        )
        return Cronjob.model_validate(
            self._client.request(
                "cronjobs", "POST", json_body=request.model_dump(exclude_none=True)
            )
        )

    def get(self, cronjob_id_or_name: str) -> Cronjob:
        return Cronjob.model_validate(
            self._client.request(f"cronjobs/{cronjob_id_or_name}", "GET")
        )

    def list(self) -> list[Cronjob]:
        payload = self._client.request("cronjobs", "GET")
        items = payload.get("cronjobs") if isinstance(payload, dict) else payload
        return [Cronjob.model_validate(item) for item in (items or [])]

    def patch(
        self,
        cronjob_id_or_name: str,
        **payload: object,
    ) -> Cronjob:
        """Updates cronjob parameters (`cron_spec`, `is_active`, `job_definition`)."""
        request = PatchCronjobRequest(**payload)
        response = self._client.request(
            f"cronjobs/{cronjob_id_or_name}",
            "PATCH",
            json_body=request.model_dump(exclude_none=True),
        )
        return Cronjob.model_validate(response)

    update = patch

    def delete(self, cronjob_id_or_name: str) -> None:
        self._client.request(f"cronjobs/{cronjob_id_or_name}", "DELETE")
