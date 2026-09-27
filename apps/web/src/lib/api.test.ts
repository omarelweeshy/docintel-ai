import { describe, expect, it } from "vitest";
import { errorMessage, formatBytes, validateFile } from "./api";
describe("upload validation", () => {
  it("rejects unsafe types, empty and oversized files", () => {
    expect(validateFile({ name: "script.exe", size: 1 }, 100)).toContain("PDF");
    expect(validateFile({ name: "a.txt", size: 0 }, 100)).toContain("empty");
    expect(validateFile({ name: "a.pdf", size: 101 }, 100)).toContain("exceeds");
  });
  it("accepts supported extensions case-insensitively", () => {
    expect(validateFile({ name: "report.PDF", size: 100 }, 100)).toBeNull();
  });
  it("formats sizes and safe API errors", () => {
    expect(formatBytes(1048576)).toBe("1.0 MB");
    expect(errorMessage({ error: { message: "Duplicate" } }, "fallback")).toBe("Duplicate");
    expect(errorMessage({ secret: "no" }, "fallback")).toBe("fallback");
  });
});
