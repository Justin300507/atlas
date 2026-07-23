import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "./App";

function jsonResponse(body: unknown, ok = true, status = 200) {
  return Promise.resolve({
    ok,
    status,
    json: () => Promise.resolve(body),
  });
}

describe("App", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows an inline error when submission fails", async () => {
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse({ detail: "Not a valid GitHub repository URL" }, false, 400));
    vi.stubGlobal("fetch", fetchMock);

    render(<App pollIntervalMs={5} />);
    fireEvent.change(screen.getByPlaceholderText(/github.com/i), {
      target: { value: "not-a-url" },
    });
    fireEvent.click(screen.getByText("Analyze"));

    await waitFor(() => {
      expect(screen.getByText("Not a valid GitHub repository URL")).toBeInTheDocument();
    });
  });

  it("submits a URL and shows the running state", async () => {
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse({ job_id: "abc123" }))
      .mockReturnValue(
        jsonResponse({
          id: "abc123",
          status: "running",
          stage: "parsing",
          markdown: null,
          error: null,
        })
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<App pollIntervalMs={5} />);
    fireEvent.change(screen.getByPlaceholderText(/github.com/i), {
      target: { value: "https://github.com/example/example" },
    });
    fireEvent.click(screen.getByText("Analyze"));

    await waitFor(() => {
      expect(screen.getByText("Parsing source files")).toHaveClass("done");
    });
  });

  it("renders the report once the job is done", async () => {
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse({ job_id: "abc123" }))
      .mockReturnValue(
        jsonResponse({
          id: "abc123",
          status: "done",
          stage: "generating_documentation",
          markdown: "## Executive Summary\n\nhello",
          error: null,
        })
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<App pollIntervalMs={5} />);
    fireEvent.change(screen.getByPlaceholderText(/github.com/i), {
      target: { value: "https://github.com/example/example" },
    });
    fireEvent.click(screen.getByText("Analyze"));

    await waitFor(
      () => {
        expect(screen.getByText("Executive Summary")).toBeInTheDocument();
      },
      { timeout: 2000 }
    );
  });

  it("shows an error state when the job fails", async () => {
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse({ job_id: "abc123" }))
      .mockReturnValue(
        jsonResponse({
          id: "abc123",
          status: "error",
          stage: "cloning_structure",
          markdown: null,
          error: "Repository clone timed out",
        })
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<App pollIntervalMs={5} />);
    fireEvent.change(screen.getByPlaceholderText(/github.com/i), {
      target: { value: "https://github.com/example/example" },
    });
    fireEvent.click(screen.getByText("Analyze"));

    await waitFor(
      () => {
        expect(screen.getByText("Repository clone timed out")).toBeInTheDocument();
      },
      { timeout: 2000 }
    );

    fireEvent.click(screen.getByText("Try Again"));
    expect(screen.getByPlaceholderText(/github.com/i)).toBeInTheDocument();
  });
});
