"""Shared job output buffer for streaming subprocess output.

This module is separate to avoid circular imports between theses.py and streaming.py.
"""

# In-memory output buffers for active jobs
# Key: job_id, Value: {"lines": list[str], "complete": bool, "exit_code": int | None}
JOB_OUTPUT_BUFFERS: dict[str, dict] = {}


def get_output_buffer(job_id: str) -> dict:
    """Get or create an output buffer for a job."""
    if job_id not in JOB_OUTPUT_BUFFERS:
        JOB_OUTPUT_BUFFERS[job_id] = {
            "lines": [],
            "complete": False,
            "exit_code": None,
        }
    return JOB_OUTPUT_BUFFERS[job_id]


def append_output(job_id: str, line: str):
    """Append a line to a job's output buffer."""
    buffer = get_output_buffer(job_id)
    buffer["lines"].append(line)


def mark_complete(job_id: str, exit_code: int = 0):
    """Mark a job's output as complete."""
    buffer = get_output_buffer(job_id)
    buffer["complete"] = True
    buffer["exit_code"] = exit_code


def clear_buffer(job_id: str):
    """Clear the output buffer for a job."""
    if job_id in JOB_OUTPUT_BUFFERS:
        del JOB_OUTPUT_BUFFERS[job_id]
