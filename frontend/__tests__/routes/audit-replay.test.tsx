import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import type React from "react";
import Audit from "#/routes/audit";
import Tools from "#/routes/tools";
import Cost from "#/routes/cost";
import Policy from "#/routes/policy";

const renderRoute = (ui: React.ReactElement) =>
  render(<MemoryRouter>{ui}</MemoryRouter>);

describe("ForgePilot audit replay workbench", () => {
  it("renders unified audit replay events and JSONL export", () => {
    renderRoute(<Audit />);

    expect(screen.getByTestId("audit-jsonl-export")).toHaveAttribute(
      "download",
      "task-login-42-audit.jsonl",
    );
    expect(
      screen.getByTestId("audit-replay-event-task_created"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("audit-replay-event-model_response"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("audit-replay-event-command_run"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("audit-replay-event-test_result"),
    ).toBeInTheDocument();
  });

  it("renders tool registry controls", () => {
    renderRoute(<Tools />);

    expect(
      screen.getByTestId("tool-registry-item-connector.github"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("GitHub enabled")).toBeChecked();
    expect(screen.getByText("repo:read")).toBeInTheDocument();
    expect(screen.getAllByText(/mock:/)).toHaveLength(3);
  });

  it("renders budget and approval gate policy closures", () => {
    renderRoute(<Cost />);
    expect(
      screen.getByTestId("budget-policy-downgrade_model"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("budget-policy-pause + require_approval"),
    ).toBeInTheDocument();

    renderRoute(<Policy />);
    expect(
      screen.getByTestId("approval-policy-high_risk_command"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("approval-policy-sensitive_file_change"),
    ).toBeInTheDocument();
  });
});
