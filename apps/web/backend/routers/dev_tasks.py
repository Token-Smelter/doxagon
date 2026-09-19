"""Dev tasks endpoints for UI/code modifications via Claude in isolated worktrees."""

import uuid
import asyncio
import subprocess
import shutil
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from doxagon.config import ROOT_DIR
from apps.web.backend.routers.job_output import append_output, mark_complete


router = APIRouter(prefix="/dev-tasks", tags=["dev-tasks"])


# Job states
JobStatus = Literal[
    "pending",           # Job created, worktree being set up
    "processing",        # Claude is executing tasks
    "testing",           # Running validation (type check, tests)
    "awaiting_approval", # Tests passed, waiting for user to merge or reject
    "merged",            # Changes merged to main, worktree cleaned up
    "rejected",          # User rejected changes, worktree cleaned up
    "error",             # Claude failed, worktree preserved for inspection
    "failed",            # Tests failed, worktree preserved for inspection
]


# Request/Response models
class DevTasksSubmitRequest(BaseModel):
    tasks: list[str]


class DevTasksSubmitResponse(BaseModel):
    status: JobStatus
    message: str
    job_id: str | None = None
    worktree: str | None = None
    branch: str | None = None


class PreflightResponse(BaseModel):
    uncommitted_changes: int
    warning: str | None = None
    safe_to_proceed: bool = True


class JobStatusResponse(BaseModel):
    status: JobStatus
    job_id: str
    worktree: str | None = None
    branch: str | None = None
    message: str | None = None
    test_results: dict | None = None
    diff_stats: dict | None = None


class DiffResponse(BaseModel):
    diff: str
    files: list[str]


class MergeResponse(BaseModel):
    status: Literal["merged"]
    commit: str
    message: str


class RejectResponse(BaseModel):
    status: Literal["rejected"]
    cleaned_up: bool


# In-memory job tracking
DEV_TASK_JOBS: dict[str, dict] = {}

# Worktree directory
WORKTREES_DIR = ROOT_DIR / ".worktrees"

# Find claude binary (may be in nvm path not available to subprocess)
CLAUDE_BIN = shutil.which("claude") or "claude"


def is_git_repo(path: Path) -> bool:
    """Check if path is inside a git repository."""
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=path,
        capture_output=True
    )
    return result.returncode == 0


def count_uncommitted_changes() -> int:
    """Count uncommitted files in the git working directory."""
    if not is_git_repo(ROOT_DIR):
        return 0
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        return 0
    return len([line for line in result.stdout.strip().split('\n') if line])


