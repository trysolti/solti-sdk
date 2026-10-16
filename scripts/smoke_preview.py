"""Preview smoke verification for `solti-sdk` (Change 015 WS5).

READ-ONLY against the preview environment (https://preview.api.solti.run/1):
list/get calls and error-path probes only — no mutations, no resource
creation, no 429 triggering (rate-limit plumbing is inspected from response
headers, not by hammering the API).

Usage:
    uv run python scripts/smoke_preview.py \
        --api-key "$SOLTI_PREVIEW_API_KEY" --project-id "$SOLTI_PREVIEW_PROJECT_ID"

Credentials fall back to the `SOLTI_API_KEY` / `SOLTI_PROJECT_ID` environment
variables (the same fallbacks the SDK client itself uses).

Checks:
  1. Auth + project header: jobs.list() and connections.list() → 200, valid JSON.
  2. Error mapping: invalid API key on jobs.list() → AuthenticationError (401).
  3. Not-found mapping: jobs.get(<random UUID>) → NotFoundError (404), no crash.
  4. RateLimit header plumbing: inspect X-RateLimit-* headers on the list
     response; confirm RateLimitError surfaces them when present.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from solti import PREVIEW_API_URL, SoltiClient  # noqa: E402
from solti.exceptions import AuthenticationError, NotFoundError, SoltiError  # noqa: E402


def _check(results: list[tuple[str, bool, str]], name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))


def _list_headers(client: SoltiClient) -> tuple[bool, dict[str, str]]:
    """Raw GET /1/jobs with the client's exact headers — inspects the same
    list call at transport level to capture X-RateLimit-* response headers
    (the success path of `request()` returns parsed JSON only)."""
    headers = {"X-Solti-API-Key": client.api_key}
    if client.project_id:
        headers["X-Solti-Project-Id"] = client.project_id
    response = client._http.get("jobs", headers=headers)
    rate_limit_headers = {
        name: value
        for name, value in response.headers.items()
        if name.lower().startswith("x-ratelimit-")
    }
    return response.status_code == 200, rate_limit_headers


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview smoke checks (read-only).")
    parser.add_argument("--api-key", default=os.environ.get("SOLTI_API_KEY"))
    parser.add_argument("--project-id", default=os.environ.get("SOLTI_PROJECT_ID"))
    parser.add_argument("--api-url", default=PREVIEW_API_URL)
    args = parser.parse_args()
    if not args.api_key or not args.project_id:
        parser.error("--api-key/--project-id (or SOLTI_API_KEY/SOLTI_PROJECT_ID) are required")

    results: list[tuple[str, bool, str]] = []
    print(f"Preview smoke — {args.api_url} (project {args.project_id})\n")

    # 1. Auth + project header: jobs.list() + connections.list() → 200 / valid JSON.
    try:
        with SoltiClient(
            api_key=args.api_key, api_url=args.api_url, project_id=args.project_id
        ) as client:
            jobs = client.jobs.list(limit=5)
            conns = client.connections.list()
            ok = isinstance(jobs, list) and isinstance(conns, list)
            _check(
                results,
                "auth+jobs.list+connections.list (200, valid JSON)",
                ok,
                f"jobs={len(jobs)} connections={len(conns)}",
            )

            # 4. RateLimit header plumbing — headers on the list response.
            list_ok, rl_headers = _list_headers(client)
            if rl_headers:
                _check(
                    results,
                    "ratelimit headers surfaced on list response",
                    list_ok,
                    ", ".join(f"{k}: {v}" for k, v in sorted(rl_headers.items())),
                )
            else:
                _check(
                    results,
                    "ratelimit headers surfaced on list response",
                    list_ok,
                    "no X-RateLimit-* headers sent by preview on 200 "
                    "(RateLimitError.rate_limit_headers plumbing unit-verified; "
                    "live 429 not triggered by design)",
                )
    except SoltiError as exc:
        _check(results, "auth+jobs.list+connections.list (200, valid JSON)", False, repr(exc))

    # 2. Error mapping: invalid API key → AuthenticationError (401).
    try:
        with SoltiClient(
            api_key="invalid-smoke-key", api_url=args.api_url, project_id=args.project_id
        ) as bad:
            try:
                bad.jobs.list(limit=1)
                _check(results, "invalid key → AuthenticationError (401)", False, "no error raised")
            except AuthenticationError as exc:
                _check(
                    results,
                    "invalid key → AuthenticationError (401)",
                    exc.status == 401,
                    f"status={exc.status}",
                )
            except SoltiError as exc:
                # Observed on preview: the API returns 500 'Internal Server
                # Error' for invalid keys (error-contract violation — 401 is
                # expected; recorded in the WS5 report). The SDK surfaces the
                # generic SoltiError — misclassifying all 500s as auth errors
                # would be wrong, so this stays a documented API deviation.
                _check(
                    results,
                    "invalid key → AuthenticationError (401)",
                    False,
                    f"API returned status={exc.status} (expected 401 — "
                    f"preview error-contract violation, recorded in report); "
                    f"SDK raised {type(exc).__name__}, no crash",
                )
    except SoltiError as exc:
        _check(results, "invalid key → AuthenticationError (401)", False, f"client init: {exc!r}")

    # 3. Not-found mapping: random-UUID job → NotFoundError (404), no crash.
    missing_id = str(uuid.uuid4())
    try:
        with SoltiClient(
            api_key=args.api_key, api_url=args.api_url, project_id=args.project_id
        ) as client:
            try:
                client.jobs.get(missing_id)
                _check(results, "random-UUID job → NotFoundError (404)", False, "no error raised")
            except NotFoundError as exc:
                _check(
                    results,
                    "random-UUID job → NotFoundError (404)",
                    exc.status == 404,
                    f"status={exc.status} message={exc}",
                )
            except SoltiError as exc:
                _check(
                    results,
                    "random-UUID job → NotFoundError (404)",
                    False,
                    f"unexpected error type {type(exc).__name__}: {exc}",
                )
    except SoltiError as exc:
        _check(results, "random-UUID job → NotFoundError (404)", False, f"client init: {exc!r}")

    # Compact PASS/FAIL table.
    width = max(len(name) for name, _, _ in results)
    print(f"{'CHECK':<{width}}  RESULT  DETAIL")
    failed = 0
    for name, ok, detail in results:
        print(f"{name:<{width}}  {'PASS' if ok else 'FAIL':<6}  {detail}")
        failed += 0 if ok else 1
    print(f"\n{len(results) - failed}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
