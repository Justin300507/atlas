from __future__ import annotations

import re
from collections import defaultdict
from itertools import combinations

from .git_log_parser import Commit
from .models import CoChangePair, FileChurn, FileOwnership, GitIntelligenceReport

_TOP_N = 20
_BUG_FIX_PATTERN = re.compile(r"\b(fix|fixes|fixed|bug|hotfix|patch|bugfix)\b", re.IGNORECASE)

# combinations(k, 2) is O(k^2) -- a commit that touches an unusually large
# number of files (an initial import, a mass rename, a lockfile regen, or a
# large deliberate refactor/formatter run) is unlikely to carry meaningful
# "these files habitually change together" signal even when deliberate, but
# computing it anyway is a real combinatorial-explosion risk regardless of
# why the commit is large:
# a single commit touching ~3,000 files (not contrived -- this is exactly
# what almost every real repo's first commit looks like) produces ~4.9
# million pairs, which measured as a multi-second, multi-GB-transient-
# memory spike in this project's own load-testing benchmark. Skipping
# co-change accounting for such commits is both a performance fix and a
# correctness one -- per-file commit_count/bug_fix_count/ownership below
# are unaffected and still count every file in these commits normally.
_MAX_FILES_PER_COMMIT_FOR_COCHANGE = 100


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

        unique_paths = sorted(set(paths))
        if len(unique_paths) <= _MAX_FILES_PER_COMMIT_FOR_COCHANGE:
            for path_a, path_b in combinations(unique_paths, 2):
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
