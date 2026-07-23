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
    localStorage.clear();
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
    expect(screen.getByRole("alert")).toHaveTextContent("Not a valid GitHub repository URL");
  });

  it("exposes the repo URL input via an accessible label, not just a placeholder", () => {
    render(<App pollIntervalMs={5} />);
    expect(screen.getByLabelText(/github repository url/i)).toBeInTheDocument();
  });

  it("ignores a rapid double-click so only one job is created", async () => {
    let resolveCreate: (value: unknown) => void;
    const createPromise = new Promise((resolve) => {
      resolveCreate = resolve;
    });
    const fetchMock = vi.fn().mockReturnValueOnce(createPromise);
    vi.stubGlobal("fetch", fetchMock);

    render(<App pollIntervalMs={5} />);
    fireEvent.change(screen.getByPlaceholderText(/github.com/i), {
      target: { value: "https://github.com/example/example" },
    });
    const button = screen.getByText("Analyze");
    fireEvent.click(button);
    fireEvent.click(button);
    fireEvent.click(button);

    resolveCreate!(jsonResponse({ job_id: "abc123" }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
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
    // The live region's actual text content must change on each stage
    // transition -- an aria-live region only announces real DOM mutations,
    // not a sibling element's className toggling.
    expect(screen.getByText(/Parsing source files \(step 2 of 7\)/)).toBeInTheDocument();
  });

  it("keeps earlier stages marked done while scanning for security issues", async () => {
    // Regression test: "scanning_security" used to be missing from STAGES,
    // so STAGES.indexOf("scanning_security") returned -1 and every prior
    // step's "done" class briefly disappeared during that stage.
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse({ job_id: "abc123" }))
      .mockReturnValue(
        jsonResponse({
          id: "abc123",
          status: "running",
          stage: "scanning_security",
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
      expect(screen.getByText("Scanning for security issues")).toHaveClass("done");
    });
    expect(screen.getByText("Analyzing code quality")).toHaveClass("done");
    expect(screen.getByText("Cloning repository")).toHaveClass("done");
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

  it("persists the active job to localStorage and clears it once done", async () => {
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
          created_at: new Date().toISOString(),
        })
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<App pollIntervalMs={5} />);
    fireEvent.change(screen.getByPlaceholderText(/github.com/i), {
      target: { value: "https://github.com/example/example" },
    });
    fireEvent.click(screen.getByText("Analyze"));

    await waitFor(() => {
      expect(JSON.parse(localStorage.getItem("atlas.activeJob")!)).toEqual({
        jobId: "abc123",
        repoUrl: "https://github.com/example/example",
      });
    });

    await waitFor(() => {
      expect(screen.getByText("Executive Summary")).toBeInTheDocument();
    });
    expect(localStorage.getItem("atlas.activeJob")).toBeNull();
  });

  it("recovers a running job from localStorage on mount", async () => {
    localStorage.setItem(
      "atlas.activeJob",
      JSON.stringify({ jobId: "abc123", repoUrl: "https://github.com/example/example" })
    );
    const fetchMock = vi.fn().mockReturnValue(
      jsonResponse({
        id: "abc123",
        status: "running",
        stage: "parsing",
        markdown: null,
        error: null,
        created_at: new Date(Date.now() - 5000).toISOString(),
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<App pollIntervalMs={5} />);

    await waitFor(() => {
      expect(screen.getByText("Parsing source files")).toHaveClass("done");
    });
    expect(fetchMock.mock.calls[0][0]).toContain("/jobs/abc123");
  });

  it("restores a finished job directly from localStorage without polling", async () => {
    localStorage.setItem(
      "atlas.activeJob",
      JSON.stringify({ jobId: "abc123", repoUrl: "https://github.com/example/example" })
    );
    const fetchMock = vi.fn().mockReturnValueOnce(
      jsonResponse({
        id: "abc123",
        status: "done",
        stage: "generating_documentation",
        markdown: "## Executive Summary\n\nhello",
        error: null,
        created_at: new Date().toISOString(),
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<App pollIntervalMs={5} />);

    await waitFor(() => {
      expect(screen.getByText("Executive Summary")).toBeInTheDocument();
    });
    expect(localStorage.getItem("atlas.activeJob")).toBeNull();
  });

  it("clears a stale job from localStorage when it no longer resolves (404)", async () => {
    localStorage.setItem(
      "atlas.activeJob",
      JSON.stringify({ jobId: "gone", repoUrl: "https://github.com/example/example" })
    );
    const fetchMock = vi.fn().mockReturnValueOnce(jsonResponse({ detail: "not found" }, false, 404));
    vi.stubGlobal("fetch", fetchMock);

    render(<App pollIntervalMs={5} />);

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/github.com/i)).toBeInTheDocument();
    });
    expect(localStorage.getItem("atlas.activeJob")).toBeNull();
  });

  it("keeps retrying (not clearing) recovery after a transient failure, unlike a real 404", async () => {
    localStorage.setItem(
      "atlas.activeJob",
      JSON.stringify({ jobId: "abc123", repoUrl: "https://github.com/example/example" })
    );
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse({ detail: "server error" }, false, 500))
      .mockReturnValue(
        jsonResponse({
          id: "abc123",
          status: "running",
          stage: "parsing",
          markdown: null,
          error: null,
          created_at: new Date().toISOString(),
        })
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<App pollIntervalMs={5} />);

    // A transient (non-404) failure must not discard the saved job or bounce to idle.
    expect(screen.queryByPlaceholderText(/github.com/i)).not.toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem("atlas.activeJob")!).jobId).toBe("abc123");

    await waitFor(() => {
      expect(screen.getByText("Parsing source files")).toHaveClass("done");
    });
  });

  it("recovers correctly against the real backend created_at format (UTC isoformat, microseconds)", async () => {
    // Python's datetime.now(timezone.utc).isoformat() looks like this -- not the
    // 3-digit-ms/"Z" shape of JS's Date.prototype.toISOString().
    const pythonStyleCreatedAt = new Date(Date.now() - 5000).toISOString().replace("Z", "123+00:00");
    localStorage.setItem(
      "atlas.activeJob",
      JSON.stringify({ jobId: "abc123", repoUrl: "https://github.com/example/example" })
    );
    const fetchMock = vi.fn().mockReturnValue(
      jsonResponse({
        id: "abc123",
        status: "running",
        stage: "parsing",
        markdown: null,
        error: null,
        created_at: pythonStyleCreatedAt,
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<App pollIntervalMs={5} />);

    await waitFor(() => {
      expect(screen.getByText(/\ds elapsed/)).toBeInTheDocument();
    });
    expect(screen.queryByText("NaNs elapsed")).not.toBeInTheDocument();
  });
});
