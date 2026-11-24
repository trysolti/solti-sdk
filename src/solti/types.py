"""Typed contracts for the Solti API (api spec §3).

Finite value sets are `Literal` string unions mirroring the exact wire values.
Request models serialize with camelCase aliases (api spec §3.0 request
conventions); response models keep the snake_case field names of API JSON
responses and preserve unknown fields (`extra="allow"`) so SDK updates never
drop newly added API fields.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

# -- finite value sets (string unions) ----------------------------------------

#: Top-level workload lifecycle (scheduler spec §"Job Status Lifecycle").
WorkloadStatus = Literal["queued", "booting", "running", "succeeded", "failed", "cancelled"]

#: Statuses from which no further transitions occur.
TerminalStatus = Literal["succeeded", "failed", "cancelled"]

#: Infrastructure lifecycle — strictly monotonic (scheduler spec §vm_status).
VmStatus = Literal[
    "nonassigned", "provisioning", "provisioned", "terminating", "terminated", "error"
]

#: Workflow lifecycle (api `Workflow.status`): `running` until every node
#: job is terminal; the scheduler finalizes succeeded/failed/cancelled.
WorkflowStatus = Literal["running", "succeeded", "failed", "cancelled"]

#: Cloud providers accepted by job routing and connections.
CloudProvider = Literal["aws", "gcp", "azure"]

#: Connection integration types (cli `solti connection create --type`).
ConnectionType = Literal["aws", "gcp", "azure", "r2", "github"]

#: Key roles (api `keys/models.py`: `Role = Literal[...]`).
KeyRole = Literal["admin", "developer", "viewer"]

#: Macro-regions accepted as `region` routing constraints (api spec §3.2).
MacroRegion = Literal["americas", "europe", "apac", "africa", "middle-east"]


# -- job request models ---------------------------------------------------------


class GpuRequest(BaseModel):
    """Nested GPU request (api spec §3.2 resources.gpu long form)."""

    model_config = ConfigDict(extra="forbid")

    #: Minimum aggregate GPU VRAM (e.g. `"24Gi"`); required unless `model` is given.
    vram: str | None = None
    #: Hard constraint on GPU model (e.g. `"A100"`); matched case-insensitively.
    model: str | None = None
    #: Hard constraint on the minimum number of physical GPUs (requires `model`).
    count: int | None = None


class VolumeMount(BaseModel):
    """A storage volume mount; passed as a map value keyed by volume name."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    #: Required: target cloud storage bucket name.
    bucket: str
    #: Required: absolute in-container mount path (wire key `mountPath`).
    mount_path: str = Field(alias="mountPath")
    #: Optional: connection name (defaults to the first connection with bucket access).
    connection: str | None = None
    #: Optional: key/folder prefix within the bucket (defaults to the bucket root).
    prefix: str | None = None


class JobResources(BaseModel):
    """Compute resources. Defaults (api-side): `cpu: 1`, `memory: "4Gi"`."""

    model_config = ConfigDict(extra="forbid")

    #: Fractional cpu is accepted api-side (DB rows carry e.g. `0.5`).
    cpu: float | None = None
    memory: str | None = None
    #: VRAM shorthand (`"24Gi"`) or nested request (`{"vram": "24Gi"}`).
    gpu: str | GpuRequest | None = None
    #: Boot/root disk size of the provisioned VM (change 100): integer GiB
    #: (`100`) or quantity string (`"100Gi"` / `"102400Mi"`), bounds
    #: 10–16384 GiB (integral — fractional quantities are rejected `422`).
    #: Omitted ⇒ per-provider image default (AWS 8 GiB, GCP 10 GB, Azure 30 GB).
    storage: int | str | None = None


