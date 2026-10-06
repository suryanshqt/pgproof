import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MetricRule } from "../../src/components/MetricRule/MetricRule";

describe("MetricRule", () => {
  it("renders the count and label together", () => {
    render(<MetricRule count={3} label="required correctness decisions" />);
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("required correctness decisions")).toBeInTheDocument();
  });

  it("renders a zero count rather than hiding the row", () => {
    render(<MetricRule count={0} label="verified improvements" />);
    expect(screen.getByText("0")).toBeInTheDocument();
  });
});
