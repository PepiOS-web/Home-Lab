from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator


class CapturedSource(BaseModel):
    id: str = Field(pattern=r"^S[1-9][0-9]*$")
    url: HttpUrl
    title: str = Field(min_length=3, max_length=240)
    excerpt: str = Field(min_length=40, max_length=12000)
    retrieved_at: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ScriptSegment(BaseModel):
    heading: str = Field(min_length=3, max_length=100)
    narration: str = Field(min_length=20, max_length=1300)
    visual_direction: str = Field(min_length=5, max_length=300)
    visual_kind: Literal[
        "auto",
        "moon_light",
        "moon_phases",
        "orbit",
        "eclipse",
        "planet",
        "rings",
        "star",
        "galaxy",
        "telescope",
        "scale",
        "timeline",
    ] = "auto"
    source_ids: list[str] = Field(min_length=1, max_length=6)


class ShortDraft(BaseModel):
    title: str = Field(min_length=5, max_length=100)
    hook: str = Field(min_length=10, max_length=250)
    body: str = Field(min_length=20, max_length=650)
    call_to_action: str = Field(min_length=5, max_length=180)
    source_ids: list[str] = Field(min_length=1, max_length=6)


class ContentPackage(BaseModel):
    language: Literal["es-ES"]
    title_options: list[str] = Field(min_length=3, max_length=5)
    selected_title: str = Field(min_length=5, max_length=100)
    description: str = Field(min_length=80, max_length=5000)
    thumbnail_text: str = Field(min_length=2, max_length=45)
    segments: list[ScriptSegment] = Field(min_length=3, max_length=10)
    shorts: list[ShortDraft] = Field(min_length=1, max_length=3)
    source_summary: list[str] = Field(min_length=1, max_length=10)
    warnings: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def selected_title_must_be_an_option(self) -> ContentPackage:
        if self.selected_title not in self.title_options:
            raise ValueError("selected_title debe estar dentro de title_options")
        return self


class AuditedContent(BaseModel):
    content: ContentPackage
    corrections: list[str] = Field(default_factory=list, max_length=10)


class JobView(BaseModel):
    id: str
    created_at: str
    updated_at: str
    topic: str
    source_urls: list[str]
    target_seconds: int
    status: str
    pending_action: str | None
    progress: str
    error: str | None
    package: ContentPackage | None
    approved_script_at: str | None
    approved_render_at: str | None
    output_dir: str | None
