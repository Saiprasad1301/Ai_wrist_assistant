# Codex n8n agent pack

This pack adds project-scoped Codex guidance and custom subagents for reviewing, debugging, and planning changes to n8n workflows through your existing MCP connection.

## What is included
- `AGENTS.md` - project-wide operating rules for n8n workflow review.
- `.codex/config.toml` - project-scoped Codex settings with agent limits.
- `.codex/agents/*.toml` - custom subagents for specialized review tasks.

## Included custom agents
- `structure_analyst`
- `trigger_startup_reviewer`
- `credentials_dependency_auditor`
- `logic_mapping_debugger`
- `execution_failure_investigator`
- `production_readiness_reviewer`
- `workflow_patch_planner`

## Before you start
1. Install and sign in to Codex.
2. Make sure your n8n MCP server is already configured and working in Codex.
3. Open or create a local project folder for this setup.
4. Copy this pack into that project root.

## Install steps
### macOS / Linux
```bash
mkdir -p ~/projects/n8n-review
cp -R codex-n8n-agent-pack/. ~/projects/n8n-review/
cd ~/projects/n8n-review
```

### Windows PowerShell
```powershell
New-Item -ItemType Directory -Force "$HOME\projects\n8n-review" | Out-Null
Copy-Item -Recurse -Force ".\codex-n8n-agent-pack\*" "$HOME\projects\n8n-review\"
Set-Location "$HOME\projects\n8n-review"
```

## Trust the project
Codex loads project-scoped `.codex/config.toml` only when the project is trusted. If the Codex app or CLI prompts you to trust the project, approve it.

## Verify the setup
From the project directory, ask Codex:

```text
Summarize the current instructions and list the available custom agents.
```

You should see the `AGENTS.md` guidance reflected and the custom agent names available.

## How to run a workflow review
Use a parent prompt like this:

```text
Use the connected n8n MCP tools to review workflow "WORKFLOW_NAME_OR_ID".
Spawn these custom agents in parallel when helpful:
- structure_analyst
- trigger_startup_reviewer
- credentials_dependency_auditor
- logic_mapping_debugger
- execution_failure_investigator
- production_readiness_reviewer

Wait for all of them, then merge the results into one report with this format:
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

Do not make edits yet.
```

## How to ask for a patch plan
After the review finishes, use:

```text
Based on the review findings, spawn workflow_patch_planner.
Create an exact change plan for the workflow.
Do not apply changes yet. Group the plan into critical fixes, safe improvements, and optional refactors.
```

## How to ask for edits after approval
If your MCP setup supports editing workflows, use a prompt like:

```text
Apply only the approved critical fixes to workflow "WORKFLOW_NAME_OR_ID".
Before each edit, state the node and field being changed.
After changes, summarize exactly what changed and what still needs manual testing.
```

## Recommended operating pattern
1. Review first.
2. Patch plan second.
3. Apply only approved edits.
4. Re-run review on the updated workflow.
5. Test manually in n8n.

## Troubleshooting
### Codex does not see the project agents
- Confirm the files are inside the project root:
  - `AGENTS.md`
  - `.codex/config.toml`
  - `.codex/agents/*.toml`
- Confirm the project is trusted.
- Ask Codex to summarize current instructions.

### Codex cannot access n8n workflows
- Your n8n MCP server is likely not configured or not connected for this Codex session.
- Verify your MCP server in your user-level Codex setup before using this pack.

### The agent reviews but does not edit
- That is by design. This pack defaults to read-only specialists.
- Use `workflow_patch_planner` to prepare changes first.
- Only then ask the parent agent to apply approved edits, if your MCP server supports workflow mutation.

## Notes
- Codex custom agents are defined as standalone TOML files under `.codex/agents/`.
- `AGENTS.md` is read before work starts and can be layered globally and per project.
- Project-scoped `.codex/config.toml` is only loaded for trusted projects.
