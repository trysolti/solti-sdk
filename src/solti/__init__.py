"""Solti Platform Python SDK (package `solti-sdk`, import `solti`)."""

from ._client import DEFAULT_API_URL, PREVIEW_API_URL, SoltiClient
from .exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    SoltiError,
    TimeoutError,
    ValidationError,
    WorkloadFailedError,
)
from .resources.connections import Connection
from .resources.cronjobs import Cronjob
from .resources.jobs import Job
from .resources.keys import CreateKeyResponse, Key
from .types import (
    AwsCredentials,
    AzureCredentials,
    CloudProvider,
    ConnectionCredentials,
    ConnectionType,
    CreateConnectionRequest,
    CreateCronjobRequest,
    CreateJobRequest,
    CreateKeyRequest,
    GcpCredentials,
    GithubCredentials,
    GpuRequest,
    JobDefinition,
    JobResources,
    KeyRole,
    MacroRegion,
    PatchCronjobRequest,
    R2Credentials,
    TerminalStatus,
    VmStatus,
    VolumeMount,
    WorkloadStatus,
)

__version__ = "0.1.1"

__all__ = [
    "DEFAULT_API_URL",
    "PREVIEW_API_URL",
    "SoltiClient",
    # Resources
    "Job",
    "Connection",
    "Cronjob",
    "Key",
    "CreateKeyResponse",
    # Request models
    "CreateJobRequest",
    "JobDefinition",
    "JobResources",
    "GpuRequest",
    "VolumeMount",
    "CreateConnectionRequest",
    "CreateCronjobRequest",
    "PatchCronjobRequest",
    "CreateKeyRequest",
    # Credential models
    "ConnectionCredentials",
    "AwsCredentials",
    "GcpCredentials",
    "AzureCredentials",
    "R2Credentials",
    "GithubCredentials",
    # String-union value sets
    "WorkloadStatus",
    "TerminalStatus",
    "VmStatus",
    "CloudProvider",
    "ConnectionType",
    "KeyRole",
    "MacroRegion",
    # Exceptions
    "SoltiError",
    "AuthenticationError",
    "PermissionDeniedError",
    "NotFoundError",
    "ConflictError",
    "ValidationError",
    "RateLimitError",
    "WorkloadFailedError",
    "TimeoutError",
    "__version__",
]
