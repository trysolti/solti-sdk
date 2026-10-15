"""Cronjobs namespace: periodic task definitions with UTC schedules (api spec §3.3)."""

from __future__ import annotations

from typing import Any

from .._client import SoltiClient
from . import Resource, _wrap_list


class Cronjob(Resource):
    """A cronjob API response."""


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
        job_definition: dict[str, Any],
        is_active: bool | None = None,
    ) -> Cronjob:
        """Creates a cronjob. `cron_spec` is evaluated strictly in UTC; the
        `job_definition` template must not contain a fixed `name` field.
        """
        body: dict[str, Any] = {
            "name": name,
            "cron_spec": cron_spec,
            "job_definition": job_definition,
        }
        if is_active is not None:
            body["is_active"] = is_active
        return Cronjob(self._client, self._client.request("cronjobs", "POST", json_body=body))

    def get(self, cronjob_id_or_name: str) -> Cronjob:
        return Cronjob(self._client, self._client.request(f"cronjobs/{cronjob_id_or_name}", "GET"))

    def list(self) -> list[Cronjob]:
        payload = self._client.request("cronjobs", "GET")
        return _wrap_list(self._client, payload, "cronjobs", Cronjob)

    def patch(self, cronjob_id_or_name: str, **payload: Any) -> Cronjob:
        """Updates cronjob parameters (`cron_spec`, `is_active`, `job_definition`)."""
        response = self._client.request(
            f"cronjobs/{cronjob_id_or_name}", "PATCH", json_body=payload
        )
        return Cronjob(self._client, response)

    update = patch

    def delete(self, cronjob_id_or_name: str) -> None:
        self._client.request(f"cronjobs/{cronjob_id_or_name}", "DELETE")
