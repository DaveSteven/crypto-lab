"""Models for evidence collected from real public API probes."""

from pydantic import BaseModel, ConfigDict, Field

from crypto_lab.models.enums import TransportType


class APIProbeResult(BaseModel):
    """Outcome of one real API request, following schema version 1.0.0."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    probe_id: str = Field(min_length=1)
    exchange_id: str = Field(min_length=1)
    endpoint_type: str = Field(min_length=1)
    endpoint: str | None = None
    transport: TransportType
    started_ts_ms: int = Field(ge=0)
    completed_ts_ms: int | None = Field(default=None, ge=0)
    duration_ms: int | None = Field(default=None, ge=0)
    success: bool
    status_code: int | None = Field(default=None, ge=100, le=599)
    error_type: str | None = None
    error_message: str | None = None
    response_ref: str | None = None
