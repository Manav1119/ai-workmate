"""CSV upload: validate -> preview + suggested column mapping -> import as a private dataset.

Checks: size, extension, UTF-8 text (no binary), row limit, header sanity, column mapping,
data types, negative values, duplicate (date, campaign) rows, missing values, impossible
values (clicks > impressions, conversions > clicks), spreadsheet formula injection in
text fields (neutralised), and timestamp -> reporting-date conversion.
"""

from __future__ import annotations

import io
import json
import re
import secrets
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
from sqlalchemy import text

from app.config import get_settings
from app.db import app_tx
from app.errors import ApiError
from app.services.datasets import refresh_stats, run_anomaly_detection

TARGETS = {
    "date": {"required": True, "type": "date", "synonyms": ["date", "day", "report_date", "reporting_date", "timestamp", "datetime", "time"]},
    "campaign_id": {"required": False, "type": "text", "synonyms": ["campaign_id", "campaignid", "campaign id", "cid"]},
    "campaign_name": {"required": False, "type": "text", "synonyms": ["campaign_name", "campaign", "campaign name", "name"]},
    "platform": {"required": False, "type": "text", "synonyms": ["platform", "channel", "network", "source"]},
    "objective": {"required": False, "type": "text", "synonyms": ["objective", "goal"]},
    "spend": {"required": True, "type": "number", "synonyms": ["spend", "cost", "amount_spent", "amount spent", "ad_spend"]},
    "impressions": {"required": True, "type": "integer", "synonyms": ["impressions", "impr", "views"]},
    "clicks": {"required": True, "type": "integer", "synonyms": ["clicks", "link_clicks", "link clicks"]},
    "conversions": {"required": True, "type": "integer", "synonyms": ["conversions", "purchases", "results", "leads", "orders"]},
    "revenue": {"required": True, "type": "number", "synonyms": ["revenue", "conversion_value", "purchase_value", "value", "sales"]},
}
FORMULA_PREFIX = re.compile(r"^[=+\-@\t\r]")
ID_RE = re.compile(r"^[A-Za-z0-9_\-:. ]{1,64}$")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(s).strip().lower()).strip("_")


def _upload_path(upload_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_\-]{16,64}", upload_id):
        raise ApiError(400, "invalid_upload_id", "Invalid upload id.")
    return Path(get_settings().upload_dir) / f"{upload_id}.csv"


def _read(raw: bytes) -> pd.DataFrame:
    s = get_settings()
    if not raw:
        raise ApiError(422, "empty_file", "The file is empty.")
    if b"\x00" in raw[:8192]:
        raise ApiError(415, "not_text", "The file looks binary. Upload a UTF-8 CSV file.")
    try:
        txt = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ApiError(415, "bad_encoding", "The file is not valid UTF-8 text.") from e
    try:
        df = pd.read_csv(io.StringIO(txt), dtype=str, keep_default_na=False, na_values=[""], skip_blank_lines=True,
                         nrows=s.upload_max_rows + 1, on_bad_lines="error")
    except Exception as e:  # noqa: BLE001
        raise ApiError(422, "unparseable_csv", f"Could not parse the CSV: {str(e).splitlines()[0][:160]}") from e
    if len(df) > s.upload_max_rows:
        raise ApiError(413, "too_many_rows", f"The file has more than {s.upload_max_rows:,} rows.")
    if df.empty:
        raise ApiError(422, "no_rows", "The CSV has a header but no data rows.")
    if len(df.columns) > 50:
        raise ApiError(422, "too_many_columns", "The CSV has more than 50 columns.")
    if len(set(_norm(c) for c in df.columns)) != len(df.columns):
        raise ApiError(422, "duplicate_columns", "The CSV has duplicate column names.")
    return df


def suggest_mapping(columns: list[str]) -> dict[str, str | None]:
    normed = {_norm(c): c for c in columns}
    out: dict[str, str | None] = {}
    for t, spec in TARGETS.items():
        out[t] = next((normed[_norm(s)] for s in spec["synonyms"] if _norm(s) in normed), None)
    return out


def _infer(series: pd.Series) -> str:
    s = series.dropna().astype(str).head(200)
    if s.empty:
        return "empty"
    if pd.to_numeric(s.str.replace(",", "", regex=False), errors="coerce").notna().all():
        return "number"
    if pd.to_datetime(s, errors="coerce", utc=True, format="mixed").notna().all():
        return "date"
    return "text"


