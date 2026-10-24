"""Pydantic request/response models for the REST API."""

from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar

import re

from pydantic import BaseModel, Field, field_validator

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")


def _email(v: str) -> str:
    v = v.strip().lower()
    if not EMAIL_RE.match(v):
        raise ValueError("invalid email address")
    return v


class LoginIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=1, max_length=200)
    _v = field_validator("email")(classmethod(lambda cls, v: _email(v)))


class RegisterIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=10, max_length=200)
    display_name: str = Field(min_length=1, max_length=60)
    _v = field_validator("email")(classmethod(lambda cls, v: _email(v)))


class UserOut(BaseModel):
    id: int
    email: str
    display_name: str
    is_demo: bool
    reporting_timezone: str
    anomaly_sensitivity: str
    active_dataset_id: int | None


class UserSettingsIn(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=60)
    reporting_timezone: str | None = Field(default=None, max_length=64)
    anomaly_sensitivity: Literal["conservative", "balanced", "sensitive"] | None = None
    active_dataset_id: int | None = None


class AnalysisCreate(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    dataset_id: int | None = None
    parent_id: int | None = None

    @field_validator("question")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 3:
            raise ValueError("question is too short")
        return v


class AnalysisPatch(BaseModel):
    saved: bool | None = None
    title: str | None = Field(default=None, min_length=1, max_length=120)


class AnalysisSummary(BaseModel):
    id: int
    question: str
    title: str | None
    status: str
    mode: str
    intent: str | None
    saved: bool
    created_at: str
    duration_ms: int | None
    dataset_id: int
    parent_id: int | None
    summary: str | None
    error_message: str | None


class AnalysisOut(BaseModel):
    id: int
    question: str
    title: str | None
    status: str
    mode: str
    intent: str | None
    saved: bool
    created_at: str
    duration_ms: int | None
    dataset_id: int
    dataset_name: str | None
    dataset_is_synthetic: bool
    parent_id: int | None
    plan: dict | None
    generated_sql: str | None
    sql_validation: dict | None
    result: dict | None
    explanation: dict | None
    pipeline_trace: dict | None
    error_code: str | None
    error_message: str | None
    llm_usage: dict | None
    data_as_of: str | None
    current_data_as_of: str | None
    result_is_historical: bool


class AnomalyPatch(BaseModel):
    status: Literal["new", "investigating", "resolved", "not_actionable"]
    note: str | None = Field(default=None, max_length=500)


class ReportCreate(BaseModel):
    analysis_id: int | None = None
    kind: Literal["investigation", "briefing"] = "investigation"
    title: str | None = Field(default=None, max_length=120)
    dataset_id: int | None = None


class ReportOut(BaseModel):
    id: int
    kind: str
    title: str
    analysis_id: int | None
    markdown: str
    data_as_of: str | None
    created_at: str


class ImportIn(BaseModel):
    mapping: dict[str, str | None]
    dataset_name: str = Field(min_length=1, max_length=120)
    reporting_timezone: str = Field(default="UTC", max_length=64)


class ErrorOut(BaseModel):
    error: dict[str, Any]
