"""
mpxj/jpype plumbing: the error hierarchy, lazy JVM startup, input file validation, and
opening a project file with mpxj's UniversalProjectReader.
"""

import logging
import os

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class MpxjError(Exception):
    """Base exception for mpxj reader errors."""
    pass


class MpxjNotAvailableError(MpxjError):
    """mpxj or jpype1 is not installed."""
    pass


class MpxjFileError(MpxjError):
    """File not found, not readable, or not a valid .mpp file."""
    pass


class MpxjParseError(MpxjError):
    """mpxj failed to parse the .mpp file."""
    pass


# ---------------------------------------------------------------------------
# JVM lifecycle
# ---------------------------------------------------------------------------

_jvm_started = False  # Best-effort fast path; jpype.startJVM() is internally synchronized.


def _ensure_jvm() -> None:
    """Start the JVM if not already running. No-op after first call."""
    global _jvm_started
    if _jvm_started:
        return

    try:
        import jpype
    except ImportError:
        raise MpxjNotAvailableError(
            "jpype1 is not installed. Install with: "
            "pip install 'msproject-mcp[mpxj]'"
        )

    if not jpype.isJVMStarted():
        try:
            # mpxj bundles its own JARs; jpype finds the default JVM
            import mpxj  # noqa: F401 — import triggers JAR registration
            jpype.startJVM()
            logger.info("JVM started for mpxj fast-read path.")
        except Exception as exc:
            raise MpxjNotAvailableError(
                f"Failed to start JVM for mpxj: {exc}. "
                f"Ensure a JDK/JRE is installed and JAVA_HOME is set."
            ) from exc

    _jvm_started = True


def is_mpxj_available() -> bool:
    """Check whether mpxj and jpype1 are importable (does NOT start JVM)."""
    try:
        import mpxj  # noqa: F401
        import jpype  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# File validation
# ---------------------------------------------------------------------------

_VALID_EXTENSIONS = frozenset((".mpp", ".mpt", ".mpx", ".xml", ".mspdi"))


def _validate_file(file_path: str) -> str:
    """Validate the file exists, is readable, and has a supported extension.

    Returns the resolved absolute path.
    Raises MpxjFileError with a descriptive message on any problem.
    """
    if not file_path or not file_path.strip():
        raise MpxjFileError("file_path is required — provide the path to a .mpp file.")

    resolved = os.path.abspath(file_path)

    if not os.path.exists(resolved):
        raise MpxjFileError(
            f"File not found: {file_path!r}. "
            f"The mpxj tools read the SAVED .mpp file from disk. "
            f"Ensure the file exists and the path is correct."
        )

    if not os.path.isfile(resolved):
        raise MpxjFileError(f"Not a file: {file_path!r} (is it a directory?).")

    if not os.access(resolved, os.R_OK):
        raise MpxjFileError(f"File not readable: {file_path!r}. Check permissions.")

    ext = os.path.splitext(resolved)[1].lower()
    if ext not in _VALID_EXTENSIONS:
        raise MpxjFileError(
            f"Unsupported file extension {ext!r}. "
            f"Supported: {', '.join(sorted(_VALID_EXTENSIONS))}"
        )

    return resolved


# ---------------------------------------------------------------------------
# Core reader: open project file
# ---------------------------------------------------------------------------

def _open_project(file_path: str):
    """Open an .mpp file and return the mpxj ProjectFile object.

    Raises MpxjParseError on parse failure.
    """
    _ensure_jvm()

    try:
        from net.sf.mpxj.reader import UniversalProjectReader
    except ImportError:
        # Fallback: mpxj Python wrapper
        try:
            import mpxj as mpxj_pkg
            reader = mpxj_pkg.ProjectReader()
            return reader.read(file_path)
        except Exception as exc:
            raise MpxjParseError(
                f"Failed to parse {file_path!r}: {exc}. "
                f"The file may be corrupted or in an unsupported format."
            ) from exc

    try:
        reader = UniversalProjectReader()
        project = reader.read(file_path)
        if project is None:
            raise MpxjParseError(
                f"mpxj returned None for {file_path!r}. "
                f"The file may be empty, corrupted, or not a valid project file."
            )
        return project
    except MpxjParseError:
        raise
    except Exception as exc:
        raise MpxjParseError(
            f"Failed to parse {file_path!r}: {exc}. "
            f"The file may be corrupted or in an unsupported format."
        ) from exc
