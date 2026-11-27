from datetime import datetime
from urllib.parse import urlsplit
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


Identifier = Annotated[str, Field(min_length=1, max_length=512)]
Provider = Literal["bitbrowser", "adspower", "local-chrome"]
Platform = Literal["rednote", "xiaohongshu", "tiktok", "instagram"]
Action = Literal["check", "upload-video", "upload-note"]


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


ReleaseSha = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
PackageDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
DesktopTarget = Literal["macos-arm64", "macos-x86_64", "windows-x86_64"]


class Installation(WireModel):
    machineId: UUID
    revision: ReleaseSha
    sha256: PackageDigest
    target: DesktopTarget
    batchId: UUID | None = None


class Session(WireModel):
    installation: Installation | None = None
    mode: Literal["worker", "self-check"] = "worker"
    sessionId: UUID
    cliRelease: Identifier | None = None
    release: Identifier
    contractVersion: Literal[1]
    preparedStarts: StrictBool = False
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


class CheckTask(Task):
    action: Literal["check"]


class Media(WireModel):
    id: Identifier
    url: str
    role: Literal["video", "cover", "image"]

    @field_validator("url")
    @classmethod
    def readable_url(cls, value):
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname or any(c.isspace() for c in value):
            raise ValueError("media must use a desktop-readable HTTP(S) URL")
        return value


class PublishTask(Task):
    action: Literal["upload-video", "upload-note"]
    organizationId: Identifier
    bindingId: Identifier
    postId: Identifier
    channelId: Identifier
    caption: str
    settings: dict
    media: list[Media]
    earliestPublishAt: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")] | None
    claimDeadlineAt: AwareDatetime | None = None
    noPublish: StrictBool

    @model_validator(mode="after")
    def media_contract(self):
        roles = sorted(item.role for item in self.media)
        if self.action == "upload-video" and roles not in (["video"], ["cover", "video"]):
            raise ValueError("Video requires one video and an optional cover")
        if self.action == "upload-note" and (not roles or set(roles) != {"image"}):
            raise ValueError("Image post requires ordered images")
        if self.earliestPublishAt:
            datetime.strptime(self.earliestPublishAt, "%Y-%m-%dT%H:%M:%SZ")
        return self


class Preparation(WireModel):
    task: PublishTask
    expiresAt: AwareDatetime


class Start(WireModel):
    workflowId: Identifier
    sessionId: UUID


class PreparedStart(Start):
    preparedMedia: list[Media]
    mediaFailed: StrictBool = False


class LeaseCommand(Start):
    leaseGrantId: UUID


class LeaseRelease(LeaseCommand):
    windowClosed: StrictBool

    @field_validator("windowClosed")
    @classmethod
    def confirmed(cls, value):
        if not value:
            raise ValueError("Release requires observed window closure")
        return value


class Claim(WireModel):
    acceptPreparation: StrictBool = False
    sessionId: UUID
    waitSeconds: Annotated[int, Field(ge=0, le=30)] = 20


class CheckReceipt(WireModel):
    cloudConnected: Literal[True]
    cliInvoked: bool
    profileVisible: bool
    platformLogin: Literal["valid", "login-required", "login-or-verification-required", "verification-required", "unknown"]
    exitCode: int | None

    @model_validator(mode="after")
    def consistent_evidence(self):
        if self.platformLogin == "valid" and not (self.cliInvoked and self.profileVisible and self.exitCode == 0):
            raise ValueError("valid login requires a successful profile check")
        return self


class PublishReceipt(WireModel):
    outcome: Literal["published", "prepared", "failed", "unknown", "processing"]
    cliInvoked: StrictBool
    exitCode: int | None

    reason: Literal["login_required", "verification_required", "upload_timeout", "pre_submit_failure", "possible_submission", "authorization_declined"] | None = None
    releaseId: Identifier | None = None
    url: Annotated[str, Field(max_length=2048)] | None = None
    publishAttempted: StrictBool | None = None

    @model_validator(mode="after")
    def consistent_evidence(self):
        if self.url:
            parts = urlsplit(self.url)
            if parts.scheme not in {"https", "http"} or not parts.hostname or parts.username or parts.password:
                raise ValueError("Expected a public post URL")
        if self.outcome == "processing" and (not self.cliInvoked or self.exitCode is not None):
            raise ValueError("Processing describes a running child")
        if self.outcome == "failed" and (self.exitCode == 9 or self.publishAttempted):
            raise ValueError("A possible submission requires review")
        if not self.cliInvoked and self.exitCode is not None:
            raise ValueError("exitCode requires a child")
        if self.outcome in ("published", "prepared") and not (self.cliInvoked and self.exitCode == 0):
            raise ValueError("successful publishing or preparation requires a successful child")
        return self


class Result(Start):
    receipt: CheckReceipt | PublishReceipt