async def create_worktree(job_id: str) -> Path:
    """Create isolated worktree for dev task."""
    worktree_dir = WORKTREES_DIR / f"dev-task-{job_id}"
    branch_name = f"dev-task/{job_id}"

    # Ensure worktrees directory exists
    WORKTREES_DIR.mkdir(exist_ok=True)

    # Create branch from current HEAD
    await asyncio.to_thread(
        subprocess.run,
        ["git", "branch", branch_name],
        cwd=ROOT_DIR,
        capture_output=True
    )

    # Create worktree
    result = await asyncio.to_thread(
        subprocess.run,
        ["git", "worktree", "add", str(worktree_dir), branch_name],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(f"Failed to create worktree: {result.stderr}")

    return worktree_dir


async def cleanup_worktree(job_id: str):
    """Remove worktree and branch."""
    worktree_dir = WORKTREES_DIR / f"dev-task-{job_id}"
    branch_name = f"dev-task/{job_id}"

    # Remove worktree
    await asyncio.to_thread(
        subprocess.run,
        ["git", "worktree", "remove", str(worktree_dir), "--force"],
        cwd=ROOT_DIR,
        capture_output=True
    )

    # Delete branch
    await asyncio.to_thread(
        subprocess.run,
        ["git", "branch", "-D", branch_name],
        cwd=ROOT_DIR,
        capture_output=True
    )


async def run_tests_in_worktree(worktree_dir: Path) -> tuple[bool, str]:
    """Run validation in worktree."""
    frontend_dir = worktree_dir / "apps" / "web" / "frontend"

    # Run svelte-check
    result = await asyncio.to_thread(
        subprocess.run,
        ["npm", "run", "check"],
        cwd=frontend_dir,
        capture_output=True,
        text=True
    )

    output = result.stdout + result.stderr
    return result.returncode == 0, output


async def get_diff_stats(job_id: str) -> dict:
    """Get diff statistics for a dev task branch."""
    branch_name = f"dev-task/{job_id}"

    result = await asyncio.to_thread(
        subprocess.run,
        ["git", "diff", "--stat", f"HEAD...{branch_name}"],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        return {"files_changed": 0, "insertions": 0, "deletions": 0}

    lines = result.stdout.strip().split('\n')
    if not lines or not lines[-1]:
        return {"files_changed": 0, "insertions": 0, "deletions": 0}

    # Parse summary line (e.g., "3 files changed, 45 insertions(+), 12 deletions(-)")
    summary = lines[-1] if lines else ""
    stats = {"files_changed": 0, "insertions": 0, "deletions": 0}

    import re
    files_match = re.search(r"(\d+) files? changed", summary)
    if files_match:
        stats["files_changed"] = int(files_match.group(1))

    ins_match = re.search(r"(\d+) insertions?\(\+\)", summary)
    if ins_match:
        stats["insertions"] = int(ins_match.group(1))

    del_match = re.search(r"(\d+) deletions?\(-\)", summary)
    if del_match:
        stats["deletions"] = int(del_match.group(1))

    return stats


def build_dev_tasks_prompt(tasks: list[str]) -> str:
    """Build prompt for dev tasks with web app context."""
    prompt_parts = [
        "# Dev Tasks: UI/Code Modifications",
        "",
        "You are modifying the Doxagon web application. This is a SvelteKit frontend with a FastAPI backend.",
        "",
        "## Project Structure",
        "",
        "Frontend (SvelteKit + TypeScript):",
        "- `apps/web/frontend/src/lib/components/` - Svelte components",
        "- `apps/web/frontend/src/lib/stores/` - Svelte stores",
        "- `apps/web/frontend/src/lib/api.ts` - API client functions",
        "- `apps/web/frontend/src/routes/` - Page routes",
        "",
        "Backend (FastAPI + Python):",
        "- `apps/web/backend/routers/` - API route handlers",
        "- `apps/web/backend/main.py` - FastAPI app setup",
        "",
        "## Key Files to Reference",
        "",
        "@apps/web/frontend/src/lib/components/",
        "@apps/web/frontend/src/lib/stores/",
        "@apps/web/frontend/src/lib/api.ts",
        "@apps/web/backend/routers/",
        "",
        "## Requested Changes",
        "",
    ]

    for i, task in enumerate(tasks, 1):
        prompt_parts.append(f"{i}. {task}")

    prompt_parts.extend([
        "",
        "---",
        "",
        "## Instructions",
        "",
        "1. Read the relevant files before making changes",
        "2. Make minimal, focused changes to accomplish each task",
        "3. Follow existing code patterns and conventions",
        "4. Commit your changes with a clear message when done",
        "5. Report what files were modified",
        "",
    ])

    return "\n".join(prompt_parts)


async def run_dev_tasks_job(job_id: str, tasks: list[str]):
    """Background task to run Claude CLI for dev tasks in isolated worktree."""
    worktree_dir = None
    branch_name = f"dev-task/{job_id}"

    try:
        # 1. Create worktree
        DEV_TASK_JOBS[job_id]["status"] = "pending"
        DEV_TASK_JOBS[job_id]["message"] = "Creating isolated worktree..."
        append_output(job_id, "[STATUS] Creating isolated worktree...")

        worktree_dir = await create_worktree(job_id)
        DEV_TASK_JOBS[job_id]["worktree"] = str(worktree_dir)
        DEV_TASK_JOBS[job_id]["branch"] = branch_name
        append_output(job_id, f"[STATUS] Worktree created at {worktree_dir}")

        # 2. Build prompt
        DEV_TASK_JOBS[job_id]["status"] = "processing"
        DEV_TASK_JOBS[job_id]["message"] = "Building prompt..."
        append_output(job_id, "[STATUS] Building dev tasks prompt...")
        prompt_content = build_dev_tasks_prompt(tasks)
        append_output(job_id, f"[STATUS] Prompt ready ({len(prompt_content)} chars)")

        # 3. Invoke Claude CLI in worktree
        DEV_TASK_JOBS[job_id]["message"] = f"Processing {len(tasks)} tasks..."
        append_output(job_id, f"[STATUS] Processing {len(tasks)} task(s) with Claude...")

        process = await asyncio.create_subprocess_exec(
            CLAUDE_BIN, "-p",
            "--allowedTools", "Edit,Read,Glob,Grep,Bash",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=worktree_dir,  # Constrained to worktree
        )

        process.stdin.write(prompt_content.encode())
        await process.stdin.drain()
        process.stdin.close()
        await process.stdin.wait_closed()

        # Stream output
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            decoded = line.decode().rstrip()
            append_output(job_id, decoded)

        return_code = await process.wait()

        if return_code != 0:
            append_output(job_id, f"[ERROR] Claude exited with code {return_code}")
            mark_complete(job_id, return_code)
            DEV_TASK_JOBS[job_id]["status"] = "error"
            DEV_TASK_JOBS[job_id]["message"] = "Claude failed - worktree preserved for inspection"
            return

        append_output(job_id, "[STATUS] Claude completed successfully")

        # 4. Commit changes in worktree
        append_output(job_id, "[STATUS] Committing changes in worktree...")

        await asyncio.to_thread(
            subprocess.run,
            ["git", "add", "-A"],
            cwd=worktree_dir
        )

        task_summary = "; ".join(tasks[:3])
        if len(tasks) > 3:
            task_summary += f" (+{len(tasks) - 3} more)"

        commit_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "commit", "-m", f"Dev tasks: {task_summary}"],
            cwd=worktree_dir,
            capture_output=True,
            text=True
        )

        if commit_result.returncode != 0 and "nothing to commit" in commit_result.stdout:
            append_output(job_id, "[STATUS] No changes made")
            mark_complete(job_id, 0)
            DEV_TASK_JOBS[job_id]["status"] = "merged"  # Nothing to merge
            DEV_TASK_JOBS[job_id]["message"] = "No changes were made"
            await cleanup_worktree(job_id)
            return

        append_output(job_id, "[STATUS] Changes committed")

        # 5. Run tests
        DEV_TASK_JOBS[job_id]["status"] = "testing"
        DEV_TASK_JOBS[job_id]["message"] = "Running validation..."
        append_output(job_id, "[STATUS] Running validation (npm run check)...")

        test_passed, test_output = await run_tests_in_worktree(worktree_dir)
        append_output(job_id, test_output)

        DEV_TASK_JOBS[job_id]["test_results"] = {
            "passed": test_passed,
            "output": test_output
        }

        if not test_passed:
            append_output(job_id, "[FAILED] Tests failed - worktree preserved for inspection")
            mark_complete(job_id, 1)
            DEV_TASK_JOBS[job_id]["status"] = "failed"
            DEV_TASK_JOBS[job_id]["message"] = "Tests failed - review diff and approve or reject"
            DEV_TASK_JOBS[job_id]["diff_stats"] = await get_diff_stats(job_id)
            return

        # 6. Tests passed - await approval
        append_output(job_id, "[STATUS] Tests passed - awaiting approval")
        mark_complete(job_id, 0)
        DEV_TASK_JOBS[job_id]["status"] = "awaiting_approval"
        DEV_TASK_JOBS[job_id]["message"] = "Tests passed - review diff and approve or reject"
        DEV_TASK_JOBS[job_id]["diff_stats"] = await get_diff_stats(job_id)

    except Exception as e:
        append_output(job_id, f"[ERROR] Exception: {str(e)}")
        mark_complete(job_id, 1)
        DEV_TASK_JOBS[job_id]["status"] = "error"
        DEV_TASK_JOBS[job_id]["message"] = f"Error: {str(e)}"


