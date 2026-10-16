"""Keys namespace: API key management (admin only, api spec §3.4)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .._client import SoltiClient
from ..types import CreateKeyRequest, KeyRole


class Key(BaseModel):
    """An API key response. The create response's clear-text PAT is exposed
    as `api_key` (or `token`) and is shown only once."""

    model_config = ConfigDict(extra="allow")

    name: str
    role: KeyRole | None = None
    created_at: str | None = None


class CreateKeyResponse(BaseModel):
    """`POST /1/keys` response — the clear-text PAT is shown only once."""

    model_config = ConfigDict(extra="allow")

    name: str
    api_key: str | None = None
    #: Alternate wire key for the same token.
    token: str | None = None


class KeysResource:
    """`/1/keys` — proxy wrapper around Zitadel machine users and PATs."""

    def __init__(self, client: SoltiClient) -> None:
        self._client = client

    def create(
        self, *, name: str, role: KeyRole, expires_at: str | None = None
    ) -> CreateKeyResponse:
        request = CreateKeyRequest(name=name, role=role, expires_at=expires_at)
        return CreateKeyResponse.model_validate(
            self._client.request("keys", "POST", json_body=request.model_dump(exclude_none=True))
        )

    def list(self) -> list[Key]:
        payload = self._client.request("keys", "GET")
        items = payload.get("keys") if isinstance(payload, dict) else payload
        return [Key.model_validate(item) for item in (items or [])]

    def delete(self, key_id_or_name: str) -> None:
        """Deletes the machine user in Zitadel, revoking access. Accepts the
        key UUID or key name."""
        self._client.request(f"keys/{key_id_or_name}", "DELETE")
