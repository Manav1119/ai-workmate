"""Structured question interpretation (the contract between NL and SQL)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.analytics.metrics import METRICS
from app.analytics.periods import PRESETS

MetricKey = Literal[
    "spend", "impressions", "clicks", "conversions", "revenue", "ctr", "conversion_rate", "cpc", "cpa", "roas", "aov"
]
Intent = Literal["compare", "trend", "breakdown", "aggregate", "anomaly_scan", "unsupported", "ambiguous"]
GroupBy = Literal["campaign", "platform", "objective", "date", "week"]
FilterDim = Literal["platform", "campaign_name", "campaign_id", "objective", "status"]


class TimeSpec(BaseModel):
    preset: Literal[
        "last_7_days", "last_14_days", "last_28_days", "last_30_days", "last_90_days",
        "last_week", "this_week", "last_month", "this_month", "all_time", "custom",
    ] = "last_7_days"
    start: date | None = None
    end: date | None = None

    @model_validator(mode="after")
    def _custom(self):
        if self.preset == "custom" and (self.start is None or self.end is None):
            raise ValueError("custom time range requires start and end")
        return self


class Filter(BaseModel):
    dimension: FilterDim
    values: list[str] = Field(min_length=1, max_length=20)

    @field_validator("values")
    @classmethod
    def _clean(cls, v: list[str]) -> list[str]:
        out = []
        for s in v:
            s = str(s).strip()
            if not s or len(s) > 120:
                raise ValueError("filter values must be 1..120 characters")
            out.append(s)
        return out


class Ranking(BaseModel):
    order: Literal["asc", "desc"] = "desc"
    limit: int = Field(default=10, ge=1, le=50)


class QuestionPlan(BaseModel):
    intent: Intent
    metrics: list[MetricKey] = Field(default_factory=list, max_length=6)
    primary_metric: MetricKey | None = None
    time_range: TimeSpec = Field(default_factory=TimeSpec)
    comparison: Literal["previous_period", "same_period_last_year", "none"] = "none"
    group_by: list[GroupBy] = Field(default_factory=list, max_length=2)
    filters: list[Filter] = Field(default_factory=list, max_length=5)
    ranking: Ranking | None = None
    highlight: Literal["none", "high_cost_low_efficiency"] = "none"
    clarification_question: str | None = None
    clarification_options: list[str] = Field(default_factory=list, max_length=5)
    unsupported_reason: str | None = None
    unsafe_request: bool = False
    interpretation_notes: str = ""

    @model_validator(mode="after")
    def _consistency(self):
        if self.intent in ("compare", "trend", "breakdown", "aggregate"):
            if not self.metrics:
                raise ValueError(f"intent '{self.intent}' requires at least one metric")
            if self.primary_metric is None:
                self.primary_metric = self.metrics[0]
            if self.primary_metric not in self.metrics:
                self.metrics = [self.primary_metric, *self.metrics]
        if self.intent == "compare" and self.comparison == "none":
            self.comparison = "previous_period"
        if self.intent == "trend" and not any(g in ("date", "week") for g in self.group_by):
            self.group_by = ["date", *self.group_by][:2]
        if self.intent != "trend":
            self.group_by = [g for g in self.group_by if g not in ("date", "week")]
        if self.intent == "breakdown" and not self.group_by:
            self.group_by = ["campaign"]
        if self.intent == "ambiguous" and not self.clarification_question:
            self.clarification_question = "Could you clarify which metric and time period you mean?"
        return self

    def segment_dim(self) -> str | None:
        for g in self.group_by:
            if g in ("campaign", "platform", "objective"):
                return g
        return None


def plan_json_schema() -> dict:
    schema = QuestionPlan.model_json_schema()
    return schema


METRIC_KEYS = list(METRICS)
PRESET_KEYS = list(PRESETS)
