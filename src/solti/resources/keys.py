"""Keys namespace: API key management (admin only, api spec §3.4)."""

from __future__ import annotations

from .._client import SoltiClient
from . import Resource, _wrap_list


class Key(Resource):
    """An API key response. The create response's clear-text PAT is exposed
    as `api_key` (or `token`) and is shown only once."""


class KeysResource:
    """`/1/keys` — proxy wrapper around Zitadel machine users and PATs."""

    def __init__(self, client: SoltiClient) -> None:
        self._client = client

    def create(self, *, name: str, role: str, expires_at: str | None = None) -> Key:
        body: dict[str, str] = {"name": name, "role": role}
        if expires_at is not None:
            body["expires_at"] = expires_at
        return Key(self._client, self._client.request("keys", "POST", json_body=body))

    def list(self) -> list[Key]:
        payload = self._client.request("keys", "GET")
        return _wrap_list(self._client, payload, "keys", Key)

    def delete(self, key_id_or_name: str) -> None:
        """Deletes the machine user in Zitadel, revoking access. Accepts the
        key UUID or key name."""
        self._client.request(f"keys/{key_id_or_name}", "DELETE")
