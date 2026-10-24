export type User = {
  id: number;
  email: string;
  display_name: string;
  is_demo: boolean;
  reporting_timezone: string;
  anomaly_sensitivity: "conservative" | "balanced" | "sensitive";
  active_dataset_id: number | null;
};

export type Freshness = {
  last_data_date: string | null;
  first_data_date: string | null;
  today: string;
  reporting_timezone: string;
  days_since_last_data: number | null;
  status: "fresh" | "stale" | "very_stale" | "unknown";
  missing_data_episodes_last_30d: number;
  is_synthetic: boolean;
};

export type Kpi = {
  metric: string;
  label: string;
  unit: string;
  higher_is_better: boolean;
  current: number | null;
  comparison: number | null;
  abs_change: number | null;
  pct_change: number | null;
  note: string | null;
  current_display: string;
  comparison_display: string;
  abs_change_display: string;
  pct_change_display: string;
};

export type Anomaly = {
  id: number;
  metric: string;
  metric_label: string;
  campaign_id: string;
  campaign_name: string;
  platform: string;
  anomaly_date: string;
  episode_end: string;
  episode_days: number;
  kind: "drop" | "spike" | "missing_data" | "tracking_gap";
  observed_value: number | null;
  expected_value: number | null;
  observed_display: string;
  expected_display: string;
  expected_range_display: string | null;
  abs_deviation: number | null;
  pct_deviation: number | null;
  pct_deviation_display: string;
  robust_z: number | null;
  severity: "low" | "medium" | "high";
  data_quality_status: "ok" | "missing_data" | "suspected_tracking_issue" | "low_volume";
  status: "new" | "investigating" | "resolved" | "not_actionable";
  note?: string | null;
  detected_at: string;
};

export type Overview = {
  user: { display_name: string; is_demo: boolean };
  dataset: { id: number; name: string; is_synthetic: boolean; kind: string };
  freshness: Freshness;
  empty: boolean;
  anchor_date?: string;
  period?: Period;
  comparison?: Period;
  kpis: Kpi[];
  series: Array<Record<string, number | string | null>>;
  anomalies: Anomaly[];
  anomalies_open_count?: number;
  recent_investigations: Array<{ id: number; question: string; status: string; mode: string; created_at: string; saved: boolean }>;
};

export type Period = { start: string; end: string; label: string; days: number };

export type Part = { type: "text" | "fact"; value: string; fact_id?: string; label?: string };
export type Statement = { text: string; parts: Part[]; fact_ids: string[]; confidence?: string; rationale?: string | null };

export type Explanation = {
  source: "llm" | "deterministic" | "deterministic_fallback";
  summary: Statement;
  observed_facts: Statement[];
  contributions: Statement[];
  possible_explanations: Statement[];
  recommended_actions: Statement[];
  limitations: string[];
  computed_limitations: string[];
  verification: {
    numeric_tokens_checked: number;
    fact_placeholders_rendered: number;
    violations: string[];
    warnings: string[];
    passed: boolean;
    rejected_llm_drafts?: string[][];
  };
};

export type ChartSpec = {
  type: "bar" | "grouped_bar" | "line";
  title: string;
  x_key: string;
  unit_metric: string | null;
  diverging?: boolean;
  highlight_key?: string | null;
  series: Array<{ key: string; label: string; unit_metric?: string }>;
  data: Array<Record<string, unknown>>;
};

export type Fact = { id: string; label: string; value: number | null; display: string; kind: string };

export type KeyMetric = {
  metric: string;
  label: string;
  requested: boolean;
  current: number | null;
  comparison?: number | null;
  abs_change?: number | null;
  pct_change?: number | null;
  current_display: string;
  comparison_display?: string;
  abs_change_display?: string;
  pct_change_display?: string;
  higher_is_better?: boolean;
};

export type TraceStep = { step: number; name: string; status: string; duration_ms: number; detail: unknown };

export type Analysis = {
  id: number;
  question: string;
  title: string | null;
  status: "running" | "succeeded" | "failed" | "needs_clarification" | "unsupported" | "rejected";
  mode: "llm" | "demo";
  intent: string | null;
  saved: boolean;
  created_at: string;
  duration_ms: number | null;
  dataset_id: number;
  dataset_name: string | null;
  dataset_is_synthetic: boolean;
  parent_id: number | null;
  plan: Record<string, unknown> | null;
  generated_sql: string | null;
  sql_validation: {
    ok?: boolean;
    reasons?: string[];
    checks?: Array<{ check: string; passed: boolean; reason?: string }>;
    tables?: string[];
    limit_applied?: number;
    skipped?: boolean;
    reason?: string;
  } | null;
  result: {
    columns?: string[];
    rows?: Array<Record<string, unknown>>;
    row_count?: number;
    rows_stored?: number;
    query_duration_ms?: number;
    periods?: { current: Period; comparison: Period | null; anchor_date: string; notes: string[] } | null;
    calculations?: {
      intent: string;
      primary_metric?: string;
      key_metrics?: KeyMetric[];
      contributions?: Record<string, { method: string; segments: Array<Record<string, unknown>>; notes: string[] }>;
      breakdown?: Array<Record<string, unknown>>;
      highlight_rule?: string;
      trend_summary?: Array<Record<string, unknown>>;
      facts: Fact[];
      charts: ChartSpec[];
    };
    checks?: { row_count: number; warnings: string[]; crosscheck: { matched: boolean | null; note?: string } };
    anomalies?: Anomaly[];
    clarification_options?: string[];
  } | null;
  explanation: Explanation | null;
  pipeline_trace: { steps: TraceStep[]; sql_attempts: Array<Record<string, unknown>> } | null;
  error_code: string | null;
  error_message: string | null;
  llm_usage: { llm_calls: number; input_tokens: number; output_tokens: number; estimated_cost_usd: number } | null;
  data_as_of: string | null;
  current_data_as_of: string | null;
  result_is_historical: boolean;
};

export type AnalysisSummary = {
  id: number;
  question: string;
  title: string | null;
  status: Analysis["status"];
  mode: "llm" | "demo";
  intent: string | null;
  saved: boolean;
  created_at: string;
  duration_ms: number | null;
  dataset_id: number;
  parent_id: number | null;
  summary: string | null;
  error_message: string | null;
};

export type Page<T> = { items: T[]; total: number; limit: number; offset: number };

export type SystemStatus = {
  mode: "llm" | "demo";
  llm_provider: string | null;
  llm_model: string | null;
  llm_key_configured: boolean;
  query_timeout_ms: number;
  query_row_limit: number;
  sql_repair_attempts: number;
  analysis_rate_limit_per_minute: number;
  upload_max_mb: number;
  upload_max_rows: number;
  anomaly_detector: string;
  sensitivity_thresholds: Record<string, number>;
  connectors: Connector[];
};

export type Connector = { key: string; name: string; status: "available" | "planned"; description: string; auth: string };

export type Dataset = {
  id: number;
  name: string;
  kind: "synthetic_seed" | "csv_upload";
  is_synthetic: boolean;
  is_public: boolean;
  is_active: boolean;
  row_count: number;
  first_date: string | null;
  last_date: string | null;
  loaded_at: string;
  reporting_timezone: string;
  import_summary: Record<string, unknown> | null;
  freshness: Freshness;
};

export type Report = { id: number; kind: "investigation" | "briefing"; title: string; analysis_id: number | null; markdown: string; data_as_of: string | null; created_at: string };
