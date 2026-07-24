# Security Policy

## Reporting a vulnerability

If you find a security issue in Atlas itself (not a finding *about* a
repo you analyzed — see below), please report it privately rather than
opening a public issue:

- Preferred: [GitHub Security Advisories](https://github.com/Justin300507/atlas/security/advisories/new)
  ("Report a vulnerability" — private until you and the maintainer agree
  to disclose).
- If that doesn't work for you, open a regular issue that says only
  "security issue, please contact me" with no details, and a maintainer
  will follow up for a private channel.

Please include: what you found, how to reproduce it, and what you think
the impact is. There's no bug bounty — this is a solo/beta project — but
real reports are read and acted on, and you'll be credited unless you'd
rather not be.

## What's already known and documented

Atlas is unauthenticated by design (a public analysis tool for public
repo URLs) and has a rate limiter with a known gap behind reverse
proxies — both are documented, not hidden, in
[`FAQ.md`](FAQ.md#known-limitations) and
[`DEPLOYMENT.md`](DEPLOYMENT.md#production-checklist). Please check
there before reporting those specific behaviors as new findings — though
if you've found a way to exploit them beyond what's documented, that's
still worth reporting.

## Reporting a false positive/negative in Atlas's own scanner

That's not a security vulnerability in Atlas — it's a bug in the
Security Scanner engine, and the most useful kind of bug report this
project gets. Open a regular issue with the `bug` label; see
[`CONTRIBUTING.md`](CONTRIBUTING.md#reporting-bugs--false-positives).

## Supported versions

Atlas is pre-1.0 and doesn't maintain multiple release branches — only
the latest commit on `main` receives fixes.
