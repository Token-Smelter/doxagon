"""Closed, offline HTML Edition contracts and compiler services."""

from .compiler import BuildResult, EditionIdentity, EditionReceipt, HtmlEditionCompiler
from .contracts import ContentDocument, load_content_document
from .errors import HtmlEditionError
from .inspector import InspectionReport, inspect_edition
from .public import PublicEdgeV1, PublicEvidenceV1, PublicGraphExcerptV1, PublicNodeV1
from .service import HtmlEditionCoordinator, HtmlEditionServiceError, Job

__all__ = [
    "BuildResult",
    "ContentDocument",
    "EditionIdentity",
    "EditionReceipt",
    "HtmlEditionCompiler",
    "HtmlEditionCoordinator",
    "HtmlEditionError",
    "HtmlEditionServiceError",
    "InspectionReport",
    "Job",
    "PublicEdgeV1",
    "PublicEvidenceV1",
    "PublicGraphExcerptV1",
    "PublicNodeV1",
    "inspect_edition",
    "load_content_document",
]
