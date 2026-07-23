import "@testing-library/jest-dom/vitest";

// jsdom doesn't implement SVG layout APIs (getBBox), which mermaid needs
// during rendering even in headless/off-screen mode. This is the standard
// polyfill used to test mermaid/d3-based rendering under jsdom.
if (typeof SVGElement !== "undefined" && !("getBBox" in SVGElement.prototype)) {
  // @ts-expect-error jsdom doesn't implement SVG layout
  SVGElement.prototype.getBBox = () => ({ x: 0, y: 0, width: 100, height: 20, top: 0, right: 0, bottom: 0, left: 0 });
}
