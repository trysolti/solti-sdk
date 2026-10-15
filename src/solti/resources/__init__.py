"""Resource namespaces on `SoltiClient` (jobs, connections, cronjobs, keys)."""

from __future__ import annotations

from typing import Any


class Resource(dict):
    """API response wrapper: a dict with attribute access to response fields.

    API JSON responses use snake_case (`estimated_cost`, `vm_status`), so
    attribute access follows the response shape exactly.
    """

    def __init__(self, client: Any, data: dict[str, Any]) -> None:
        super().__init__(data)
        self.client = client

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(
                f"{type(self).__name__!r} object has no attribute {name!r}"
            ) from None


def _wrap_list(client: Any, payload: Any, envelope_key: str, wrapper: type[Resource]) -> list:
    """Unwraps a list endpoint response — either `{envelope_key: [...]}` or a bare array."""
    items = payload.get(envelope_key) if isinstance(payload, dict) else payload
    items = items or []
    return [wrapper(client, item) for item in items]
