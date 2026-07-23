# Atlas: CommonJS `require()` Import Support

## Objective

`code_parser._extract_imports` only recognizes ES `import` statements for
JS/TS/JSX/TSX. Any repo written in CommonJS style (`require(...)`) — including
`expressjs/express`, verified during Phase 3/4/5 real-repo validation to show
`import edges: 0` despite 141 real modules — gets an empty dependency graph, a
trivially-100 architecture score, and no real "Dependency Diagram" or circular-import
detection. This is a real, previously-disclosed gap (Atlas's own "Analysis Coverage"
footer says "CommonJS ... not yet supported"). This closes it.

## Architecture

Extend `_extract_imports` in `code_parser.py` with one more JS/TS branch: walk for
`call_expression` nodes whose first child is an `identifier` with text `"require"`,
and whose `arguments` child contains a `string` node — append that string's text
(quotes stripped, same as the existing ES-import extraction) to the same
`imports: list[str]` return value. No other module changes: `graph_builder.py`'s
`_resolve_js_import`/`_build_js_path_index` already treat every entry in
`FileSymbols.imports` uniformly regardless of which JS import style produced it
(relative specifiers resolve against local files; bare specifiers are treated as
external packages and never resolved) — that logic needs no changes.

```
tree-sitter JS/TS AST
        │
        ▼
_extract_imports (extended)
    ├─ import_statement  (existing, ES modules)      → imports.append(string)
    └─ call_expression where fn == "require"  (new)  → imports.append(string)
        │
        ▼
FileSymbols.imports: list[str]        <- uniform shape, no new type
        │
        ▼
graph_builder.build_graph             <- unchanged, already resolves both the same way
```

`doc_generator.py`'s "Analysis Coverage" footer text updates from "CommonJS
(`require()`) ... not yet supported" to "supported", since it's no longer true.

## Edge cases

- `require(pathVariable)` (non-literal argument) — skipped, same posture as any
  import Atlas can't statically resolve (an ES `import(dynamicExpr)` isn't handled
  either).
- `require("foo")` with no assignment (side-effect import, e.g. `require("./polyfill");`)
  — captured; the walk finds the `call_expression` regardless of its parent
  statement shape.
- `const { a, b } = require("./foo")` (destructuring) — captured; the extraction only
  looks at the `call_expression`'s own children, not what the result is bound to.
- `require()` nested inside a function body or conditional — captured; the walk is
  unconditional over the whole tree, same as existing `import_statement` handling
  (which similarly doesn't check for top-level position).
- More than one string-like argument to `require(...)` — only the first `string`
  child of `arguments` is used; `require()` never takes more than one meaningful
  argument in real code, so this can't under- or over-count in practice.
- A local identifier named `require` that isn't Node's module loader (e.g. a
  user-defined test helper) — indistinguishable from the real thing and will produce
  a spurious import entry. Accepted: same class of heuristic limitation as the
  existing bug-fix-commit regex and naming-convention checks — not tunable further
  without real type/scope analysis, which is out of scope for a deterministic
  syntax-level pass.
- Dynamic ES `import()` expressions (e.g. `await import("./foo")`) — a different,
  separate case from CommonJS `require()`; explicitly out of scope for this change,
  same "one clearly-scoped gap at a time" discipline used throughout this project.

## Risks

Low — purely additive to `_extract_imports`'s existing JS/TS branch; no existing
field, type, or downstream consumer changes shape. The only risk is inflating
`imports` with entries from a shadowed local `require` (noted above, accepted).

## Testing

- Unit tests in `test_code_parser.py`: a JS fixture using `require()` in each of the
  five edge-case shapes above (plain assignment, destructuring, side-effect call, an
  argument that isn't a string literal, and a nested/nonâ€‘top-level call), asserting
  the resolvable ones appear in `FileSymbols.imports` and the unresolvable one
  (variable argument) does not produce a bogus entry.
- Unit test in `test_graph_builder.py`: a `require("./sibling")`-based import
  resolves to the correct local file — proving the existing resolution logic needs
  no changes, only new input reaches it.
- Real-repo validation: rerun `/analyze` against `expressjs/express` and confirm
  `import edges` goes from `0` to a real, non-zero, believable count, and that the
  quality/architecture score changes accordingly (still believable, not 0 — if it
  drops to 0, that would itself indicate the SCC-based scoring regressed, which
  would be a real problem to investigate, not just accept).
