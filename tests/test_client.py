"""Client construction, header semantics, and request/response conventions."""

from __future__ import annotations

import pytest

from conftest import json_response
from solti import DEFAULT_API_URL, PREVIEW_API_URL, SoltiClient, exceptions


class TestConstruction:
    def test_api_key_falls_back_to_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SOLTI_API_KEY", "env-key")
        client = SoltiClient(api_url="http://127.0.0.1:1/1")
        assert client.api_key == "env-key"

    def test_missing_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SOLTI_API_KEY", raising=False)
        with pytest.raises(ValueError, match="SOLTI_API_KEY"):
            SoltiClient(api_url="http://127.0.0.1:1/1")

    def test_default_api_url_is_global_host(self) -> None:
        client = SoltiClient(api_key="k", api_url=DEFAULT_API_URL)
        assert client.api_url == "https://api.solti.run/1"
        client.close()

    def test_api_url_env_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SOLTI_API_URL", PREVIEW_API_URL)
        client = SoltiClient(api_key="k")
        assert client.api_url == "https://preview.api.solti.run/1"
        client.close()

    def test_explicit_api_url_wins_over_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SOLTI_API_URL", "https://from-env.example/1")
        client = SoltiClient(api_key="k", api_url="https://from-arg.example/1/")
        assert client.api_url == "https://from-arg.example/1"  # trailing slash stripped
        client.close()

    def test_project_id_from_arg_and_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = SoltiClient(api_key="k", project_id="proj-arg")
        assert client.project_id == "proj-arg"
        client.close()
        monkeypatch.setenv("SOLTI_PROJECT_ID", "proj-env")
        client = SoltiClient(api_key="k")
        assert client.project_id == "proj-env"
        client.close()


class TestHeaders:
    def test_auth_and_project_headers_sent(self, mock_api, client: SoltiClient) -> None:
        mock_api.respond_with(lambda req: json_response(payload={"ok": True}))
        client.request("jobs", "GET")
        request = mock_api.calls(method="GET", path="/1/jobs")[0]
        assert request.headers["X-Solti-API-Key"] == "test-key"
        assert request.headers["X-Solti-Project-Id"] == "proj-123"

    def test_no_project_header_without_project(self, mock_api) -> None:
        client = SoltiClient(api_key="test-key", api_url=mock_api.base_url)
        mock_api.respond_with(lambda req: json_response(payload={"ok": True}))
        client.request("jobs", "GET")
        assert "X-Solti-Project-Id" not in mock_api.calls()[0].headers


class TestWireConventions:
    def test_jobs_create_payload_uses_camel_case_keys(self, mock_api, client: SoltiClient) -> None:
        mock_api.respond_with(
            lambda req: json_response(
                payload={"job_id": "job-1", "name": "train-run-x7k9", "status": "queued",
                         "vm_status": "nonassigned", "estimated_cost": 0.42},
            )
        )
        job = client.jobs.create(
            name_prefix="train-run",
            image="pytorch/pytorch:2.2.1",
            command=["python3"],
            args=["train.py", "--epochs", "50"],
            env={"A": "1"},
            volumes={
                "datasets": {
                    "bucket": "ml-artifacts",
                    "mountPath": "/mnt/s3",
                    "connection": "my-aws-s3",
                    "prefix": "checkpoints",
                }
            },
            resources={"cpu": 8, "memory": "32Gi", "gpu": "24Gi"},  # shorthand passes through
            cloud=["aws", "gcp"],
            region="americas",
            max_retries=3,
            labels={"environment": "production"},
            tags=["pytorch", "training"],
        )

        request = mock_api.calls(method="POST", path="/1/jobs")[0]
        assert request.headers["Content-Type"] == "application/json"
        assert request.body["image"] == "pytorch/pytorch:2.2.1"
        assert request.body["namePrefix"] == "train-run"
        assert "name" not in request.body
        assert request.body["volumes"]["datasets"]["mountPath"] == "/mnt/s3"
        assert request.body["resources"]["gpu"] == "24Gi"
        assert request.body["cloud"] == ["aws", "gcp"]
        assert request.body["region"] == "americas"
        assert request.body["maxRetries"] == 3
        assert request.body["labels"] == {"environment": "production"}
        assert request.body["tags"] == ["pytorch", "training"]

        # Response fields are snake_case; create's `job_id` is normalized to `.id`.
        assert job.id == "job-1"
        assert job.name == "train-run-x7k9"
        assert job.status == "queued"
        assert job.vm_status == "nonassigned"
        assert job.estimated_cost == 0.42

    def test_jobs_create_with_explicit_name(self, mock_api, client: SoltiClient) -> None:
        mock_api.respond_with(lambda req: json_response(payload={"id": "j1", "name": "n"}))
        client.jobs.create(name="explicit", image="alpine:latest")
        body = mock_api.calls(method="POST", path="/1/jobs")[0].body
        assert body["name"] == "explicit"
        assert "namePrefix" not in body

    def test_jobs_list_filters_use_query_params(self, mock_api, client: SoltiClient) -> None:
        mock_api.respond_with(lambda req: json_response(payload={"jobs": []}))
        client.jobs.list(status="queued", tag="training", label="environment:production",
                         limit=50, offset=0)
        request = mock_api.calls(method="GET", path="/1/jobs")[0]
        assert request.query["status"] == ["queued"]
        assert request.query["tag"] == ["training"]
        assert request.query["label"] == ["environment:production"]  # key:value form
        assert request.query["limit"] == ["50"]
        assert request.query["offset"] == ["0"]

    def test_jobs_get_and_cancel(self, mock_api, client: SoltiClient) -> None:
        mock_api.respond_with(
            lambda req: json_response(payload={"id": "j1", "name": "n", "status": "cancelled"}),
        )
        job = client.jobs.get("j1")
        client.jobs.cancel(job.id)
        assert mock_api.calls(method="GET", path="/1/jobs/j1")
        cancel = mock_api.calls(method="POST", path="/1/jobs/j1/cancel")
        assert cancel and cancel[0].body is None


