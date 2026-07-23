import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// mermaid (plus its per-diagram-type renderers, cytoscape, katex, etc.) is
// one of the largest dependencies in this app by a wide margin, but most
// reports render zero diagrams that need it before the user has even
// submitted a URL. A dynamic import means it's only fetched the first time a
// ```mermaid block actually needs rendering, not bundled into the initial
// page load. The import is cached (repeated calls resolve the same module),
// so this is safe to call from every MermaidBlock instance.
let mermaidModulePromise: Promise<typeof import("mermaid")> | null = null;

function loadMermaid() {
  if (!mermaidModulePromise) {
    mermaidModulePromise = import("mermaid").then((mod) => {
      mod.default.initialize({ startOnLoad: false });
      return mod;
    });
  }
  return mermaidModulePromise;
}

let mermaidIdCounter = 0;

// mermaid.render() is not safe to call concurrently — two overlapping calls
// interfere with each other's internal rendering sandbox. React StrictMode
// deliberately double-invokes effects in development (mount -> cleanup ->
// mount again), which reliably triggers exactly that overlap and left every
// diagram permanently blank (verified via a real browser-driven run: the
// render promise resolved with `cancelled` correctly false, yet the
// resulting SVG string was empty). Routing every call through one shared
// queue guarantees no two renders — from StrictMode's double-invoke, or from
// multiple diagrams on the same page — ever run at the same time.
let renderQueue: Promise<unknown> = Promise.resolve();

function MermaidBlock({ code }: { code: string }) {
  const [svg, setSvg] = useState<string>("");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    mermaidIdCounter += 1;
    const id = `atlas-mermaid-${mermaidIdCounter}`;
    const task = renderQueue.then(async () => {
      const { default: mermaid } = await loadMermaid();
      return mermaid.render(id, code);
    });
    renderQueue = task.catch(() => undefined);
    task
      .then((result) => {
        if (!cancelled) setSvg(result.svg);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [code]);

  if (failed) {
    return <pre>{code}</pre>;
  }
  // eslint-disable-next-line react/no-danger
  return <div dangerouslySetInnerHTML={{ __html: svg }} />;
}

interface CodeProps {
  className?: string;
  children?: React.ReactNode;
}

function CodeBlock({ className, children }: CodeProps) {
  const language = /language-(\w+)/.exec(className || "")?.[1];
  const codeText = String(children).replace(/\n$/, "");

  if (language === "mermaid") {
    return <MermaidBlock code={codeText} />;
  }
  return <code className={className}>{children}</code>;
}

function TableBlock({ children }: { children?: React.ReactNode }) {
  return (
    <div className="table-scroll">
      <table>{children}</table>
    </div>
  );
}

export function MarkdownReport({ markdown }: { markdown: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{ code: CodeBlock, table: TableBlock }}
    >
      {markdown}
    </ReactMarkdown>
  );
}
