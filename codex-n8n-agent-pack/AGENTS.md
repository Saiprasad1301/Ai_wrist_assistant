# n8n workflow review defaults

## Working agreements
- Use connected n8n MCP tools to inspect workflows before making claims.
- Prefer review-first behavior: diagnose, explain, and propose changes before editing.
- Treat missing logs, credentials, or MCP permissions as explicit unknowns.
- Prefer minimal safe fixes before larger refactors.
- When suggesting edits, name the exact nodes and fields affected.
- Do not apply destructive or production-impacting changes without approval.

## Standard report format
A. Workflow purpose
B. Trigger and how it starts
C. Node-by-node breakdown
D. Data flow summary
E. Problems found
F. Root-cause debugging notes
G. Required fixes
H. How to test it now
I. How to activate/use it in production
J. Recommended improvements

## Delegation policy
For deep workflow reviews, explicitly spawn these specialist agents in parallel when useful:
- structure_analyst
- trigger_startup_reviewer
- credentials_dependency_auditor
- logic_mapping_debugger
- execution_failure_investigator
- production_readiness_reviewer

Then merge findings into one final report and remove duplicates.
