"""Validated client control messages for protocol version 1."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from crypto_lab.realtime.hub import Subscription


class ControlModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResumeCursor(ControlModel):
    stream_id: str = Field(min_length=1, max_length=100)
    stream_sequence: int = Field(ge=0)


class SubscribeMessage(ControlModel):
    type: Literal["subscribe"]
    request_id: str = Field(min_length=1, max_length=100)
    topics: list[Subscription] = Field(min_length=1)
    resume_from: ResumeCursor | None = None


class UnsubscribeMessage(ControlModel):
    type: Literal["unsubscribe"]
    request_id: str = Field(min_length=1, max_length=100)
    topics: list[Subscription] = Field(min_length=1)


class PingMessage(ControlModel):
    type: Literal["ping"]
    request_id: str = Field(min_length=1, max_length=100)


class PongMessage(ControlModel):
    type: Literal["pong"]
    heartbeat_id: str = Field(min_length=1, max_length=100)


ClientMessage = SubscribeMessage | UnsubscribeMessage | PingMessage | PongMessage


def parse_client_message(value: object) -> ClientMessage:
    if not isinstance(value, dict):
        raise ValueError("control message must be a JSON object")
    kind = value.get("type")
    models = {
        "subscribe": SubscribeMessage,
        "unsubscribe": UnsubscribeMessage,
        "ping": PingMessage,
        "pong": PongMessage,
    }
    model = models.get(kind)
    if model is None:
        raise ValueError("unsupported control message type")
    return model.model_validate(value)
