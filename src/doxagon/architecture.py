"""Stage I architecture-boundary policy used by the lightweight source guard."""

CONVERTED_MODULES = (
    "doxagon.workspace",
    "doxagon.repositories",
    "doxagon.wal",
    "doxagon.html_editions",
    "doxagon.html_editions.cli",
    "doxagon.html_editions.api",
    "doxagon.html_editions.compiler",
    "doxagon.html_editions.contracts",
    "doxagon.html_editions.css",
    "doxagon.html_editions.errors",
    "doxagon.html_editions.inspector",
    "doxagon.html_editions.public",
    "doxagon.html_editions.resources",
    "doxagon.html_editions.service",
    "doxagon.presentations",
    "doxagon.presentations.agent",
    "doxagon.presentations.api",
    "doxagon.presentations.contracts",
    "doxagon.presentations.cursor",
    "doxagon.presentations.errors",
    "doxagon.presentations.generation",
    "doxagon.presentations.javascript",
    "doxagon.presentations.jobs",
    "doxagon.presentations.receipt",
    "doxagon.presentations.registration",
    "doxagon.presentations.sources",
    "doxagon.presentations.store",
    "doxagon.presentations.thumbnails",
    "doxagon.presentations.validator",
    "doxagon.presentations.workspace",
)
LEGACY_ADAPTER_MODULE = "doxagon.compat.legacy"

# The only sanctioned working-directory read: an explicit convenience
# constructor that snapshots the caller's cwd so a relative --vault argument
# resolves against the invocation, never against the checkout. Every other
# converted module must reach zero cwd callsites.
SANCTIONED_CWD_CALLSITES = {"doxagon.workspace": frozenset({"workspace_request_for_vault"})}

# These are policy tokens, not a sandbox. The test uses AST import and call sites
# so converted modules cannot regress to checkout/cwd discovery or global paths.
# Path.__file__ denotes the Path(__file__) constructor pattern.
FORBIDDEN_LEGACY_IMPORTS = ("doxagon.config", "doxagon.compat.legacy")
FORBIDDEN_DISCOVERY_CALLS = (
    "Path.cwd",
    "os.getcwd",
    "Path.__file__",
)
