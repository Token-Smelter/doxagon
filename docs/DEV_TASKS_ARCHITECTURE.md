# Dev Tasks Architecture

A worktree-isolated approach for executing UI/code modifications via Claude.

## Overview

Dev Tasks allows requesting code changes to the web application from within the UI itself. Changes execute in an isolated git worktree, run through validation, and only merge to main after approval.

## Design Principles

1. **Isolation** - Agent operates in a worktree, cannot affect main working directory
2. **Validation** - Tests must pass before changes can merge
3. **Atomic** - Nothing lands until explicit merge approval
4. **Reversible** - Delete worktree to abandon changes, no cleanup needed

## Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        DEV TASKS FLOW                           │
└─────────────────────────────────────────────────────────────────┘

  User                    Backend                     Git
    │                        │                         │
    │  Submit tasks          │                         │
    │───────────────────────>│                         │
    │                        │  Create branch          │
    │                        │────────────────────────>│
    │                        │  Create worktree        │
    │                        │────────────────────────>│
    │                        │                         │
    │                        │  Run Claude (cwd=worktree)
    │  Stream output         │  ─────────────┐         │
    │<───────────────────────│               │         │
    │                        │<──────────────┘         │
    │                        │                         │
    │                        │  Commit changes         │
    │                        │────────────────────────>│
    │                        │                         │
    │                        │  Run tests in worktree  │
    │  Stream test output    │  ─────────────┐         │
    │<───────────────────────│               │         │
    │                        │<──────────────┘         │
    │                        │                         │
    │  Show diff + results   │                         │
    │<───────────────────────│                         │
    │                        │                         │
    │  [Approve/Reject]      │                         │
    │───────────────────────>│                         │
    │                        │                         │
    │  (if approved)         │  Merge branch           │
    │                        │────────────────────────>│
    │                        │  Delete worktree        │
    │                        │────────────────────────>│
    │                        │                         │
    │  (if rejected)         │  Delete branch          │
    │                        │────────────────────────>│
    │                        │  Delete worktree        │
    │                        │────────────────────────>│
```

## Directory Structure

```
project/
├── .worktrees/                    # Worktree container (gitignored)
│   └── dev-task-{job_id}/         # Isolated worktree for each job
│       └── (full repo copy)
├── apps/web/...                   # Main working directory (untouched)
└── ...
```

## Job States

```
┌─────────┐     ┌────────────┐     ┌─────────┐     ┌──────────────┐
│ pending │────>│ processing │────>│ testing │────>│ awaiting_    │
└─────────┘     └────────────┘     └─────────┘     │ approval     │
                      │                  │          └──────────────┘
                      │                  │                 │
                      v                  v                 v
                ┌──────────┐      ┌──────────┐     ┌───────────┐
                │  error   │      │  failed  │     │  merged   │
                └──────────┘      └──────────┘     └───────────┘
                                                          │
                                                          v
                                                   ┌───────────┐
                                                   │ rejected  │
                                                   └───────────┘
```

| State | Description |
|-------|-------------|
| `pending` | Job created, worktree being set up |
| `processing` | Claude is executing tasks |
| `testing` | Running validation (type check, tests) |
| `awaiting_approval` | Tests passed, waiting for user to merge or reject |
| `merged` | Changes merged to main, worktree cleaned up |
| `rejected` | User rejected changes, worktree cleaned up |
| `error` | Claude failed, worktree preserved for inspection |
| `failed` | Tests failed, worktree preserved for inspection |

## API Endpoints

### Submit Tasks

```
POST /api/dev-tasks/submit
Content-Type: application/json

{
  "tasks": ["Add loading spinner to Graph component", "Fix button alignment"]
}

Response:
{
  "status": "processing",
  "job_id": "abc123",
  "worktree": ".worktrees/dev-task-abc123",
  "branch": "dev-task/abc123"
}
```

### Get Job Status

```
GET /api/dev-tasks/status/{job_id}

