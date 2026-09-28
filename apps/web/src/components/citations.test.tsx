import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Citations } from "./citations";
describe("source evidence", () => {
  it("renders filename, true page number, snippet and scoped download", () => {
    render(
      <Citations
        workspaceId="workspace-1"
        citations={[
          {
            document_id: "doc-1",
            filename: "Policy.pdf",
            page_number: 4,
            chunk_id: "chunk-1",
            snippet: "Keep records for 30 days.",
          },
        ]}
      />,
    );
    expect(screen.getByText("Page 4")).toBeInTheDocument();
    expect(screen.getByText("Keep records for 30 days.")).toBeInTheDocument();
    expect(screen.getByRole("link", { hidden: true })).toHaveAttribute(
      "href",
      expect.stringContaining("workspace_id=workspace-1"),
    );
  });
  it("does not invent a page for unpaginated formats", () => {
    render(
      <Citations
        workspaceId="w"
        citations={[
          {
            document_id: "d",
            filename: "Notes.txt",
            page_number: null,
            chunk_id: "c",
            snippet: "Notes",
          },
        ]}
      />,
    );
    expect(screen.getByText("Passage")).toBeInTheDocument();
  });
});
