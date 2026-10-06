import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EvidenceLabel } from "../../src/components/EvidenceLabel/EvidenceLabel";

describe("EvidenceLabel", () => {
  it("never shortens 'Verified in fixture' to 'Verified'", () => {
    render(<EvidenceLabel kind="verified_in_fixture" />);
    expect(screen.getByText("Verified in fixture")).toBeInTheDocument();
  });

  it("renders the exact shared-language label for each kind", () => {
    render(<EvidenceLabel kind="user_confirmed" />);
    expect(screen.getByText("User-confirmed")).toBeInTheDocument();
  });
});