@router.get("/preflight", response_model=PreflightResponse)
def preflight_check():
    """Check conditions before dev task submission."""
    uncommitted = count_uncommitted_changes()
    return PreflightResponse(
        uncommitted_changes=uncommitted,
        warning=f"You have {uncommitted} uncommitted file(s). Consider committing first." if uncommitted > 0 else None,
        safe_to_proceed=True
    )


@router.post("/submit", response_model=DevTasksSubmitResponse)
async def submit_dev_tasks(request: DevTasksSubmitRequest, background_tasks: BackgroundTasks):
    """Submit dev tasks to Claude for processing in isolated worktree."""
    if not request.tasks:
        return DevTasksSubmitResponse(
            status="error",
            message="No tasks provided",
            job_id=None
        )

    # Check for existing processing job
    for job_id, job_data in DEV_TASK_JOBS.items():
        if job_data.get("status") in ("pending", "processing", "testing"):
            return DevTasksSubmitResponse(
                status=job_data["status"],
                message="A dev task job is already in progress",
                job_id=job_id,
                worktree=job_data.get("worktree"),
                branch=job_data.get("branch")
            )

    # Create job
    job_id = str(uuid.uuid4())[:8]
    DEV_TASK_JOBS[job_id] = {
        "status": "pending",
        "message": "Starting...",
        "tasks": request.tasks,
        "worktree": None,
        "branch": None,
        "test_results": None,
        "diff_stats": None,
    }

    background_tasks.add_task(run_dev_tasks_job, job_id, request.tasks)

    return DevTasksSubmitResponse(
        status="pending",
        message=f"Processing {len(request.tasks)} task(s)...",
        job_id=job_id
    )


