import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AnalysisBoundary } from "../../src/components/AnalysisBoundary/AnalysisBoundary";

describe("AnalysisBoundary", () => {
  it("hides its glyph from assistive tech, per section 4: icons never appear without nearby text", () => {
    render(<AnalysisBoundary mark="ok">Reconstructed provisional design</AnalysisBoundary>);
    const text = screen.getByText("Reconstructed provisional design");
    expect(text.querySelector("[aria-hidden='true']")).not.toBeNull();
  });

  it("renders the sentence regardless of mark", () => {
    render(<AnalysisBoundary mark="failure">Migration stopped at revision 91ca21</AnalysisBoundary>);
    expect(screen.getByText("Migration stopped at revision 91ca21")).toBeInTheDocument();
  });
});
