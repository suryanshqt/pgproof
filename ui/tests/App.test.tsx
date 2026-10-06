import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { App } from "../src/app/App";

describe("App", () => {
  it("renders the fixture gallery heading", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "pgproof fixture gallery" })).toBeInTheDocument();
  });

  it("renders every evidence label from the shared-language table", () => {
    render(<App />);
    expect(screen.getAllByText("Verified in fixture").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Inconclusive").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Rejected").length).toBeGreaterThan(0);
  });
});
