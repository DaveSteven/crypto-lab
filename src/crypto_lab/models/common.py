"""Common canonical market-event structures."""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from crypto_lab.models.enums import (
    DataQualityStatus,
    DataSourceType,
    ExchangeId,
    TransportType,
)


class CanonicalModel(BaseModel):
    """Strict base model shared by persisted canonical records."""

    model_config = ConfigDict(extra="forbid")


class MarketEventEnvelope[PayloadT: BaseModel](CanonicalModel):
    schema_version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    event_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    exchange_id: ExchangeId
    instrument_id: str = Field(min_length=1)
    source_type: DataSourceType
    transport: TransportType
    exchange_ts_ms: int | None = Field(default=None, ge=0)
    received_ts_ms: int = Field(ge=0)
    processed_ts_ms: int | None = Field(default=None, ge=0)
    raw_ref: str | None = None
    quality_status: DataQualityStatus
    payload: PayloadT

    @model_validator(mode="after")
    def validate_envelope_consistency(self) -> "MarketEventEnvelope[PayloadT]":
        expected_prefix = f"{self.exchange_id.value}:"
        if not self.instrument_id.startswith(expected_prefix):
            raise ValueError("instrument_id must belong to exchange_id")
        if self.processed_ts_ms is not None and self.processed_ts_ms < self.received_ts_ms:
            raise ValueError("processed_ts_ms cannot precede received_ts_ms")
        return self