@router.get("/status/{job_id}", response_model=JobStatusResponse)
def get_dev_task_status(job_id: str):
    """Get status of a dev task job."""
    if job_id not in DEV_TASK_JOBS:
        raise HTTPException(status_code=404, detail="Job not found")

    job = DEV_TASK_JOBS[job_id]
    return JobStatusResponse(
        status=job["status"],
        job_id=job_id,
        worktree=job.get("worktree"),
        branch=job.get("branch"),
        message=job.get("message"),
        test_results=job.get("test_results"),
        diff_stats=job.get("diff_stats"),
    )


@router.get("/{job_id}/diff", response_model=DiffResponse)
async def get_dev_task_diff(job_id: str):
    """Get the diff for a dev task."""
    if job_id not in DEV_TASK_JOBS:
        raise HTTPException(status_code=404, detail="Job not found")

    job = DEV_TASK_JOBS[job_id]
    if job["status"] not in ("awaiting_approval", "failed"):
        raise HTTPException(status_code=400, detail="Job not ready for diff review")

    branch_name = f"dev-task/{job_id}"

    # Get diff
    diff_result = await asyncio.to_thread(
        subprocess.run,
        ["git", "diff", f"HEAD...{branch_name}"],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True
    )

    # Get changed files list
    files_result = await asyncio.to_thread(
        subprocess.run,
        ["git", "diff", "--name-only", f"HEAD...{branch_name}"],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True
    )

    files = [f for f in files_result.stdout.strip().split('\n') if f]

    return DiffResponse(
        diff=diff_result.stdout,
        files=files
    )


@router.post("/{job_id}/merge", response_model=MergeResponse)
async def merge_dev_task(job_id: str):
    """Merge dev task changes into current branch."""
    if job_id not in DEV_TASK_JOBS:
        raise HTTPException(status_code=404, detail="Job not found")

    job = DEV_TASK_JOBS[job_id]
    if job["status"] not in ("awaiting_approval", "failed"):
        raise HTTPException(status_code=400, detail="Job not ready for merge")

    branch_name = f"dev-task/{job_id}"

    # Get tasks summary for commit message
    tasks = job.get("tasks", [])
    tasks_summary = "; ".join(tasks[:3])
    if len(tasks) > 3:
        tasks_summary += f" (+{len(tasks) - 3} more)"

    # Merge branch
    merge_result = await asyncio.to_thread(
        subprocess.run,
        ["git", "merge", branch_name, "-m", f"Dev tasks: {tasks_summary}"],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True
    )

    if merge_result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"Merge failed: {merge_result.stderr}"
        )

    # Get commit hash
    hash_result = await asyncio.to_thread(
        subprocess.run,
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True
    )
    commit_hash = hash_result.stdout.strip()

    # Cleanup worktree and branch
    await cleanup_worktree(job_id)

    # Update job status
    DEV_TASK_JOBS[job_id]["status"] = "merged"
    DEV_TASK_JOBS[job_id]["message"] = f"Merged as {commit_hash}"

    return MergeResponse(
        status="merged",
        commit=commit_hash,
        message=f"Merged dev-task/{job_id}: {tasks_summary}"
    )


@router.post("/{job_id}/reject", response_model=RejectResponse)
async def reject_dev_task(job_id: str):
    """Reject dev task changes and cleanup worktree."""
    if job_id not in DEV_TASK_JOBS:
        raise HTTPException(status_code=404, detail="Job not found")

    job = DEV_TASK_JOBS[job_id]
    if job["status"] not in ("awaiting_approval", "failed", "error"):
        raise HTTPException(status_code=400, detail="Job cannot be rejected in current state")

    # Cleanup worktree and branch
    await cleanup_worktree(job_id)

    # Update job status
    DEV_TASK_JOBS[job_id]["status"] = "rejected"
    DEV_TASK_JOBS[job_id]["message"] = "Changes rejected and cleaned up"

    return RejectResponse(
        status="rejected",
        cleaned_up=True
    )
