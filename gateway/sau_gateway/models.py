from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


Identifier = Annotated[str, Field(min_length=1, max_length=512)]
Provider = Literal["bitbrowser", "adspower"]
Platform = Literal["rednote", "xiaohongshu", "tiktok", "instagram"]
Action = Literal["check"]


class Capability(WireModel):
    platform: Platform
    action: Action


class Profile(WireModel):
    profileId: Identifier
    name: Annotated[str, Field(max_length=1024)]


class ProviderReport(WireModel):
    provider: Provider
    available: bool
    profiles: list[Profile]


class Session(WireModel):
    mode: Literal["worker", "self-check"] = "worker"
    sessionId: UUID
    cliRelease: Identifier | None = None
    release: Identifier
    contractVersion: Literal[1]
    capabilities: list[Capability]
    capacity: Annotated[int, Field(ge=1)]
    freeSlots: Annotated[int, Field(ge=0)]
    providers: list[ProviderReport]

    @model_validator(mode="after")
    def valid_slots(self):
        if self.freeSlots > self.capacity:
            raise ValueError("freeSlots exceeds capacity")
        return self


class CheckTarget(WireModel):
    provider: Provider
    profileId: Identifier
    platform: Platform


class Task(CheckTarget):
    workflowId: Identifier
    contractVersion: Literal[1]
    requiredCapability: Identifier
    release: Identifier
    action: Action

    @model_validator(mode="after")
    def capability_matches(self):
        if self.requiredCapability != f"{self.platform}.{self.action}":
            raise ValueError("requiredCapability must match platform.action")
        return self


class Claim(WireModel):
    sessionId: UUID
    waitSeconds: Annotated[int, Field(ge=0, le=30)] = 20


class CheckReceipt(WireModel):
    cloudConnected: Literal[True]
    cliInvoked: bool
    profileVisible: bool
    platformLogin: Literal["valid", "login-required", "unknown"]
    exitCode: int | None

    @model_validator(mode="after")
    def consistent_evidence(self):
        if self.platformLogin == "valid" and not (self.cliInvoked and self.profileVisible and self.exitCode == 0):
            raise ValueError("valid login requires a successful profile check")
        return self


class Result(WireModel):
    workflowId: Identifier
    sessionId: UUID
    receipt: CheckReceipt
