import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StateNotice } from "../../src/components/StateNotice/StateNotice";

describe("StateNotice", () => {
  it("uses an alert role for failure, per section 10", () => {
    render(
      <StateNotice kind="failure" title="Migration failed">
        PostgreSQL rejected revision 91ca21.
      </StateNotice>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Migration failed");
  });

  it("uses a polite status role for non-failure states", () => {
    render(<StateNotice kind="empty" title="No recommendations" />);
    expect(screen.getByRole("status")).toHaveTextContent("No recommendations");
  });

  it("renders without a body when none is given", () => {
    render(<StateNotice kind="pristine" title="No run yet" />);
    expect(screen.getByText("No run yet")).toBeInTheDocument();
  });
});
