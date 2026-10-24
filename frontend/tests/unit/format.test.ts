import { describe, expect, it } from "vitest";
import { changeTone, formatMetric, formatSigned, investigateQuestion, relativeTime, shortDate } from "@/lib/format";

describe("formatMetric", () => {
  it("formats by metric unit", () => {
    expect(formatMetric("spend", 1234.5)).toBe("$1,234.50");
    expect(formatMetric("conversions", 4763)).toBe("4,763");
    expect(formatMetric("conversion_rate", 0.0353)).toBe("3.53%");
    expect(formatMetric("roas", 3.3333)).toBe("3.33x");
  });
  it("uses a real minus sign and compact axis labels", () => {
    expect(formatMetric("spend", -50)).toBe("−$50.00");
    expect(formatMetric("spend", 13500, { compact: true })).toBe("$13.5K");
    expect(formatMetric("spend", 9000, { compact: true })).toBe("$9,000");
  });
  it("shows n/a for missing or undefined values instead of 0", () => {
    expect(formatMetric("cpa", null)).toBe("n/a");
    expect(formatMetric("cpa", undefined)).toBe("n/a");
    expect(formatSigned("spend", null)).toBe("n/a");
    expect(formatSigned("spend", 12)).toBe("+$12.00");
  });
});

describe("changeTone", () => {
  it("respects metric direction", () => {
    expect(changeTone(5, true)).toBe("good");
    expect(changeTone(5, false)).toBe("bad"); // CPA up is bad
    expect(changeTone(-5, false)).toBe("good");
    expect(changeTone(0.01, true)).toBe("neutral");
    expect(changeTone(null, true)).toBe("neutral");
  });
});

describe("dates and questions", () => {
  it("formats dates without timezone drift", () => {
    expect(shortDate("2026-10-18")).toBe("Oct 18");
    expect(relativeTime("2026-10-24T10:00:00Z", new Date("2026-10-24T12:30:00Z"))).toBe("2 h ago");
  });
  it("builds an investigation question with the anomaly's exact dates", () => {
    expect(
      investigateQuestion({ kind: "drop", metric_label: "Conversion rate", campaign_name: "Prospecting - Lookalike", anomaly_date: "2026-10-12", episode_end: "2026-10-15" }),
    ).toBe("Why did conversion rate change for Prospecting - Lookalike from 2026-10-12 to 2026-10-15?");
    expect(
      investigateQuestion({ kind: "missing_data", metric_label: "Data completeness", campaign_name: "X", anomaly_date: "2026-09-14", episode_end: "2026-09-20" }),
    ).toContain("spend");
  });
});
