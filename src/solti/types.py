"""Typed contracts for the Solti API (api spec §3).

Finite value sets are `Literal` string unions mirroring the exact wire values.
Request models serialize with camelCase aliases (api spec §3.0 request
conventions); response models keep the snake_case field names of API JSON
responses and preserve unknown fields (`extra="allow"`) so SDK updates never
drop newly added API fields.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# -- finite value sets (string unions) ----------------------------------------

#: Top-level workload lifecycle (scheduler spec §"Job Status Lifecycle").
WorkloadStatus = Literal["queued", "booting", "running", "succeeded", "failed", "cancelled"]

#: Statuses from which no further transitions occur.
TerminalStatus = Literal["succeeded", "failed", "cancelled"]

#: Infrastructure lifecycle — strictly monotonic (scheduler spec §vm_status).
VmStatus = Literal[
    "nonassigned", "provisioning", "provisioned", "terminating", "terminated", "error"
]

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

    cpu: int | None = None
    memory: str | None = None
    #: VRAM shorthand (`"24Gi"`) or nested request (`{"vram": "24Gi"}`).
    gpu: str | GpuRequest | None = None


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
    labels: dict[str, str] | None = None
    tags: list[str] | None = None


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
