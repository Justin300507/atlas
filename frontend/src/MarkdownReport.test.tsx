import { StrictMode } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";

// Regression test for the concurrency bug found via real-browser validation:
// mermaid.render() isn't safe to call concurrently, and React StrictMode
// (wrapping the real app in main.tsx) deliberately double-invokes effects in
// development, which reliably triggered exactly that overlap and left every
// diagram permanently blank. jsdom doesn't reproduce the real-browser race
// reliably (verified: the pre-fix code passes a real-render assertion under
// jsdom too), so this test verifies the actual guarantee directly — no two
// mermaid.render() calls are ever in flight at the same time — with a mocked
// render function that tracks its own concurrency.
let concurrentCalls = 0;
let maxConcurrentCalls = 0;

vi.mock("mermaid", () => ({
  default: {
    initialize: vi.fn(),
    render: vi.fn(async (id: string) => {
      concurrentCalls += 1;
      maxConcurrentCalls = Math.max(maxConcurrentCalls, concurrentCalls);
      await new Promise((resolve) => setTimeout(resolve, 20));
      concurrentCalls -= 1;
      return { svg: `<svg data-id="${id}"></svg>` };
    }),
  },
}));

const { MarkdownReport } = await import("./MarkdownReport");

describe("MarkdownReport mermaid concurrency", () => {
  it("never calls mermaid.render() concurrently, even under StrictMode's double-invoked effects", async () => {
    const markdown = "```mermaid\ngraph TD\n  a --> b\n```\n";

    const { container } = render(
      <StrictMode>
        <MarkdownReport markdown={markdown} />
      </StrictMode>
    );

    await waitFor(() => {
      expect(container.querySelector("svg")).not.toBeNull();
    });

    expect(maxConcurrentCalls).toBe(1);
  });
});