def stage_upload(filename: str, raw: bytes) -> dict:
    s = get_settings()
    if not filename.lower().endswith(".csv"):
        raise ApiError(415, "unsupported_format", "Only .csv files are supported.")
    if len(raw) > s.upload_max_bytes:
        raise ApiError(413, "file_too_large", f"The file exceeds {s.upload_max_bytes // (1024 * 1024)} MB.")
    df = _read(raw)
    upload_id = secrets.token_urlsafe(18)
    Path(s.upload_dir).mkdir(parents=True, exist_ok=True)
    _upload_path(upload_id).write_bytes(raw)
    mapping = suggest_mapping(list(df.columns))
    return {
        "upload_id": upload_id,
        "filename": filename[:200],
        "rows": int(len(df)),
        "columns": [{"name": c, "inferred_type": _infer(df[c]), "missing": int(df[c].isna().sum()),
                     "sample": [str(v) for v in df[c].dropna().head(3)]} for c in df.columns],
        "suggested_mapping": mapping,
        "targets": {k: {"required": v["required"], "type": v["type"]} for k, v in TARGETS.items()},
        "preview": json.loads(df.head(10).to_json(orient="records")),
    }


def validate_mapped(df: pd.DataFrame, mapping: dict[str, str | None], tz: str) -> tuple[pd.DataFrame, dict]:
    errors: list[str] = []
    warnings: list[str] = []
    for t, spec in TARGETS.items():
        col = mapping.get(t)
        if spec["required"] and not col:
            errors.append(f"required field '{t}' is not mapped")
        if col and col not in df.columns:
            errors.append(f"mapped column '{col}' does not exist")
    if not mapping.get("campaign_id") and not mapping.get("campaign_name"):
        errors.append("map at least one of campaign_id or campaign_name")
    if errors:
        raise ApiError(422, "invalid_mapping", "Column mapping is invalid.", errors)

    out = pd.DataFrame()
    report = {"missing_values": {}, "invalid_values": {}, "neutralised_formula_cells": 0}
    # dates: accept YYYY-MM-DD dates or timestamps (converted into the reporting timezone)
    raw_d = df[mapping["date"]]
    parsed = pd.to_datetime(raw_d, errors="coerce", utc=False, format="mixed")
    bad_dates = int(parsed.isna().sum() - raw_d.isna().sum())
    if bad_dates:
        errors.append(f"{bad_dates} row(s) have an unparseable date")
    has_time = raw_d.dropna().astype(str).str.contains(r"\d{1,2}:\d{2}").any()
    if has_time:
        ts = pd.to_datetime(raw_d, errors="coerce", utc=True, format="mixed")
        out["date"] = ts.dt.tz_convert(ZoneInfo(tz)).dt.date
        warnings.append(f"Timestamps were converted to calendar dates in the reporting timezone ({tz}); naive times are treated as UTC.")
    else:
        out["date"] = parsed.dt.date
    report["missing_values"]["date"] = int(raw_d.isna().sum())

    for t in ("spend", "impressions", "clicks", "conversions", "revenue"):
        col = df[mapping[t]].astype("string").str.replace(",", "", regex=False).str.replace("$", "", regex=False).str.strip()
        num = pd.to_numeric(col, errors="coerce")
        missing = int(col.isna().sum())
        invalid = int(num.isna().sum()) - missing
        report["missing_values"][t] = missing
        if invalid:
            report["invalid_values"][t] = invalid
            errors.append(f"{invalid} non-numeric value(s) in '{mapping[t]}' ({t})")
        if (num < 0).any():
            errors.append(f"{int((num < 0).sum())} negative value(s) in {t}")
        if TARGETS[t]["type"] == "integer" and (num.dropna() % 1 != 0).any():
            errors.append(f"{t} must be whole numbers")
        if missing:
            warnings.append(f"{missing} missing value(s) in {t} were imported as 0.")
        out[t] = num.fillna(0)

    def text_col(t: str, default: str | None) -> pd.Series:
        col = mapping.get(t)
        if not col:
            return pd.Series([default] * len(df), index=df.index, dtype="object")
        s = df[col].astype("string").str.strip()
        mask = s.fillna("").str.match(FORMULA_PREFIX)
        report["neutralised_formula_cells"] += int(mask.sum())
        s = s.where(~mask, "'" + s.fillna(""))
        return s.fillna(default if default is not None else "").str.slice(0, 200)

    out["campaign_name"] = text_col("campaign_name", None)
    if mapping.get("campaign_id"):
        ids = df[mapping["campaign_id"]].astype("string").str.strip()
        bad = ids.fillna("").map(lambda v: not ID_RE.match(v))
        if bad.any():
            errors.append(f"{int(bad.sum())} campaign_id value(s) are empty or contain unsupported characters")
        out["campaign_id"] = ids
    else:
        names = out["campaign_name"].fillna("")
        if (names == "").any():
            errors.append("campaign_name has empty values and no campaign_id column is mapped")
        codes = {n: f"CSV{i + 1:04d}" for i, n in enumerate(sorted(set(names)))}
        out["campaign_id"] = names.map(codes)
    out.loc[out["campaign_name"].fillna("") == "", "campaign_name"] = out["campaign_id"]
    out["platform"] = text_col("platform", "Unknown")
    out["objective"] = text_col("objective", "Unknown")

    if not errors:
        imp = out["clicks"] > out["impressions"]
        if imp.any():
            errors.append(f"{int(imp.sum())} row(s) have more clicks than impressions")
        conv = out["conversions"] > out["clicks"]
        if conv.any():
            warnings.append(f"{int(conv.sum())} row(s) have more conversions than clicks (possible view-through or "
                            "attribution differences); imported as-is.")
    dup = out.duplicated(subset=["date", "campaign_id"], keep=False)
    report["duplicate_rows"] = int(out.duplicated(subset=["date", "campaign_id"]).sum())
    if dup.any():
        errors.append(f"{report['duplicate_rows']} duplicate (date, campaign) row(s): the grain must be one row per "
                      "campaign per day. Aggregate or remove duplicates and re-upload.")
    attrs = out.groupby("campaign_id")[["campaign_name", "platform"]].nunique()
    if (attrs > 1).any().any():
        warnings.append("Some campaign_ids have more than one name or platform; the most recent value is used.")
    if report["neutralised_formula_cells"]:
        warnings.append(f"{report['neutralised_formula_cells']} text cell(s) started with =, +, -, @ and were prefixed "
                        "with ' to prevent spreadsheet formula injection on export.")
    if errors:
        raise ApiError(422, "validation_failed", "The file did not pass validation.", errors)
    report["warnings"] = warnings
    return out, report


