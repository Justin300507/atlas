import { motion, useReducedMotion } from "motion/react";

// The hero's signature visual: a dependency graph drawing itself in, then
// gently breathing -- literally what Atlas does (find the graph hidden in
// a codebase), not a generic gradient blob. Node/edge positions are fixed
// and hand-placed rather than randomized per render, so the shape reads as
// an intentional composition instead of jittering into something
// different on every load.

interface GraphNode {
  id: string;
  x: number;
  y: number;
}

interface GraphEdge {
  from: string;
  to: string;
}

const NODES: GraphNode[] = [
  { id: "a", x: 10, y: 18 },
  { id: "b", x: 28, y: 10 },
  { id: "c", x: 47, y: 22 },
  { id: "d", x: 67, y: 12 },
  { id: "e", x: 88, y: 24 },
  { id: "f", x: 19, y: 44 },
  { id: "g", x: 41, y: 51 },
  { id: "h", x: 61, y: 45 },
  { id: "i", x: 81, y: 57 },
  { id: "j", x: 13, y: 74 },
  { id: "k", x: 36, y: 82 },
  { id: "l", x: 57, y: 73 },
  { id: "m", x: 79, y: 84 },
];

const EDGES: GraphEdge[] = [
  { from: "a", to: "b" },
  { from: "b", to: "c" },
  { from: "c", to: "d" },
  { from: "d", to: "e" },
  { from: "a", to: "f" },
  { from: "b", to: "g" },
  { from: "c", to: "g" },
  { from: "d", to: "h" },
  { from: "e", to: "i" },
  { from: "f", to: "g" },
  { from: "g", to: "h" },
  { from: "h", to: "i" },
  { from: "f", to: "j" },
  { from: "g", to: "k" },
  { from: "h", to: "l" },
  { from: "i", to: "m" },
  { from: "j", to: "k" },
  { from: "k", to: "l" },
  { from: "l", to: "m" },
];

const nodeById = new Map(NODES.map((n) => [n.id, n]));

export function GraphBackground() {
  const reducedMotion = useReducedMotion();

  return (
    <svg
      className="graph-bg"
      viewBox="0 0 100 100"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
    >
      {EDGES.map((edge, i) => {
        const from = nodeById.get(edge.from)!;
        const to = nodeById.get(edge.to)!;
        return (
          <motion.line
            key={`${edge.from}-${edge.to}`}
            x1={from.x}
            y1={from.y}
            x2={to.x}
            y2={to.y}
            stroke="var(--graph-edge)"
            strokeWidth="0.25"
            initial={{ pathLength: 0, opacity: 0 }}
            animate={{ pathLength: 1, opacity: 1 }}
            transition={
              reducedMotion
                ? { duration: 0 }
                : { duration: 1.1, delay: 0.2 + i * 0.035, ease: "easeOut" }
            }
          />
        );
      })}
      {NODES.map((node, i) => (
        <motion.circle
          key={node.id}
          cx={node.x}
          r="1"
          fill="var(--accent-2)"
          initial={{ scale: 0, opacity: 0, cy: node.y }}
          animate={
            reducedMotion
              ? { scale: 1, opacity: 0.9, cy: node.y }
              : {
                  scale: [0, 1.4, 1],
                  opacity: [0, 1, 0.85],
                  cy: [node.y, node.y - 1.4, node.y],
                }
          }
          transition={
            reducedMotion
              ? { duration: 0 }
              : {
                  scale: { duration: 0.5, delay: 0.15 + i * 0.05 },
                  opacity: { duration: 0.5, delay: 0.15 + i * 0.05 },
                  cy: {
                    duration: 4 + (i % 3),
                    repeat: Infinity,
                    repeatType: "mirror",
                    ease: "easeInOut",
                    delay: 1 + i * 0.12,
                  },
                }
          }
        />
      ))}
    </svg>
  );
}
