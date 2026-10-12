"""Conductor participation v1 inputs; world actions remain webDiplomacy-specific."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$")]


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Controller(WireModel):
    id: Identifier
    generation: int = Field(ge=1)
    expiresAt: int | None = Field(ge=0)


class Command(WireModel):
    id: Identifier
    controllerId: Identifier
    generation: int = Field(ge=1)
    windowId: Identifier
    kind: Literal["orders", "press"]
    value: JsonValue


class Observe(WireModel):
    operation: Literal["observe"]
    seat: Identifier


class Bind(WireModel):
    operation: Literal["bind"]
    seat: Identifier
    controller: Controller


class Submit(WireModel):
    operation: Literal["command"]
    seat: Identifier
    command: Command


class Receipt(WireModel):
    operation: Literal["receipt"]
    seat: Identifier
    commandId: Identifier


host_request = TypeAdapter(Annotated[Observe | Bind | Submit | Receipt, Field(discriminator="operation")])


class Order(WireModel):
    type: Literal[
        "Hold",
        "Move",
        "Support hold",
        "Support move",
        "Convoy",
        "Retreat",
        "Disband",
        "Build Army",
        "Build Fleet",
        "Wait",
        "Destroy",
    ]
    terrID: int = Field(ge=0, default=0)
    fromTerrID: int = Field(ge=0, default=0)
    toTerrID: int = Field(ge=0, default=0)
    viaConvoy: Literal["Yes", "No"] = "No"


class Orders(WireModel):
    orders: list[Order] = Field(max_length=34)
    ready: bool = False


class Press(WireModel):
    toCountryID: int = Field(ge=0, le=7)
    message: str = Field(min_length=1, max_length=4000)