def import_upload(upload_id: str, mapping: dict, dataset_name: str, tz: str, user_id: int) -> dict:
    path = _upload_path(upload_id)
    if not path.exists():
        raise ApiError(404, "upload_not_found", "Upload not found or expired. Upload the file again.")
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ApiError(422, "invalid_timezone", f"Unknown timezone '{tz}'.") from e
    df = _read(path.read_bytes())
    data, report = validate_mapped(df, mapping, tz)
    camps = (data.sort_values("date").groupby("campaign_id")
             .agg(campaign_name=("campaign_name", "last"), platform=("platform", "last"),
                  objective=("objective", "last"), start_date=("date", "min")).reset_index())
    with app_tx() as c:
        ds = c.execute(
            text("INSERT INTO app.datasets (owner_user_id, name, kind, is_synthetic, reporting_timezone)"
                 " VALUES (:u, :n, 'csv_upload', FALSE, :tz) RETURNING id"),
            {"u": user_id, "n": dataset_name[:120] or "Uploaded CSV", "tz": tz},
        ).scalar()
        c.execute(
            text("INSERT INTO analytics.campaigns (dataset_id, campaign_id, campaign_name, platform, objective, start_date,"
                 " status) VALUES (:d, :campaign_id, :campaign_name, :platform, :objective, :start_date, 'active')"),
            [dict(r, d=ds) for r in camps.to_dict(orient="records")],
        )
        recs = data[["date", "campaign_id", "spend", "impressions", "clicks", "conversions", "revenue"]].copy()
        for col in ("impressions", "clicks", "conversions"):
            recs[col] = recs[col].astype("int64")
        c.execute(
            text("INSERT INTO analytics.campaign_daily_metrics (dataset_id, date, campaign_id, spend, impressions, clicks,"
                 " conversions, revenue) VALUES (:d, :date, :campaign_id, :spend, :impressions, :clicks, :conversions,"
                 " :revenue)"),
            [dict(r, d=ds) for r in recs.to_dict(orient="records")],
        )
    stats = refresh_stats(ds)
    n_anom = run_anomaly_detection(ds)
    summary = {
        "dataset_id": ds, "rows_imported": int(len(data)), "campaigns": int(len(camps)),
        "date_range": [str(stats["first"]), str(stats["last"])], "anomalies_detected": n_anom,
        "missing_values": report["missing_values"], "duplicate_rows": report["duplicate_rows"],
        "warnings": report["warnings"], "reporting_timezone": tz,
        "imported_at": datetime.utcnow().isoformat() + "Z",
    }
    with app_tx() as c:
        c.execute(text("UPDATE app.datasets SET import_summary = CAST(:s AS JSONB) WHERE id = :d"),
                  {"s": json.dumps(summary), "d": ds})
    path.unlink(missing_ok=True)
    return summary
