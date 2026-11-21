"""Client construction, header semantics, and request/response conventions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
                         "vm_status": "nonassigned", "estimated_cost": 0.42,
                         "run_after": "2026-11-25T02:00:00Z"},
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
        assert job.run_after == "2026-11-25T02:00:00Z"

    def test_jobs_create_run_after_datetime_serializes_rfc3339_utc(
        self, mock_api, client: SoltiClient
    ) -> None:
        mock_api.respond_with(lambda req: json_response(payload={"id": "j1", "name": "n"}))
        client.jobs.create(
            image="alpine:latest",
            run_after=datetime(2026, 11, 25, 11, 0, tzinfo=timezone(timedelta(hours=9))),
        )
        body = mock_api.calls(method="POST", path="/1/jobs")[0].body
        # +09:00 aware datetime is normalized to RFC 3339 UTC on the wire.
        assert body["runAfter"] == "2026-11-25T02:00:00Z"

    def test_jobs_create_run_after_utc_datetime_and_iso_string(
        self, mock_api, client: SoltiClient
    ) -> None:
        mock_api.respond_with(lambda req: json_response(payload={"id": "j1", "name": "n"}))
        client.jobs.create(
            image="alpine:latest", run_after=datetime(2026, 11, 25, 2, 0, tzinfo=timezone.utc)
        )
        client.jobs.create(image="alpine:latest", run_after="2026-11-25T02:00:00+00:00")
        calls = mock_api.calls(method="POST", path="/1/jobs")
        assert calls[0].body["runAfter"] == "2026-11-25T02:00:00Z"
        assert calls[1].body["runAfter"] == "2026-11-25T02:00:00+00:00"  # strings pass through

    def test_jobs_create_run_after_absent_when_none(self, mock_api, client: SoltiClient) -> None:
        mock_api.respond_with(lambda req: json_response(payload={"id": "j1", "name": "n"}))
        client.jobs.create(image="alpine:latest", run_after=None)
        body = mock_api.calls(method="POST", path="/1/jobs")[0].body
        assert "runAfter" not in body

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


class TestWorkflows:
    def test_workflows_create_templates_passthrough_and_name_prefix_alias(
        self, mock_api, client: SoltiClient
    ) -> None:
        templates = [
            {
                "name": "fetch",
                "job": {"image": "alpine:latest", "command": ["echo", "fetch"]},
            },
            {
                "name": "train",
                "job": {
                    "image": "pytorch/pytorch:2.2.1",
                    "command": ["python3", "train.py", "--item", "{{item}}"],
                    "env": {"ITEM": "{{item}}"},
                    "labels": {"shard": "{{item}}"},
                },
                "dependencies": ["fetch"],
                "withItems": ["a", "b"],
            },
            {
                "name": "publish",
                "job": {"image": "alpine:latest", "args": ["publish"]},
                "dependencies": ["train"],
                "withSequence": {"start": 1, "end": 4, "step": 2},
            },
        ]
        mock_api.respond_with(
            lambda req: json_response(
                payload={
                    "workflow_id": "wf-1",
                    "name": "train-dag-x7k9",
                    "status": "running",
                    "nodes": {
                        "train-dag-x7k9--fetch": {
                            "job_id": "job-1",
                            "name": "train-dag-x7k9--fetch",
                        },
                        "train-dag-x7k9--train-a": {
                            "job_id": "job-2",
                            "name": "train-dag-x7k9--train-a",
                        },
                    },
                }
            )
        )
        workflow = client.workflows.create(templates, name_prefix="train-dag")

        request = mock_api.calls(method="POST", path="/1/workflows")[0]
        assert request.headers["Content-Type"] == "application/json"
        # Templates dicts pass through to the API verbatim (fan-out keys are
        # camelCase wire keys and are not rewritten client-side).
        assert request.body["templates"] == templates
        assert request.body["namePrefix"] == "train-dag"
        assert "name" not in request.body

        # Create response: `workflow_id` is normalized to `.id`; the nodes map
        # (node job name → {job_id, name}) is kept verbatim.
        assert workflow.id == "wf-1"
        assert workflow.name == "train-dag-x7k9"
        assert workflow.status == "running"
        assert workflow.nodes is not None
        assert workflow.nodes["train-dag-x7k9--fetch"] == {
            "job_id": "job-1",
            "name": "train-dag-x7k9--fetch",
        }

    def test_workflows_create_with_explicit_name(self, mock_api, client: SoltiClient) -> None:
        mock_api.respond_with(
            lambda req: json_response(
                payload={
                    "workflow_id": "wf-1",
                    "name": "nightly-etl",
                    "status": "running",
                    "nodes": {},
                }
            )
        )
        client.workflows.create(
            [{"name": "a", "job": {"image": "alpine:latest"}}], name="nightly-etl"
        )
        body = mock_api.calls(method="POST", path="/1/workflows")[0].body
        assert body["name"] == "nightly-etl"
        assert "namePrefix" not in body

    def test_workflows_create_rejects_empty_or_non_dict_templates(
        self, mock_api, client: SoltiClient
    ) -> None:
        mock_api.respond_with(lambda req: json_response(payload={}))
        with pytest.raises(ValueError, match="non-empty"):
            client.workflows.create([])
        with pytest.raises(ValueError, match="dict"):
            client.workflows.create([{"name": "a", "job": {"image": "alpine:latest"}}, "nope"])
        assert not mock_api.calls()  # rejected client-side, nothing sent

    def test_workflows_get_by_id_and_name(self, mock_api, client: SoltiClient) -> None:
        detail = {
            "id": "wf-1",
            "organization_id": "org-1",
            "project_id": "proj-123",
            "name": "train-dag",
            "status": "failed",
            "error_message": "node 'train' failed",
            "created_at": "2026-11-20T10:00:00Z",
            "updated_at": "2026-11-20T10:05:00Z",
            "ended_at": "2026-11-20T10:05:00Z",
            "node_count": 2,
            "nodes": [
                {
                    "job_id": "job-1",
                    "name": "train-dag--fetch",
                    "status": "succeeded",
                    "vm_status": "terminated",
                    "started_at": "2026-11-20T10:00:01Z",
                    "ended_at": "2026-11-20T10:01:00Z",
                    "estimated_cost": 0.5,
                    "actual_cost": 0.7,
                    "ondemand_cost": 1.25,
                },
                {
                    "job_id": "job-2",
                    "name": "train-dag--train",
                    "status": "failed",
                    "vm_status": "error",
                    "error_message": "exit code 1",
                    "estimated_cost": 0.25,
                    "actual_cost": 0.4,
                },
            ],
            "estimated_cost": 0.75,
            "actual_cost": 1.1,
            "ondemand_cost": 1.25,
        }

        def responder(request):
            if request.path in ("/1/workflows/wf-1", "/1/workflows/train-dag"):
                return json_response(payload=detail)
            return json_response(status=404, payload={"message": "not found"})

        mock_api.respond_with(responder)
        workflow = client.workflows.get("wf-1")
        by_name = client.workflows.get("train-dag")

        assert mock_api.calls(method="GET", path="/1/workflows/wf-1")
        assert mock_api.calls(method="GET", path="/1/workflows/train-dag")
        assert workflow.id == "wf-1"
        assert workflow.status == "failed"
        assert workflow.node_count == 2
        assert by_name == workflow

        nodes = workflow.nodes
        assert isinstance(nodes, list) and len(nodes) == 2
        assert nodes[0].name == "train-dag--fetch"
        assert nodes[0].status == "succeeded"
        assert nodes[0].vm_status == "terminated"
        assert nodes[0].actual_cost == 0.7
        assert nodes[1].error_message == "exit code 1"
        # Aggregate cost sums over the nodes.
        assert workflow.estimated_cost == 0.75
        assert workflow.actual_cost == 1.1
        assert workflow.ondemand_cost == 1.25

    def test_workflows_list_filters_and_pagination(self, mock_api, client: SoltiClient) -> None:
        workflow = {"id": "wf-1", "name": "train-dag", "status": "running", "node_count": 3}
        mock_api.respond_with(
            lambda req: json_response(
                payload={"workflows": [workflow], "total": 12, "offset": 5, "limit": 10}
            )
        )
        workflows = client.workflows.list(status="running", limit=10, offset=5)
        request = mock_api.calls(method="GET", path="/1/workflows")[0]
        assert request.query["status"] == ["running"]
        assert request.query["limit"] == ["10"]
        assert request.query["offset"] == ["5"]
        assert [w.id for w in workflows] == ["wf-1"]
        assert workflows[0].node_count == 3

    def test_workflows_list_omits_unset_query_params(self, mock_api, client: SoltiClient) -> None:
        mock_api.respond_with(lambda req: json_response(payload={"workflows": []}))
        assert client.workflows.list() == []
        request = mock_api.calls(method="GET", path="/1/workflows")[0]
        assert not request.query

    def test_workflows_list_for_cronjob_filters_and_pagination(
        self, mock_api, client: SoltiClient
    ) -> None:
        # Change 092: cron-spawned run history — same envelope as list();
        # entries carry `cronjob_name` (the spawning cronjob's name).
        spawn = {
            "id": "wf-1",
            "name": "nightly-backup-20261121020000",
            "status": "succeeded",
            "cronjob_name": "nightly-backup",
        }
        mock_api.respond_with(
            lambda req: json_response(
                payload={"workflows": [spawn], "total": 12, "offset": 5, "limit": 10}
            )
        )
        workflows = client.workflows.list_for_cronjob(
            "nightly-backup", status="succeeded", limit=10, offset=5
        )
        request = mock_api.calls(method="GET", path="/1/cronjobs/nightly-backup/workflows")[0]
        assert request.query["status"] == ["succeeded"]
        assert request.query["limit"] == ["10"]
        assert request.query["offset"] == ["5"]
        assert [w.id for w in workflows] == ["wf-1"]
        assert workflows[0].name == "nightly-backup-20261121020000"
        assert workflows[0].cronjob_name == "nightly-backup"

    def test_workflows_list_for_cronjob_url_encodes_id_or_name(
        self, mock_api, client: SoltiClient
    ) -> None:
        # The cronjob UUID-or-name is quoted as a single path segment
        # (encodeURIComponent parity with the TS SDK).
        mock_api.respond_with(lambda req: json_response(payload={"workflows": []}))
        assert client.workflows.list_for_cronjob("nightly etl") == []
        assert mock_api.calls(method="GET", path="/1/cronjobs/nightly%20etl/workflows")

    def test_workflows_list_for_cronjob_omits_unset_query_params_and_cronjob_name_is_optional(
        self, mock_api, client: SoltiClient
    ) -> None:
        mock_api.respond_with(
            lambda req: json_response(payload={"workflows": [{"id": "wf-1", "name": "n"}]})
        )
        workflows = client.workflows.list_for_cronjob("nightly-backup")
        request = mock_api.calls(method="GET", path="/1/cronjobs/nightly-backup/workflows")[0]
        assert not request.query
        assert workflows[0].cronjob_name is None  # API/CLI submissions have no linkage

    def test_workflows_get_surfaces_cronjob_name(self, mock_api, client: SoltiClient) -> None:
        # Detail endpoint entries carry `cronjob_name` too (change 092).
        mock_api.respond_with(
            lambda req: json_response(
                payload={"id": "wf-1", "name": "nightly-backup-20261121020000",
                         "status": "succeeded", "cronjob_name": "nightly-backup"}
            )
        )
        workflow = client.workflows.get("wf-1")
        assert mock_api.calls(method="GET", path="/1/workflows/wf-1")
        assert workflow.cronjob_name == "nightly-backup"

    def test_workflows_cancel(self, mock_api, client: SoltiClient) -> None:
        mock_api.respond_with(
            lambda req: json_response(
                payload={"workflow_id": "wf-1", "name": "train-dag", "status": "cancelled"}
            )
        )
        workflow = client.workflows.cancel("wf-1")
        cancel = mock_api.calls(method="POST", path="/1/workflows/wf-1/cancel")
        assert cancel and cancel[0].body is None
        assert workflow is not None
        assert workflow.id == "wf-1"
        assert workflow.status == "cancelled"

    def test_workflows_cancel_terminal_conflict_maps_to_conflict_error(
        self, mock_api, client: SoltiClient
    ) -> None:
        mock_api.respond_with(
            lambda req: json_response(
                status=409, payload={"message": "Workflow is already terminal"}
            )
        )
        with pytest.raises(exceptions.ConflictError) as excinfo:
            client.workflows.cancel("wf-1")
        assert excinfo.value.status == 409
        assert "already terminal" in str(excinfo.value)


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
                    {"keys": [{"name": "ci", "role": "developer"}]}
                    if req.method == "GET"
                    else {"name": "ci", "api_key": "shown-once"}
                )
            )
        )
        assert [k.name for k in client.keys.list()] == ["ci"]
        created = client.keys.create(name="ci", role="developer", expires_at="2026-12-31")
        assert created.api_key == "shown-once"
        assert mock_api.calls(method="POST", path="/1/keys")[0].body == {
            "name": "ci", "role": "developer", "expires_at": "2026-12-31",
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