Response:
{
  "status": "awaiting_approval",
  "job_id": "abc123",
  "worktree": ".worktrees/dev-task-abc123",
  "branch": "dev-task/abc123",
  "test_results": {
    "passed": true,
    "output": "..."
  },
  "diff_stats": {
    "files_changed": 3,
    "insertions": 45,
    "deletions": 12
  }
}
```

### Get Diff

```
GET /api/dev-tasks/{job_id}/diff

Response:
{
  "diff": "diff --git a/...",
  "files": ["apps/web/.../Component.svelte", "..."]
}
```

### Approve/Merge

```
POST /api/dev-tasks/{job_id}/merge

Response:
{
  "status": "merged",
  "commit": "abc123def",
  "message": "Merged dev-task/abc123: Add loading spinner, Fix button alignment"
}
```

### Reject/Abandon

```
POST /api/dev-tasks/{job_id}/reject

Response:
{
  "status": "rejected",
  "cleaned_up": true
}
```

### Stream Output

```
GET /api/stream/job/{job_id}

SSE stream of:
- Claude output during processing
- Test output during testing
- Status updates
```

## Implementation Details

### Worktree Management

```python
async def create_worktree(job_id: str) -> Path:
    """Create isolated worktree for dev task."""
    worktree_dir = ROOT_DIR / ".worktrees" / f"dev-task-{job_id}"
    branch_name = f"dev-task/{job_id}"

    # Create branch from current HEAD
    await run(["git", "branch", branch_name])

    # Create worktree
    await run(["git", "worktree", "add", str(worktree_dir), branch_name])

    return worktree_dir


async def cleanup_worktree(job_id: str):
    """Remove worktree and branch."""
    worktree_dir = ROOT_DIR / ".worktrees" / f"dev-task-{job_id}"
    branch_name = f"dev-task/{job_id}"

    # Remove worktree
    await run(["git", "worktree", "remove", str(worktree_dir), "--force"])

    # Delete branch
    await run(["git", "branch", "-D", branch_name])
```

### Claude Invocation

```python
process = await asyncio.create_subprocess_exec(
    "claude", "-p",
    "--allowedTools", "Edit,Read,Glob,Grep,Bash",
    stdin=asyncio.subprocess.PIPE,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.STDOUT,
    cwd=worktree_dir,  # Constrained to worktree
)
```

### Test Validation

```python
async def run_tests(worktree_dir: Path) -> tuple[bool, str]:
    """Run validation in worktree."""
    # Frontend type check
    result = await run(
        ["npm", "run", "check"],
        cwd=worktree_dir / "apps" / "web" / "frontend"
    )

    if result.returncode != 0:
        return False, result.output

    # Backend import check (optional)
    # pytest, etc.

    return True, result.output
```

### Merge Strategy

```python
async def merge_changes(job_id: str):
    """Merge worktree branch into current branch."""
    branch_name = f"dev-task/{job_id}"

    # Get current branch
    current = await run(["git", "rev-parse", "--abbrev-ref", "HEAD"])

    # Merge with commit message
    tasks_summary = get_tasks_summary(job_id)
    await run([
        "git", "merge", branch_name,
        "-m", f"Dev tasks: {tasks_summary}"
    ])

    # Cleanup
    await cleanup_worktree(job_id)
```

## UI Components

### DevTasksModal Updates

- Show job status progression
- Display test results
- Show diff preview
- Merge/Reject buttons when awaiting approval

### New: DevTaskResultPanel

Slide-out panel showing:
- Diff viewer with syntax highlighting
- Test output
- File list with changes
- Merge/Reject actions

## Configuration

Add to `.gitignore`:
```
.worktrees/
```

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Claude fails | Status → `error`, worktree preserved, user can inspect |
| Tests fail | Status → `failed`, worktree preserved, user can inspect/fix |
| Merge conflict | Show conflict, user resolves in worktree or rejects |
| Worktree creation fails | Return error, no cleanup needed |

## Future Enhancements

1. **Auto-fix on test failure** - Re-run Claude with test errors as context
2. **Partial merge** - Cherry-pick specific commits from the branch
3. **Worktree inspection UI** - Browse/edit files in worktree from web UI
4. **Multiple concurrent jobs** - Each in its own worktree (already supported)
5. **Job history** - Persist job records for audit trail