class TestConnectionsCronjobsKeys:
    def test_connections_crud(self, mock_api, client: SoltiClient) -> None:
        mock_api.respond_with(
            lambda req: json_response(
                payload=(
                    {"connections": [{"name": "s3", "type": "aws"}]}
                    if req.method == "GET" and req.path == "/1/connections"
                    else {"name": "s3", "type": "aws"}
                )
            )
        )
        conn = client.connections.create(
            name="s3", type="aws",
            credentials={
                "access_key_id": "AKIA", "secret_access_key": "wJal", "region": "us-east-1",
            },
        )
        create_body = mock_api.calls(method="POST", path="/1/connections")[0].body
        assert create_body == {
            "name": "s3", "type": "aws",
            "access_key_id": "AKIA", "secret_access_key": "wJal", "region": "us-east-1",
        }
        assert conn.name == "s3"

        assert client.connections.get("s3").type == "aws"
        assert [c.name for c in client.connections.list()] == ["s3"]
        client.connections.delete("s3")
        assert mock_api.calls(method="DELETE", path="/1/connections/s3")

    def test_cronjobs_crud_by_id_and_name(self, mock_api, client: SoltiClient) -> None:
        cronjob = {"id": "c1a92df4", "name": "nightly-backup", "cron_spec": "0 2 * * *",
                   "is_active": True}

        def responder(request):
            if request.method == "GET" and request.path == "/1/cronjobs":
                return json_response(payload={"cronjobs": [cronjob]})
            return json_response(payload=cronjob)

        mock_api.respond_with(responder)
        created = client.cronjobs.create(
            name="nightly-backup", cron_spec="0 2 * * *",
            job_definition={"image": "alpine:latest", "command": ["echo", "backup"]},
        )
        create = mock_api.calls(method="POST", path="/1/cronjobs")[0].body
        assert create == {
            "name": "nightly-backup",
            "cron_spec": "0 2 * * *",
            "job_definition": {"image": "alpine:latest", "command": ["echo", "backup"]},
        }
        assert created.id == "c1a92df4"

        assert client.cronjobs.get(created.id).name == "nightly-backup"
        assert mock_api.calls(method="GET", path="/1/cronjobs/c1a92df4")
        assert client.cronjobs.get("nightly-backup").id == "c1a92df4"
        assert mock_api.calls(method="GET", path="/1/cronjobs/nightly-backup")

        assert [c.name for c in client.cronjobs.list()] == ["nightly-backup"]
        assert mock_api.calls(method="GET", path="/1/cronjobs")

        patched = client.cronjobs.patch("nightly-backup", is_active=False)
        patch = mock_api.calls(method="PATCH", path="/1/cronjobs/nightly-backup")[0]
        assert patch.body == {"is_active": False}
        assert patched.is_active is True  # responder echoes the fixture

        client.cronjobs.delete("c1a92df4")
        assert mock_api.calls(method="DELETE", path="/1/cronjobs/c1a92df4")

    def test_cronjobs_update_is_alias_of_patch(self, mock_api, client: SoltiClient) -> None:
        mock_api.respond_with(lambda req: json_response(payload={"id": "c1", "name": "n"}))
        client.cronjobs.update("c1", cron_spec="0 3 * * *")
        assert mock_api.calls(method="PATCH", path="/1/cronjobs/c1")[0].body == {
            "cron_spec": "0 3 * * *"
        }

    def test_keys_list_create_delete(self, mock_api, client: SoltiClient) -> None:
        mock_api.respond_with(
            lambda req: json_response(
                payload=(
                    {"keys": [{"name": "ci", "role": "editor"}]}
                    if req.method == "GET"
                    else {"name": "ci", "api_key": "shown-once"}
                )
            )
        )
        assert [k.name for k in client.keys.list()] == ["ci"]
        created = client.keys.create(name="ci", role="editor", expires_at="2026-12-31")
        assert created.api_key == "shown-once"
        assert mock_api.calls(method="POST", path="/1/keys")[0].body == {
            "name": "ci", "role": "editor", "expires_at": "2026-12-31",
        }
        client.keys.delete("ci")
        assert mock_api.calls(method="DELETE", path="/1/keys/ci")


class TestErrorMapping:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (401, exceptions.AuthenticationError),
            (403, exceptions.PermissionDeniedError),
            (404, exceptions.NotFoundError),
            (409, exceptions.ConflictError),
            (422, exceptions.ValidationError),
            (500, exceptions.SoltiError),
        ],
    )
    def test_status_error_map(self, mock_api, client: SoltiClient,
                              status: int, expected: type) -> None:
        mock_api.respond_with(
            lambda req: json_response(status=status, payload={"message": "boom", "code": "x"})
        )
        with pytest.raises(expected) as excinfo:
            client.jobs.get("j1")
        assert excinfo.value.status == status
        assert excinfo.value.payload == {"message": "boom", "code": "x"}
        assert "boom" in str(excinfo.value)
