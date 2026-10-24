import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { FactText } from "@/components/fact-text";
import { Markdown } from "@/components/markdown";
import { TooltipProvider } from "@/components/ui/tooltip";

describe("FactText", () => {
  it("renders each number as a fact chip linked to its fact id", () => {
    render(
      <TooltipProvider>
        <p>
          <FactText
            text="Conversions fell 3.1% to 4,763."
            parts={[
              { type: "text", value: "Conversions fell " },
              { type: "fact", value: "3.1%", fact_id: "total.conversions.pct_change", label: "% change" },
              { type: "text", value: " to " },
              { type: "fact", value: "4,763", fact_id: "total.conversions.current", label: "Conversions" },
              { type: "text", value: "." },
            ]}
          />
        </p>
      </TooltipProvider>,
    );
    const chips = document.querySelectorAll("[data-fact-id]");
    expect(chips).toHaveLength(2);
    expect(chips[0]).toHaveAttribute("data-fact-id", "total.conversions.pct_change");
    expect(chips[0]).toHaveAttribute("tabindex", "0");
    expect(screen.getByText("4,763")).toBeInTheDocument();
  });
  it("falls back to plain text without parts", () => {
    render(<FactText text="No numbers here" />);
    expect(screen.getByText("No numbers here")).toBeInTheDocument();
  });
});

describe("Markdown", () => {
  it("renders headings, lists and tables without injecting HTML", () => {
    const { container } = render(
      <Markdown source={"# Title\n\n- one **bold**\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n<script>alert(1)</script>"} />,
    );
    expect(screen.getByRole("heading", { name: "Title" })).toBeInTheDocument();
    expect(screen.getByText("bold").tagName).toBe("STRONG");
    expect(container.querySelectorAll("td")).toHaveLength(2);
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByText("<script>alert(1)</script>")).toBeInTheDocument();
  });
});
