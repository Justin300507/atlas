## Executive Summary

- Backend: Django
- Frontend: Not detected
- Database: Not detected
- Auth: Not detected
- Deployment: Not detected
- Architecture: Not detected
- Files analyzed: 3038
- Overall quality score: 56/100 (maintainability 94, architecture 18)
- Commits analyzed: 500 (history truncated)

## Architecture Overview

- Modules: 3038
- Import edges: 8787
- Routes: 0

Most depended-upon modules:
- __init__.py (795 importers)
- __init__.py (777 importers)
- exceptions.py (349 importers)
- __init__.py (247 importers)
- __init__.py (219 importers)
- __init__.py (219 importers)
- utils.py (212 importers)
- functional.py (162 importers)
- __init__.py (160 importers)
- __init__.py (155 importers)

## Directory Guide

| Directory | Files |
|---|---|
| tests | 2017 |
| django | 994 |
| js_tests | 11 |
| scripts | 11 |
| docs | 4 |
| . | 1 |

## API Reference

No routes detected.

## Dependency Diagram

```mermaid
graph TD
    n16["__init__.py"] --> n31["version.py"]
    n16["__init__.py"] --> n13["__init__.py"]
    n16["__init__.py"] --> n3["__init__.py"]
    n16["__init__.py"] --> n6["__init__.py"]
    n3["__init__.py"] --> n2["exceptions.py"]
    n3["__init__.py"] --> n21["deprecation.py"]
    n3["__init__.py"] --> n8["functional.py"]
    n3["__init__.py"] --> n6["__init__.py"]
    n1["__init__.py"] --> n14["__init__.py"]
    n20["__init__.py"] --> n2["exceptions.py"]
    n23["defaultfilters.py"] --> n11["__init__.py"]
    n23["defaultfilters.py"] --> n35["encoding.py"]
    n23["defaultfilters.py"] --> n36["html.py"]
    n23["defaultfilters.py"] --> n18["safestring.py"]
    n23["defaultfilters.py"] --> n9["__init__.py"]
    n5["utils.py"] --> n13["__init__.py"]
    n5["utils.py"] --> n3["__init__.py"]
    n5["utils.py"] --> n14["__init__.py"]
    n5["utils.py"] --> n2["exceptions.py"]
    n5["utils.py"] --> n1["__init__.py"]
    n5["utils.py"] --> n10["__init__.py"]
    n5["utils.py"] --> n6["__init__.py"]
    n5["utils.py"] --> n9["__init__.py"]
    n5["utils.py"] --> n31["version.py"]
    n5["utils.py"] --> n0["__init__.py"]
    n0["__init__.py"] --> n5["utils.py"]
    n35["encoding.py"] --> n8["functional.py"]
    n36["html.py"] --> n3["__init__.py"]
    n36["html.py"] --> n2["exceptions.py"]
    n36["html.py"] --> n21["deprecation.py"]
    n36["html.py"] --> n8["functional.py"]
    n36["html.py"] --> n33["regex_helper.py"]
    n36["html.py"] --> n18["safestring.py"]
    n38["module_loading.py"] --> n13["__init__.py"]
    n33["regex_helper.py"] --> n8["functional.py"]
    n18["safestring.py"] --> n8["functional.py"]
    n31["version.py"] --> n33["regex_helper.py"]
    n31["version.py"] --> n16["__init__.py"]
    n28["options.py"] --> n16["__init__.py"]
    n28["options.py"] --> n13["__init__.py"]
    n28["options.py"] --> n3["__init__.py"]
    n28["options.py"] --> n25["__init__.py"]
    n28["options.py"] --> n27["__init__.py"]
    n28["options.py"] --> n2["exceptions.py"]
    n28["options.py"] --> n1["__init__.py"]
    n28["options.py"] --> n7["__init__.py"]
    n28["options.py"] --> n6["__init__.py"]
    n28["options.py"] --> n21["deprecation.py"]
    n28["options.py"] --> n36["html.py"]
    n28["options.py"] --> n18["safestring.py"]
    n28["options.py"] --> n9["__init__.py"]
    n28["options.py"] --> n22["models.py"]
    n15["models.py"] --> n13["__init__.py"]
    n15["models.py"] --> n25["__init__.py"]
    n15["models.py"] --> n22["models.py"]
    n15["models.py"] --> n2["exceptions.py"]
    n15["models.py"] --> n1["__init__.py"]
    n15["models.py"] --> n11["__init__.py"]
    n15["models.py"] --> n9["__init__.py"]
    n27["__init__.py"] --> n13["__init__.py"]
    n27["__init__.py"] --> n3["__init__.py"]
    n27["__init__.py"] --> n2["exceptions.py"]
    n27["__init__.py"] --> n38["module_loading.py"]
    n27["__init__.py"] --> n15["models.py"]
    n32["fields.py"] --> n22["models.py"]
    n32["fields.py"] --> n14["__init__.py"]
    n32["fields.py"] --> n2["exceptions.py"]
    n32["fields.py"] --> n1["__init__.py"]
    n32["fields.py"] --> n4["__init__.py"]
    n32["fields.py"] --> n37["__init__.py"]
    n32["fields.py"] --> n8["functional.py"]
    n22["models.py"] --> n13["__init__.py"]
    n22["models.py"] --> n1["__init__.py"]
    n22["models.py"] --> n4["__init__.py"]
    n22["models.py"] --> n9["__init__.py"]
    n19["base.py"] --> n16["__init__.py"]
    n19["base.py"] --> n14["__init__.py"]
    n19["base.py"] --> n2["exceptions.py"]
    n19["base.py"] --> n1["__init__.py"]
    n19["base.py"] --> n31["version.py"]
    n19["base.py"] --> n11["__init__.py"]
    n19["base.py"] --> n13["__init__.py"]
    n30["__init__.py"] --> n16["__init__.py"]
    n30["__init__.py"] --> n13["__init__.py"]
    n30["__init__.py"] --> n3["__init__.py"]
    n30["__init__.py"] --> n2["exceptions.py"]
    n30["__init__.py"] --> n19["base.py"]
    n30["__init__.py"] --> n11["__init__.py"]
    n24["expressions.py"] --> n2["exceptions.py"]
    n24["expressions.py"] --> n1["__init__.py"]
    n24["expressions.py"] --> n4["__init__.py"]
    n24["expressions.py"] --> n8["functional.py"]
    n24["expressions.py"] --> n12["__init__.py"]
    n39["lookups.py"] --> n2["exceptions.py"]
    n39["lookups.py"] --> n24["expressions.py"]
    n39["lookups.py"] --> n37["__init__.py"]
    n39["lookups.py"] --> n8["functional.py"]
    n39["lookups.py"] --> n12["__init__.py"]
    n4["__init__.py"] --> n2["exceptions.py"]
    n4["__init__.py"] --> n24["expressions.py"]
    n4["__init__.py"] --> n37["__init__.py"]
    n4["__init__.py"] --> n39["lookups.py"]
    n37["__init__.py"] --> n16["__init__.py"]
    n37["__init__.py"] --> n13["__init__.py"]
    n37["__init__.py"] --> n3["__init__.py"]
    n37["__init__.py"] --> n14["__init__.py"]
    n37["__init__.py"] --> n1["__init__.py"]
    n37["__init__.py"] --> n11["__init__.py"]
    n37["__init__.py"] --> n21["deprecation.py"]
    n37["__init__.py"] --> n8["functional.py"]
    n37["__init__.py"] --> n9["__init__.py"]
    n37["__init__.py"] --> n24["expressions.py"]
    n37["__init__.py"] --> n12["__init__.py"]
    n9["__init__.py"] --> n8["functional.py"]
    n9["__init__.py"] --> n33["regex_helper.py"]
    n9["__init__.py"] --> n3["__init__.py"]
    n29["models.py"] --> n1["__init__.py"]
    n17["utils.py"] --> n5["utils.py"]
    n17["utils.py"] --> n18["safestring.py"]
```

