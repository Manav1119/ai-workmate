import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

const QUESTION = "Why did conversions fall last week?";

test.beforeEach(async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue with demo account" }).click();
  await expect(page.getByTestId("kpi-strip")).toBeVisible();
});

test("ask, validate, verify, save, reopen and export an investigation", async ({ page }) => {
  // 1-3. dashboard -> ask why conversions declined -> submit
  await expect(page.getByTestId("kpi-strip")).toContainText("Conversions");
  await page.getByLabel("Ask a question about your data").fill(QUESTION);
  await page.getByRole("button", { name: "Run analysis" }).click();
  await expect(page).toHaveURL(/\/analyst\?id=\d+/, { timeout: 30_000 });
  const id = new URL(page.url()).searchParams.get("id");
  const summary = page.getByTestId("summary");
  await expect(summary).toBeVisible();

  // ground truth for this page: the stored API record
  const api = await (await page.request.get(`/api/analyses/${id}`)).json();
  expect(api.status).toBe("succeeded");
  const conv = api.result.calculations.key_metrics.find((k: { metric: string }) => k.metric === "conversions");

  // 4. SQL was validated before execution
  await page.getByRole("button", { name: /SQL inspector/ }).click();
  await expect(page.getByTestId("sql")).toContainText("SELECT");
  const checks = page.getByTestId("validation-checks").locator("li");
  expect(await checks.count()).toBeGreaterThan(8);
  await expect(page.getByTestId("validation-checks").getByLabel("failed")).toHaveCount(0);
  expect(api.sql_validation.ok).toBe(true);

  // 5. query results were returned
  await expect(page.getByRole("tab", { name: /Query result \(\d+ rows\)/ })).toBeVisible();
  expect(api.result.row_count).toBeGreaterThan(0);

  // 6. chart and explanation agree with the results
  await expect(summary).toContainText(conv.comparison_display);
  await expect(summary).toContainText(conv.current_display);
  const chips = summary.locator("[data-fact-id]");
  expect(await chips.count()).toBeGreaterThanOrEqual(3);
  const chart = api.result.calculations.charts[0];
  const top = chart.data[0];
  const rows = api.result.rows.filter((r: { period: string; campaign_name: string }) => r.campaign_name === top.label);
  const diff =
    rows.find((r: { period: string }) => r.period === "current").conversions -
    rows.find((r: { period: string }) => r.period === "comparison").conversions;
  expect(top.contribution).toBe(diff); // chart bar = difference of query rows
  await expect(page.getByTestId("charts").locator("figure").first()).toContainText("Contribution to Conversions change");
  await expect(summary).toContainText(top.label);

  // 7. save
  await page.getByRole("button", { name: "Save investigation" }).click();
  await expect(page.getByRole("button", { name: "Saved" })).toBeVisible();

  // 8. reopen from history (stored result, clearly labelled)
  await page.getByRole("link", { name: "Investigation History" }).click();
  await page.getByLabel("Saved only").check();
  await page.getByTestId("history-list").getByRole("link", { name: new RegExp(QUESTION) }).first().click();
  await expect(page.getByText("Stored result from")).toBeVisible();
  await expect(page.getByTestId("summary")).toContainText(conv.current_display);

  // 9. export a report (Markdown and PDF)
  await page.getByRole("button", { name: "Export" }).click();
  const [md] = await Promise.all([page.waitForEvent("download"), page.getByRole("menuitem", { name: /Markdown/ }).click()]);
  const text = readFileSync(await md.path(), "utf8");
  expect(text).toContain("## Summary");
  expect(text).toContain(conv.current_display);
  await page.getByRole("button", { name: "Export" }).click();
  const [pdf] = await Promise.all([page.waitForEvent("download"), page.getByRole("menuitem", { name: "PDF" }).click()]);
  expect(readFileSync(await pdf.path()).subarray(0, 4).toString()).toBe("%PDF");
});

test("an unsafe request is rejected and nothing is executed", async ({ page }) => {
  await page.goto("/analyst");
  await page.getByLabel("Ask a question about your data").fill("DROP TABLE campaigns");
  await page.getByRole("button", { name: "Run analysis" }).click();
  await expect(page.getByText("Request rejected")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/read-only/)).toBeVisible();
});

test("anomaly status changes persist", async ({ page }) => {
  await page.goto("/anomalies");
  const table = page.getByTestId("anomaly-table");
  await expect(table).toBeVisible();
  const select = table.locator("select").first();
  const label = await select.getAttribute("id");
  const next = (await select.inputValue()) === "investigating" ? "new" : "investigating";
  await select.selectOption(next);
  await expect(page.getByText(/Marked /)).toBeVisible();
  await page.reload();
  await expect(page.locator(`#${label}`)).toHaveValue(next);
});
