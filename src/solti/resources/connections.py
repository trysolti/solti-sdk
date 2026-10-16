"""Connections namespace: CRUD for cloud credential integrations (api spec §3.1)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, TypeAdapter

from .._client import SoltiClient
from ..types import ConnectionCredentials, ConnectionType, CreateConnectionRequest


class Connection(BaseModel):
    """A connection API response (credentials are redacted by the API)."""

    model_config = ConfigDict(extra="allow")

    name: str
    type: ConnectionType
    created_at: str | None = None


class ConnectionsResource:
    """`/1/connections` — manage stored cloud credentials."""

    def __init__(self, client: SoltiClient) -> None:
        self._client = client

    def create(
        self,
        *,
        name: str,
        type: ConnectionType,
        credentials: ConnectionCredentials | dict[str, Any] | None = None,
        **fields: Any,
    ) -> Connection:
        """Creates a connection. `credentials` validate into the provider
        credential models and are merged into the request body as top-level
        fields, matching the CLI's flat wire format (e.g. `access_key_id`,
        `secret_access_key`, `access_token`)."""
        CreateConnectionRequest(name=name, type=type, credentials=credentials)  # validation
        body: dict[str, Any] = {"name": name, "type": type}
        if credentials is not None:
            if isinstance(credentials, BaseModel):
                body.update(credentials.model_dump(exclude_none=True))
            else:
                adapter = TypeAdapter(ConnectionCredentials)
                body.update(adapter.validate_python(credentials).model_dump(exclude_none=True))
        body.update(fields)
        return Connection.model_validate(
            self._client.request("connections", "POST", json_body=body)
        )

    def get(self, name: str) -> Connection:
        return Connection.model_validate(self._client.request(f"connections/{name}", "GET"))

    def list(self) -> list[Connection]:
        payload = self._client.request("connections", "GET")
        items = payload.get("connections") if isinstance(payload, dict) else payload
        return [Connection.model_validate(item) for item in (items or [])]

    def delete(self, name: str) -> None:
        self._client.request(f"connections/{name}", "DELETE")
