import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import mermaid from "mermaid";

mermaid.initialize({ startOnLoad: false });

let mermaidIdCounter = 0;

function MermaidBlock({ code }: { code: string }) {
  const [svg, setSvg] = useState<string>("");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    mermaidIdCounter += 1;
    const id = `atlas-mermaid-${mermaidIdCounter}`;
    mermaid
      .render(id, code)
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

export function MarkdownReport({ markdown }: { markdown: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ code: CodeBlock }}>
      {markdown}
    </ReactMarkdown>
  );
}
