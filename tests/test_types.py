"""Typed contracts: pydantic models, string unions, aliases, and wire dumps."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from solti import (
    AzureCredentials,
    Connection,
    CreateJobRequest,
    CreateKeyResponse,
    Cronjob,
    GcpCredentials,
    GithubCredentials,
    GpuRequest,
    Job,
    JobDefinition,
    JobResources,
    Key,
    PatchCronjobRequest,
    R2Credentials,
    VolumeMount,
)
from solti.types import (
    CloudProvider,
    ConnectionType,
    KeyRole,
    MacroRegion,
    TerminalStatus,
    VmStatus,
    WorkloadStatus,
)


class TestStringUnions:
    def test_union_members_are_exact_wire_values(self) -> None:
        # WorkloadStatus (scheduler spec: queued -> booting -> running -> terminal)
        assert set(WorkloadStatus.__args__) == {  # type: ignore[attr-defined]
            "queued", "booting", "running", "succeeded", "failed", "cancelled",
        }
        assert set(TerminalStatus.__args__) == {"succeeded", "failed", "cancelled"}  # type: ignore[attr-defined]
        # VmStatus — strictly monotonic lifecycle (scheduler spec)
        assert set(VmStatus.__args__) == {  # type: ignore[attr-defined]
            "nonassigned", "provisioning", "provisioned", "terminating", "terminated", "error",
        }
        assert set(CloudProvider.__args__) == {"aws", "gcp", "azure"}  # type: ignore[attr-defined]
        assert set(ConnectionType.__args__) == {  # type: ignore[attr-defined]
            "aws", "gcp", "azure", "r2", "github",
        }
        assert set(KeyRole.__args__) == {"admin", "developer", "viewer"}  # type: ignore[attr-defined]
        assert set(MacroRegion.__args__) == {  # type: ignore[attr-defined]
            "americas", "europe", "apac", "africa", "middle-east",
        }

    def test_literal_rejects_unknown_values(self) -> None:
        with pytest.raises(ValidationError):
            Job.model_validate({"id": "j1", "name": "n", "status": "queued-ish"})
        with pytest.raises(ValidationError):
            Key.model_validate({"name": "ci", "role": "editor"})
        with pytest.raises(ValidationError):
            Connection.model_validate({"name": "c", "type": "s3-compatible"})
        with pytest.raises(ValidationError):
            Job.model_validate({"id": "j1", "vm_status": "assigned"})


class TestCreateJobRequest:
    def test_camel_case_wire_dump_excludes_none(self) -> None:
        request = CreateJobRequest(
            image="pytorch/pytorch:2.2.1",
            name_prefix="train-epoch-",
            max_retries=3,
            volumes={
                "datasets": VolumeMount(
                    bucket="ml-artifacts", mount_path="/mnt/s3", prefix="ckpts"
                )
            },
            resources=JobResources(cpu=8, memory="32Gi", gpu=GpuRequest(vram="24Gi")),
        )
        dump = request.model_dump(by_alias=True, exclude_none=True)
        assert dump["namePrefix"] == "train-epoch-"
        assert dump["maxRetries"] == 3
        assert dump["volumes"]["datasets"]["mountPath"] == "/mnt/s3"
        assert dump["resources"]["gpu"] == {"vram": "24Gi"}
        assert "name" not in dump

    def test_gpu_shorthand_string_passes_through(self) -> None:
        request = CreateJobRequest(
            image="alpine:latest", resources={"gpu": "24Gi"}
        )
        dump = request.model_dump(by_alias=True, exclude_none=True)
        assert dump["resources"]["gpu"] == "24Gi"

    def test_gpu_nested_with_model_and_count(self) -> None:
        request = CreateJobRequest(
            image="alpine:latest",
            resources=JobResources(gpu=GpuRequest(model="a100", count=4)),
        )
        dump = request.model_dump(by_alias=True, exclude_none=True)
        assert dump["resources"]["gpu"] == {"model": "a100", "count": 4}

    def test_cloud_accepts_provider_union(self) -> None:
        single = CreateJobRequest(image="i", cloud="aws")
        multi = CreateJobRequest(image="i", cloud=["aws", "gcp"])
        assert single.model_dump(by_alias=True)["cloud"] == "aws"
        assert multi.model_dump(by_alias=True)["cloud"] == ["aws", "gcp"]
        with pytest.raises(ValidationError):
            CreateJobRequest(image="i", cloud=["aws", "hetzner"])

    def test_population_by_name_and_alias(self) -> None:
        by_alias = CreateJobRequest.model_validate(
            {"image": "i", "namePrefix": "p", "maxRetries": 2}
        )
        by_name = CreateJobRequest.model_validate(
            {"image": "i", "name_prefix": "p", "max_retries": 2}
        )
        assert by_alias.name_prefix == by_name.name_prefix == "p"
        assert by_alias.max_retries == by_name.max_retries == 2

    def test_unknown_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CreateJobRequest.model_validate({"image": "i", "namePrefixx": "p"})


class TestJobResponse:
    def test_create_response_job_id_normalized_to_id(self) -> None:
        job = Job.model_validate(
            {"job_id": "job-1", "name": "n", "status": "queued", "vm_status": "nonassigned"}
        )
        assert job.id == "job-1"
        assert job.vm_status == "nonassigned"

    def test_snake_case_response_fields(self) -> None:
        job = Job.model_validate(
            {
                "id": "j1",
                "name": "n",
                "status": "succeeded",
                "estimated_cost": 0.42,
                "actual_cost": 1.23,
                "exit_code": 0,
                "oom_killed": False,
                "created_at": "2026-01-01T00:00:00Z",
            }
        )
        assert job.estimated_cost == 0.42
        assert job.actual_cost == 1.23
        assert job.exit_code == 0
        assert job.oom_killed is False

    def test_unknown_api_fields_are_preserved(self) -> None:
        job = Job.model_validate({"id": "j1", "brand_new_field": {"a": 1}})
        assert job.brand_new_field == {"a": 1}  # type: ignore[attr-defined]


class TestConnectionModels:
    def test_provider_credential_models(self) -> None:
        assert GcpCredentials(gcp_project_id="p").gcp_project_id == "p"
        assert GithubCredentials(access_token="t").access_token == "t"
        assert AzureCredentials(
            client_id="c", client_secret="s", subscription_id="sub", tenant_id="t"
        ).subscription_id == "sub"
        assert R2Credentials(
            account_id="a", access_key_id="k", secret_access_key="s"
        ).account_id == "a"
        with pytest.raises(ValidationError):
            GcpCredentials()  # missing gcp_project_id

    def test_connection_response_preserves_extra_fields(self) -> None:
        conn = Connection.model_validate(
            {"name": "s3", "type": "aws", "created_at": "2026-01-01T00:00:00Z"}
        )
        assert conn.type == "aws"
        assert conn.created_at == "2026-01-01T00:00:00Z"


class TestCronjobModels:
    def test_create_cronjob_wire_dump(self) -> None:
        from solti import CreateCronjobRequest

        request = CreateCronjobRequest(
            name="nightly-backup",
            cron_spec="0 2 * * *",
            job_definition={"image": "alpine:latest", "command": ["echo", "backup"]},
        )
        dump = request.model_dump(exclude_none=True)
        assert dump == {
            "name": "nightly-backup",
            "cron_spec": "0 2 * * *",
            "job_definition": {"image": "alpine:latest", "command": ["echo", "backup"]},
        }

    def test_patch_cronjob_partial_dump(self) -> None:
        request = PatchCronjobRequest(is_active=False)
        assert request.model_dump(exclude_none=True) == {"is_active": False}
        request = PatchCronjobRequest(
            cron_spec="0 3 * * *",
            job_definition=JobDefinition(image="python:3.13-slim", max_retries=1),
        )
        dump = request.model_dump(exclude_none=True)
        assert dump["cron_spec"] == "0 3 * * *"
        assert dump["job_definition"]["max_retries"] == 1  # cronjob wire keys are snake_case
        assert "is_active" not in dump

    def test_cronjob_response(self) -> None:
        cron = Cronjob.model_validate(
            {
                "id": "c1",
                "name": "nightly",
                "cron_spec": "0 2 * * *",
                "is_active": True,
                "last_triggered_at": "2026-01-01T02:00:00Z",
                "job_definition": {"image": "alpine:latest"},
            }
        )
        assert cron.cron_spec == "0 2 * * *"
        assert cron.is_active is True
        assert cron.job_definition is not None and cron.job_definition.image == "alpine:latest"


class TestKeyModels:
    def test_create_key_response_token_variants(self) -> None:
        assert CreateKeyResponse.model_validate(
            {"name": "ci", "api_key": "pat_123"}
        ).api_key == "pat_123"
        assert CreateKeyResponse.model_validate({"name": "ci", "token": "pat_456"}).token == (
            "pat_456"
        )

    def test_key_response(self) -> None:
        key = Key.model_validate({"name": "ci", "role": "viewer"})
        assert key.role == "viewer"


class TestVolumeMount:
    def test_alias_round_trip(self) -> None:
        mount = VolumeMount.model_validate(
            {"bucket": "b", "mountPath": "/mnt/x", "connection": "c"}
        )
        assert mount.mount_path == "/mnt/x"
        assert mount.model_dump(by_alias=True)["mountPath"] == "/mnt/x"
        with pytest.raises(ValidationError):
            VolumeMount.model_validate({"bucket": "b"})  # mountPath required