class CreateJobRequest(BaseModel):
    """`POST /1/jobs` payload — camelCase wire keys (api spec §3.0)."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    image: str
    #: Optional unique job name (unique per project; `409` on duplicate).
    name: str | None = None
    #: Optional prefix — API generates `<prefix>-<random_suffix>` (wire `namePrefix`).
    name_prefix: str | None = Field(None, alias="namePrefix")
    command: list[str] | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    #: Map keyed by volume name (unique per job).
    volumes: dict[str, VolumeMount] | None = None
    resources: JobResources | None = None
    #: Provider constraints — single provider or array (api spec §3.2 `cloud`).
    cloud: CloudProvider | list[CloudProvider] | None = None
    #: Specific region(s) or macro-region.
    region: str | list[str] | None = None
    #: Container retries inside the VM (wire `maxRetries`).
    max_retries: int | None = Field(None, alias="maxRetries")
    #: Optional scheduled start (change 090): the job stays `queued` (no VM,
    #: no cost) until the instant passes, then provisions normally; cancel
    #: works while waiting. Accepts a timezone-aware `datetime` or an RFC 3339
    #: string (wire `runAfter`, serialized to RFC 3339 UTC). Naive datetimes
    #: pass through unzoned — the API rejects them `422` (A-1: no zone guessing).
    run_after: datetime | str | None = Field(None, alias="runAfter")
    labels: dict[str, str] | None = None
    tags: list[str] | None = None

    @field_serializer("run_after")
    def _serialize_run_after(self, value: datetime | str | None) -> str | None:
        """Serializes aware datetimes to RFC 3339 UTC (e.g. `2026-11-25T02:00:00Z`)."""
        if value is None or isinstance(value, str):
            return value
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return value.isoformat()  # naive: unzoned; API rejects with `422` (no guessing)


class JobDefinition(BaseModel):
    """Cronjob job template — a standard job definition without `name` (api
    spec §3.3: each trigger spawns `<cronjob-name>-<UTC timestamp>`). Unknown
    template fields are preserved verbatim on the wire."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    image: str | None = None
    command: list[str] | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    volumes: dict[str, VolumeMount] | None = None
    resources: JobResources | None = None
    cloud: CloudProvider | list[CloudProvider] | None = None
    region: str | list[str] | None = None
    max_retries: int | None = Field(None, alias="maxRetries")
    labels: dict[str, str] | None = None
    tags: list[str] | None = None


class CreateWorkflowRequest(BaseModel):
    """`POST /1/workflows` payload — camelCase wire keys (api spec §3.0)."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    #: DAG node templates — one entry per node: a standard job definition
    #: (`job`) plus its `name`, optional `dependencies` edges and optional
    #: `withItems`/`withSequence` static fan-out. Passed through to the API
    #: verbatim (the API owns full template validation and the ≤ 50 node cap).
    templates: list[dict[str, Any]]
    #: Optional unique workflow name (slug format); `409` on duplicate.
    name: str | None = None
    #: Optional prefix — API generates `<prefix>-<random suffix>` (wire `namePrefix`).
    name_prefix: str | None = Field(None, alias="namePrefix")


# -- connection request models ---------------------------------------------------


class AwsCredentials(BaseModel):
    """`type: "aws"` credential fields (cli wire format)."""

    model_config = ConfigDict(extra="allow")

    access_key_id: str
    secret_access_key: str
    region: str | None = None


class GcpCredentials(BaseModel):
    """`type: "gcp"` credential fields (cli wire format)."""

    model_config = ConfigDict(extra="allow")

    gcp_project_id: str
    #: Service-account key JSON (stringified) or `None` for ADC-style creds.
    keyfile_json: str | None = None


class AzureCredentials(BaseModel):
    """`type: "azure"` credential fields (cli wire format)."""

    model_config = ConfigDict(extra="allow")

    client_id: str
    client_secret: str
    subscription_id: str
    tenant_id: str


class R2Credentials(BaseModel):
    """`type: "r2"` (Cloudflare R2) credential fields (cli wire format)."""

    model_config = ConfigDict(extra="allow")

    account_id: str
    access_key_id: str
    secret_access_key: str


class GithubCredentials(BaseModel):
    """`type: "github"` credential fields (cli wire format)."""

    model_config = ConfigDict(extra="allow")

    access_token: str


#: Provider-specific credentials, flattened onto the wire payload (cli convention).
ConnectionCredentials = (
    AwsCredentials | GcpCredentials | AzureCredentials | R2Credentials | GithubCredentials
)


class CreateConnectionRequest(BaseModel):
    """`POST /1/connections` payload. Credential fields are sent flat at the
    top level (cli wire format), not nested under `credentials`."""

    model_config = ConfigDict(extra="forbid")

    name: str
    type: ConnectionType
    credentials: ConnectionCredentials | dict[str, Any] | None = None


class CreateCronjobRequest(BaseModel):
    """`POST /1/cronjobs` payload (snake_case wire keys)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    #: UTC crontab expression (e.g. `"0 2 * * *"`).
    cron_spec: str
    job_definition: JobDefinition
    #: Defaults to `true` api-side.
    is_active: bool | None = None


class PatchCronjobRequest(BaseModel):
    """`PATCH /1/cronjobs/{id_or_name}` payload — partial update."""

    model_config = ConfigDict(extra="forbid")

    cron_spec: str | None = None
    is_active: bool | None = None
    job_definition: JobDefinition | None = None


class CreateKeyRequest(BaseModel):
    """`POST /1/keys` payload (admin only; api spec §3.4)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    role: KeyRole
    #: Optional expiry (ISO 8601).
    expires_at: str | None = None
