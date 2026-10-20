import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SentenceAnswer } from "./sentences";

const citations = [
  {
    document_id: "d",
    filename: "Handbook.pdf",
    page_number: 2,
    chunk_id: "c",
    snippet:
      "Intro. Evidence is retained for 365 days after closure. Other text.",
  },
];

describe("sentence citations", () => {
  it("highlights the cited span when a marker is selected", () => {
    render(
      <SentenceAnswer
        citations={citations}
        sentences={[
          {
            text: "Evidence is kept for 365 days.",
            citations: [0],
            spans: [{ citation: 0, start: 7, end: 55 }],
            supported: true,
            missing_numbers: [],
          },
        ]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /source 1/i }));
    expect(
      screen.getByText("Evidence is retained for 365 days after closure.")
        .tagName,
    ).toBe("MARK");
    expect(screen.getByText(/Handbook.pdf, page 2/)).toBeInTheDocument();
  });

  it("flags sentences that failed the support check", () => {
    render(
      <SentenceAnswer
        citations={citations}
        sentences={[
          {
            text: "Evidence is kept for 90 days.",
            citations: [0],
            spans: [{ citation: 0, start: 7, end: 55 }],
            supported: false,
            missing_numbers: ["90"],
          },
        ]}
      />,
    );
    expect(
      screen.getByText(/1 sentence could not be matched/),
    ).toBeInTheDocument();
    expect(
      screen.getByTitle(/Not found in the cited passage: 90/),
    ).toBeInTheDocument();
  });
});