_(40 of 3038 modules shown, capped for readability)_

## Risk Areas

- **critical** `django/__init__.py:0` circular_import: Circular dependency cluster of 141 modules: django/__init__.py, django/apps/__init__.py, django/apps/config.py, django/apps/registry.py, django/conf/__init__.py, django/core/cache/__init__.py, django/core/cache/backends/base.py, django/core/cache/backends/filebased.py, django/core/checks/__init__.py, django/core/checks/async_checks.py, django/core/checks/caches.py, django/core/checks/commands.py, django/core/checks/compatibility/django_4_0.py, django/core/checks/database.py, django/core/checks/files.py, django/core/checks/mail.py, django/core/checks/messages.py, django/core/checks/model_checks.py, django/core/checks/registry.py, django/core/checks/security/base.py, and 121 more
- **critical** `django/contrib/admin/__init__.py:0` circular_import: Circular dependency cluster of 12 modules: django/contrib/admin/__init__.py, django/contrib/admin/checks.py, django/contrib/admin/decorators.py, django/contrib/admin/filters.py, django/contrib/admin/models.py, django/contrib/admin/options.py, django/contrib/admin/sites.py, django/contrib/admin/templatetags/admin_list.py, django/contrib/admin/templatetags/admin_urls.py, django/contrib/admin/utils.py, django/contrib/admin/views/main.py, django/contrib/admin/widgets.py
- **critical** `django/contrib/gis/geos/__init__.py:0` circular_import: Circular dependency cluster of 11 modules: django/contrib/gis/geos/__init__.py, django/contrib/gis/geos/collections.py, django/contrib/gis/geos/coordseq.py, django/contrib/gis/geos/factory.py, django/contrib/gis/geos/geometry.py, django/contrib/gis/geos/io.py, django/contrib/gis/geos/linestring.py, django/contrib/gis/geos/point.py, django/contrib/gis/geos/polygon.py, django/contrib/gis/geos/prepared.py, django/contrib/gis/geos/prototypes/io.py
- **important** `docs/lint.py:55` high_complexity: Function 'check_line_too_long_django' has branch count 15 (threshold 10)
- **important** `scripts/prepare_commit_msg.py:31` high_complexity: Function 'process_commit_message' has branch count 13 (threshold 10)
- **important** `django/apps/config.py:100` high_complexity: Function 'create' has branch count 15 (threshold 10)
- **important** `django/conf/__init__.py:241` high_complexity: Function '__init__' has branch count 12 (threshold 10)
- **important** `django/db/transaction.py:237` high_complexity: Function '__exit__' has branch count 18 (threshold 10)
- **important** `django/dispatch/dispatcher.py:476` high_complexity: Function '_live_receivers' has branch count 12 (threshold 10)
- **important** `django/forms/fields.py:1099` high_complexity: Function 'clean' has branch count 13 (threshold 10)
- **important** `django/forms/fields.py:1202` high_complexity: Function 'set_choices' has branch count 14 (threshold 10)
- **important** `django/forms/models.py:141` high_complexity: Function 'fields_for_model' has branch count 17 (threshold 10)
- **important** `django/forms/models.py:589` high_complexity: Function 'modelform_factory' has branch count 11 (threshold 10)
- **important** `django/forms/models.py:825` high_complexity: Function 'validate_unique' has branch count 15 (threshold 10)
- **important** `django/http/multipartparser.py:133` high_complexity: Function '_parse' has branch count 33 (threshold 10)
- **important** `django/http/response.py:223` high_complexity: Function 'set_cookie' has branch count 13 (threshold 10)
- **important** `django/middleware/cache.py:88` high_complexity: Function 'process_response' has branch count 11 (threshold 10)
- **important** `django/template/base.py:530` high_complexity: Function 'parse' has branch count 13 (threshold 10)
- **important** `django/template/base.py:803` high_complexity: Function 'resolve' has branch count 11 (threshold 10)
- **important** `django/template/base.py:965` high_complexity: Function '_resolve_lookup' has branch count 15 (threshold 10)

