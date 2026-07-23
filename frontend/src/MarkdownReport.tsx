import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import mermaid from "mermaid";

mermaid.initialize({ startOnLoad: false });

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
    const task = renderQueue.then(() => mermaid.render(id, code));
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
