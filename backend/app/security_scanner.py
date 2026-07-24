from __future__ import annotations

import re
from pathlib import Path, PurePath

from .code_parser import FileSymbols, language_for
from .models import SecurityIssue, SecurityReport

# Real-world validation (2026-07-24) found the majority of "critical"/
# "important" findings against real repos (Django, React) were dummy
# passwords and eval()/exec() calls inside test suites and compiler test
# fixtures -- exactly what those files are supposed to contain, not a real
# risk. Demoted rather than excluded: a real secret genuinely can leak into
# a test fixture, so silently dropping test-path findings would violate the
# same "surface it honestly" principle used for truncation elsewhere.
_TEST_PATH_SEGMENTS = {"test", "tests", "__tests__", "fixtures", "testdata", "spec", "specs"}
_TEST_FILENAME_RE = re.compile(r"(^test_|_test$|\.test$|\.spec$)", re.IGNORECASE)


def _looks_like_test_path(path: str) -> bool:
    p = PurePath(path)
    if any(part.lower() in _TEST_PATH_SEGMENTS for part in p.parts):
        return True
    return bool(_TEST_FILENAME_RE.search(p.stem))


def _demote_test_path_issue(issue: SecurityIssue) -> SecurityIssue:
    return issue.model_copy(
        update={
            "severity": "minor",
            "message": f"{issue.message} (in a test/fixture path — lower confidence)",
        }
    )

_AWS_ACCESS_KEY = re.compile(r"AKIA[0-9A-Z]{16}")
_PRIVATE_KEY_HEADER = re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")
_GENERIC_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(password|secret|api_?key|access_?key|token)\b\s*[:=]\s*"
    r"['\"]([A-Za-z0-9_\-]{8,})['\"]"
)

_PY_SUBPROCESS_SHELL_TRUE = re.compile(r"subprocess\.\w+\([^)]*shell\s*=\s*True")
_PY_OS_SYSTEM = re.compile(r"\bos\.system\s*\(")
# (?<!\.) excludes method calls like `x.eval(context)` -- found via
# real-world validation (2026-07-24): Django's template engine defines its
# own Operator.eval() method (django/template/smartif.py), unrelated to the
# builtin eval() that executes arbitrary strings as code. Without the
# lookbehind, any object with a method literally named eval/exec (a common
# pattern for expression/AST evaluators) reads as a dangerous builtin call.
_PY_EVAL_EXEC = re.compile(r"(?<!\.)\b(eval|exec)\s*\(")
_JS_CHILD_PROCESS_EXEC = re.compile(r"child_process\.exec\s*\(")

_PY_PICKLE_LOADS = re.compile(r"\bpickle\.loads?\s*\(")
_PY_YAML_LOAD_BARE = re.compile(r"\byaml\.load\s*\(((?!.*Loader).)*\)")

_MAX_SCAN_BYTES = 2 * 1024 * 1024

_COMMENT_PREFIX_BY_LANGUAGE = {
    "python": "#",
    "javascript": "//",
    "typescript": "//",
    "tsx": "//",
}


def _is_full_line_comment(line: str, language: str | None) -> bool:
    # Found by running Atlas on its own source: security_scanner.py's own
    # comments *about* eval()/exec()/pickle.load() (explaining what these
    # checks detect) were themselves flagged as dangerous_execution/
    # unsafe_deserialization findings, since the regexes match raw text
    # regardless of whether it's live code or prose describing it. Only
    # applied to the execution/deserialization checks below, not secret
    # detection -- a commented-out secret is still a real leaked value
    # sitting in the file (and git history), so that class of finding
    # should stay live even inside a comment.
    prefix = _COMMENT_PREFIX_BY_LANGUAGE.get(language or "")
    return bool(prefix) and line.strip().startswith(prefix)


def scan_files(files: list[FileSymbols]) -> SecurityReport:
    issues: list[SecurityIssue] = []
    for f in files:
        path = Path(f.path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        file_issues = _scan_text(f.path, text, language_for(path))
        if _looks_like_test_path(f.path):
            file_issues = [_demote_test_path_issue(i) for i in file_issues]
        issues.extend(file_issues)
    return SecurityReport(issues=issues)


def _scan_text(path: str, text: str, language: str | None = None) -> list[SecurityIssue]:
    issues: list[SecurityIssue] = []
    lines = text.splitlines()

    for i, line in enumerate(lines, start=1):
        is_comment = _is_full_line_comment(line, language)
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

        if not is_comment and _PY_SUBPROCESS_SHELL_TRUE.search(line):
            issues.append(
                SecurityIssue(
                    file=path,
                    line=i,
                    kind="dangerous_execution",
                    message="subprocess call with shell=True can enable command injection",
                    severity="important",
                )
            )
        if not is_comment and _PY_OS_SYSTEM.search(line):
            issues.append(
                SecurityIssue(
                    file=path,
                    line=i,
                    kind="dangerous_execution",
                    message="os.system() invokes a shell and can enable command injection",
                    severity="important",
                )
            )
        if not is_comment:
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
        if not is_comment and _JS_CHILD_PROCESS_EXEC.search(line):
            issues.append(
                SecurityIssue(
                    file=path,
                    line=i,
                    kind="dangerous_execution",
                    message="child_process.exec() invokes a shell and can enable command injection",
                    severity="important",
                )
            )

        if not is_comment and _PY_PICKLE_LOADS.search(line):
            issues.append(
                SecurityIssue(
                    file=path,
                    line=i,
                    kind="unsafe_deserialization",
                    message="pickle.load(s)() can execute arbitrary code from untrusted data",
                    severity="important",
                )
            )
        if not is_comment and _PY_YAML_LOAD_BARE.search(line):
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