_...and 2561 additional findings._

## Security Findings

- **important** `scripts/manage_translations.py:403` dangerous_execution: eval() on untrusted input can execute arbitrary code
- **important** `django/template/defaulttags.py:917` dangerous_execution: eval() on untrusted input can execute arbitrary code
- **important** `django/template/smartif.py:59` dangerous_execution: eval() on untrusted input can execute arbitrary code
- **important** `django/template/smartif.py:86` dangerous_execution: eval() on untrusted input can execute arbitrary code
- **important** `django/template/smartif.py:144` dangerous_execution: eval() on untrusted input can execute arbitrary code
- **important** `django/contrib/admin/static/admin/js/vendor/xregexp/xregexp.js:3197` dangerous_execution: exec() on untrusted input can execute arbitrary code
- **important** `django/contrib/admin/static/admin/js/vendor/xregexp/xregexp.js:3657` dangerous_execution: exec() on untrusted input can execute arbitrary code
- **important** `django/contrib/admin/static/admin/js/vendor/xregexp/xregexp.js:4003` dangerous_execution: exec() on untrusted input can execute arbitrary code
- **important** `django/contrib/admin/static/admin/js/vendor/xregexp/xregexp.js:4202` dangerous_execution: exec() on untrusted input can execute arbitrary code
- **important** `django/core/cache/backends/db.py:102` unsafe_deserialization: pickle.load(s)() can execute arbitrary code from untrusted data
- **important** `django/core/cache/backends/filebased.py:38` unsafe_deserialization: pickle.load(s)() can execute arbitrary code from untrusted data
- **important** `django/core/cache/backends/filebased.py:71` unsafe_deserialization: pickle.load(s)() can execute arbitrary code from untrusted data
- **important** `django/core/cache/backends/filebased.py:154` unsafe_deserialization: pickle.load(s)() can execute arbitrary code from untrusted data
- **important** `django/core/cache/backends/locmem.py:43` unsafe_deserialization: pickle.load(s)() can execute arbitrary code from untrusted data
- **important** `django/core/cache/backends/locmem.py:73` unsafe_deserialization: pickle.load(s)() can execute arbitrary code from untrusted data
- **important** `django/core/cache/backends/redis.py:29` unsafe_deserialization: pickle.load(s)() can execute arbitrary code from untrusted data
- **important** `django/core/management/commands/shell.py:89` dangerous_execution: exec() on untrusted input can execute arbitrary code
- **important** `django/core/management/commands/shell.py:262` dangerous_execution: exec() on untrusted input can execute arbitrary code
- **important** `django/core/management/commands/shell.py:272` dangerous_execution: exec() on untrusted input can execute arbitrary code
- **important** `django/db/migrations/questioner.py:168` dangerous_execution: eval() on untrusted input can execute arbitrary code

