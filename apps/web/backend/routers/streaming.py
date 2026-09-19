"""Streaming endpoints for real-time job output via Server-Sent Events."""

import asyncio
from typing import AsyncGenerator
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

# Import job tracking dictionaries from routers
from apps.web.backend.routers.theses import SUBMISSION_JOBS, GENERATION_JOBS, BATCH_GENERATION_JOBS
from apps.web.backend.routers.dev_tasks import DEV_TASK_JOBS

# Import shared output buffer
from apps.web.backend.routers.job_output import (
    JOB_OUTPUT_BUFFERS,
    get_output_buffer,
    clear_buffer,
)

router = APIRouter(prefix="/stream", tags=["streaming"])


def find_job(job_id: str) -> tuple[str, dict] | None:
    """Find a job by ID across all job tracking dictionaries."""
    # Check submission jobs
    if job_id in SUBMISSION_JOBS:
        return ("submission", SUBMISSION_JOBS[job_id])

    # Check generation jobs
    if job_id in GENERATION_JOBS:
        return ("generation", GENERATION_JOBS[job_id])

    # Check batch generation jobs
    if job_id in BATCH_GENERATION_JOBS:
        return ("batch_generation", BATCH_GENERATION_JOBS[job_id])

    # Check dev task jobs
    if job_id in DEV_TASK_JOBS:
        return ("dev_tasks", DEV_TASK_JOBS[job_id])

    return None


async def stream_job_output(job_id: str) -> AsyncGenerator[str, None]:
    """Generate SSE events for a job's output."""
    buffer = get_output_buffer(job_id)
    last_index = 0

    while True:
        # Send any new lines
        while last_index < len(buffer["lines"]):
            line = buffer["lines"][last_index]
            yield f"data: {line}\n\n"
            last_index += 1

        # Check if job is complete
        if buffer["complete"]:
            yield f"data: [EXIT:{buffer['exit_code']}]\n\n"
            break

        # Also check job status from tracking dicts
        job_info = find_job(job_id)
        if job_info:
            _, job_data = job_info
            status = job_data.get("status")
            message = job_data.get("message", "")

            # If there's a status message and no buffered output, yield the status
            if last_index == 0 and message:
                yield f"data: [STATUS] {message}\n\n"

            # Check if job completed/errored
            if status in ("complete", "error"):
                if status == "error":
                    yield f"data: [ERROR] {message}\n\n"
                else:
                    yield f"data: [COMPLETE] {message}\n\n"
                break

        # Wait before checking again
        await asyncio.sleep(0.5)


@router.get("/job/{job_id}")
async def stream_job(job_id: str):
    """
    Stream output for an active job via Server-Sent Events.

    Connect to this endpoint to receive real-time output from:
    - Image generation jobs
    - Build jobs
    - Annotation submission jobs
    - Developer annotation jobs

    Events are formatted as SSE:
    - `data: <line>` - Output line from subprocess
    - `data: [STATUS] <msg>` - Status update
    - `data: [ERROR] <msg>` - Error message
    - `data: [COMPLETE] <msg>` - Job completed successfully
    - `data: [EXIT:<code>]` - Process exit code
    """
    # Verify job exists
    job_info = find_job(job_id)
    if not job_info:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    return StreamingResponse(
        stream_job_output(job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.delete("/job/{job_id}")
async def clear_job_buffer(job_id: str):
    """Clear the output buffer for a completed job."""
    if job_id in JOB_OUTPUT_BUFFERS:
        clear_buffer(job_id)
        return {"success": True, "message": f"Buffer cleared for job {job_id}"}
    return {"success": True, "message": "Buffer already empty"}
