from __future__ import annotations

import re
from pathlib import Path

from .code_parser import FileSymbols
from .models import SecurityIssue, SecurityReport

_AWS_ACCESS_KEY = re.compile(r"AKIA[0-9A-Z]{16}")
_PRIVATE_KEY_HEADER = re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")
_GENERIC_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(password|secret|api_?key|access_?key|token)\b\s*[:=]\s*"
    r"['\"]([A-Za-z0-9_\-]{8,})['\"]"
)

_PY_SUBPROCESS_SHELL_TRUE = re.compile(r"subprocess\.\w+\([^)]*shell\s*=\s*True")
_PY_OS_SYSTEM = re.compile(r"\bos\.system\s*\(")
_PY_EVAL_EXEC = re.compile(r"\b(eval|exec)\s*\(")
_JS_CHILD_PROCESS_EXEC = re.compile(r"child_process\.exec\s*\(")

_PY_PICKLE_LOADS = re.compile(r"\bpickle\.loads?\s*\(")
_PY_YAML_LOAD_BARE = re.compile(r"\byaml\.load\s*\(((?!.*Loader).)*\)")

_MAX_SCAN_BYTES = 2 * 1024 * 1024


def scan_files(files: list[FileSymbols]) -> SecurityReport:
    issues: list[SecurityIssue] = []
    for f in files:
        path = Path(f.path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        issues.extend(_scan_text(f.path, text))
    return SecurityReport(issues=issues)


def _scan_text(path: str, text: str) -> list[SecurityIssue]:
    issues: list[SecurityIssue] = []
    lines = text.splitlines()

    for i, line in enumerate(lines, start=1):
        if _AWS_ACCESS_KEY.search(line):
            issues.append(
                SecurityIssue(
                    file=path,
                    line=i,
                    kind="hardcoded_secret",
                    message="Hardcoded AWS access key detected",
                    severity="critical",
                )
            )
        elif _GENERIC_SECRET_ASSIGNMENT.search(line):
            issues.append(
                SecurityIssue(
                    file=path,
                    line=i,
                    kind="hardcoded_secret",
                    message="Possible hardcoded secret (password/token/key assigned a literal value)",
                    severity="critical",
                )
            )

        if _PY_SUBPROCESS_SHELL_TRUE.search(line):
            issues.append(
                SecurityIssue(
                    file=path,
                    line=i,
                    kind="dangerous_execution",
                    message="subprocess call with shell=True can enable command injection",
                    severity="important",
                )
            )
        if _PY_OS_SYSTEM.search(line):
            issues.append(
                SecurityIssue(
                    file=path,
                    line=i,
                    kind="dangerous_execution",
                    message="os.system() invokes a shell and can enable command injection",
                    severity="important",
                )
            )
        for match in _PY_EVAL_EXEC.finditer(line):
            issues.append(
                SecurityIssue(
                    file=path,
                    line=i,
                    kind="dangerous_execution",
                    message=f"{match.group(1)}() on untrusted input can execute arbitrary code",
                    severity="important",
                )
            )
        if _JS_CHILD_PROCESS_EXEC.search(line):
            issues.append(
                SecurityIssue(
                    file=path,
                    line=i,
                    kind="dangerous_execution",
                    message="child_process.exec() invokes a shell and can enable command injection",
                    severity="important",
                )
            )

        if _PY_PICKLE_LOADS.search(line):
            issues.append(
                SecurityIssue(
                    file=path,
                    line=i,
                    kind="unsafe_deserialization",
                    message="pickle.load(s)() can execute arbitrary code from untrusted data",
                    severity="important",
                )
            )
        if _PY_YAML_LOAD_BARE.search(line):
            issues.append(
                SecurityIssue(
                    file=path,
                    line=i,
                    kind="unsafe_deserialization",
                    message="yaml.load() without an explicit safe Loader can execute arbitrary code",
                    severity="important",
                )
            )

    if _PRIVATE_KEY_HEADER.search(text):
        line_number = next(
            (i for i, line in enumerate(lines, start=1) if _PRIVATE_KEY_HEADER.search(line)), 0
        )
        issues.append(
            SecurityIssue(
                file=path,
                line=line_number,
                kind="hardcoded_secret",
                message="Private key material embedded in source",
                severity="critical",
            )
        )

    return issues
