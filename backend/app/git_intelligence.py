from __future__ import annotations

import re
from collections import defaultdict
from itertools import combinations

from .git_log_parser import Commit
from .models import CoChangePair, FileChurn, FileOwnership, GitIntelligenceReport

_TOP_N = 20
_BUG_FIX_PATTERN = re.compile(r"\b(fix|fixes|fixed|bug|hotfix|patch|bugfix)\b", re.IGNORECASE)


def analyze_git_history(commits: list[Commit], history_truncated: bool) -> GitIntelligenceReport:
    commit_counts: dict[str, int] = defaultdict(int)
    bug_fix_counts: dict[str, int] = defaultdict(int)
    author_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    co_change_counts: dict[tuple[str, str], int] = defaultdict(int)

    for commit in commits:
        is_bug_fix = bool(_BUG_FIX_PATTERN.search(commit.message))
        paths = [f.path for f in commit.files]

        for path in paths:
            commit_counts[path] += 1
            if is_bug_fix:
                bug_fix_counts[path] += 1
            author_counts[path][commit.author_email] += 1

        for path_a, path_b in combinations(sorted(set(paths)), 2):
            co_change_counts[(path_a, path_b)] += 1

    churn = sorted(
        (
            FileChurn(file=path, commit_count=count, bug_fix_count=bug_fix_counts.get(path, 0))
            for path, count in commit_counts.items()
        ),
        key=lambda c: c.commit_count,
        reverse=True,
    )[:_TOP_N]

    ownership = sorted(
        (
            FileOwnership(
                file=path,
                top_author=max(authors.items(), key=lambda kv: kv[1])[0],
                top_author_commits=max(authors.values()),
                total_commits=sum(authors.values()),
                ownership_ratio=max(authors.values()) / sum(authors.values()),
            )
            for path, authors in author_counts.items()
        ),
        key=lambda o: o.total_commits,
        reverse=True,
    )[:_TOP_N]

    co_changes = sorted(
        (
            CoChangePair(file_a=a, file_b=b, co_change_count=count)
            for (a, b), count in co_change_counts.items()
        ),
        key=lambda p: p.co_change_count,
        reverse=True,
    )[:_TOP_N]

    return GitIntelligenceReport(
        commits_analyzed=len(commits),
        history_truncated=history_truncated,
        churn=churn,
        ownership=ownership,
        co_changes=co_changes,
    )