_...and 150 additional findings._

## Recent High-Churn Components

Analyzed 500 commits (history truncated — repo has more commits than analyzed).

| File | Commits | Bug fixes |
|---|---|---|
| docs/releases/6.1.txt | 53 | 38 |
| tests/admin_views/tests.py | 20 | 15 |
| AUTHORS | 18 | 18 |
| docs/internals/deprecation.txt | 18 | 11 |
| docs/topics/email.txt | 18 | 7 |
| docs/releases/6.2.txt | 17 | 13 |
| django/contrib/admin/options.py | 17 | 12 |
| docs/ref/settings.txt | 16 | 6 |
| tests/cache/tests.py | 14 | 11 |
| docs/releases/index.txt | 11 | 0 |

## Analysis Coverage

**Supported:**
- Python imports (absolute and relative)
- ES Module imports (JS/TS `import` syntax)
- CommonJS imports (JS/TS `require()` calls)
- Dynamic ES imports (JS/TS `import(...)` expressions)
- Git history (commit churn, ownership, co-change)
- Repository structure and stack detection
- Security scanning for hardcoded secrets, dangerous shell/eval execution, and unsafe deserialization

**Limitations:**
- Imports whose target isn't a string literal (e.g. `require(somePathVariable)`) can't be resolved statically and are skipped.
- Security scanning is pattern-based (not full static analysis) and can miss real issues or flag safe code that matches a risky pattern.
- Quality and architecture scores are heuristic engineering signals, not guarantees of correctness or safety.
