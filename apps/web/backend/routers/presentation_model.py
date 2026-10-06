"""Which rendering model a thesis's presentation uses.

Separate from the routers that read it so `theses.py` and `diegeses.py` answer
the question identically, the way `job_output.py` is separate from the two
routers that share its buffers.

The two models are different products rather than two encodings of one. A
document-model thesis keeps a single authored HTML file selected by
``outputs/document/presentation.json`` and plays it through the MessagePort
bridge; a legacy thesis keeps per-slide sources under
``outputs/presentation/slides/``. Reporting only ``has_presentation`` forced
every caller to guess the model from ``slide_count``, which a document does not
have, so a document-model thesis read as having no presentation at all.
"""

from pathlib import Path

from doxagon.models import PresentationModel


def presentation_model(thesis_dir: Path) -> PresentationModel:
    """Name the model this thesis's presentation plays through.

    The selection manifest, not the ``outputs/document/`` directory, is the
    discriminator: the playback routes resolve an authored selection before any
    checkpoint workspace (``src/doxagon/renderings/document_context.py``
    ``inspect_project``), and a directory without that manifest is not served as
    a document. A selected document therefore wins over sibling legacy slides,
    which is what actually plays.
    """
    selection = thesis_dir / "outputs" / "document" / "presentation.json"
    if selection.exists() or selection.is_symlink():
        return "document"
    if (thesis_dir / "outputs" / "presentation").exists():
        return "slides"
    return "none"
