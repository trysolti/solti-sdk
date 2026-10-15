"""Connections namespace: CRUD for cloud credential integrations (api spec §3.1)."""

from __future__ import annotations

from typing import Any

from .._client import SoltiClient
from . import Resource, _wrap_list


class Connection(Resource):
    """A connection API response (credentials are redacted by the API)."""


class ConnectionsResource:
    """`/1/connections` — manage stored cloud credentials."""

    def __init__(self, client: SoltiClient) -> None:
        self._client = client

    def create(
        self,
        *,
        name: str,
        type: str,
        credentials: dict[str, Any] | None = None,
        **fields: Any,
    ) -> Connection:
        """Creates a connection. `credentials` entries are merged into the
        request body as top-level fields, matching the CLI's flat wire format
        (e.g. `access_key_id`, `secret_access_key`, `access_token`).
        """
        body: dict[str, Any] = {"name": name, "type": type}
        if credentials is not None:
            body.update(credentials)
        body.update(fields)
        return Connection(self._client, self._client.request("connections", "POST", json_body=body))

    def get(self, name: str) -> Connection:
        return Connection(self._client, self._client.request(f"connections/{name}", "GET"))

    def list(self) -> list[Connection]:
        payload = self._client.request("connections", "GET")
        return _wrap_list(self._client, payload, "connections", Connection)

    def delete(self, name: str) -> None:
        self._client.request(f"connections/{name}", "DELETE")
