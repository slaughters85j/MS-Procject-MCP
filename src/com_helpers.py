"""
COM access helpers shared by the tool modules: locating or launching MS Project, the active
project, and conversions between COM values and JSON-friendly Python values.
"""

import datetime
import logging

from .guards import com_call, is_com_busy, get_session

logger = logging.getLogger(__name__)


def _find_app():
    """
    Return the running MS Project COM app, or None if Project is not running.

    Prefers the WP-1 session's app when attached: Office apps started by automation
    can stay out of the Running Object Table, so GetActiveObject may not find a
    hidden instance that the session launched.

    Uses com_call for retry on transient COM busy errors.
    """
    if get_session is not None and get_session().is_attached:
        return get_session().app
    import win32com.client
    try:
        return com_call(
            lambda: win32com.client.GetActiveObject("MSProject.Application"),
            label="GetActiveObject",
        )
    except Exception as e:
        if is_com_busy(e):
            logger.warning("GetActiveObject: COM busy after all retries: %s", e)
        else:
            logger.debug("GetActiveObject failed (%s): %s", type(e).__name__, e)
        return None


def _launch_app():
    """
    Launch MS Project. With the WP-1 session available, the session launches and owns
    the instance, so it follows the session's headless setting (default Visible=False).
    """
    if get_session is not None:
        app = get_session().attach().app
    else:
        import win32com.client
        app = win32com.client.Dispatch("MSProject.Application")
        app.Visible = True
    app.DisplayAlerts = False
    return app


def get_app(require_project=True):
    """Get running MS Project instance.

    Raises RuntimeError with diagnostic guidance covering the three most common
    failure modes (adapted from devGPL fork, Item #8):
      1. MS Project not running
      2. Elevated shell hiding the Running Object Table entry
      3. Wrong Windows logon session (e.g. SSH)
    """
    app = _find_app()
    if app is None:
        raise RuntimeError(
            "Could not attach to MS Project. Check, in order:\n"
            "  1. MS Project is running with a project file open.\n"
            "  2. This server was NOT started from an elevated (admin) shell.\n"
            "     'Run as administrator' hides a normally-launched MS Project\n"
            "     from the Running Object Table rather than helping.\n"
            "  3. This server runs in the same Windows logon session as\n"
            "     MS Project — starting the server over SSH or as a service\n"
            "     places it in session 0, which cannot see the interactive\n"
            "     desktop's COM registrations."
        )
    if require_project:
        try:
            count = com_call(lambda: app.Projects.Count, label="Projects.Count")
        except Exception:
            count = app.Projects.Count
        if count == 0:
            raise RuntimeError(
                "No project file is open in MS Project. Open a .mpp file first."
            )
    return app


def get_proj(app):
    return app.ActiveProject


def _get_mpd(proj):
    """Get MinutesPerDay safely (falls back to 480 for freshly-imported XML)."""
    try:
        return proj.MinutesPerDay
    except Exception:
        return 480


def _parse_date(s):
    """Parse YYYY-MM-DD string to datetime for COM. Returns None if empty."""
    if not s:
        return None
    return datetime.datetime.strptime(s, "%Y-%m-%d")


def task_to_dict(t, proj):
    """Convert a COM Task object to a plain dict."""
    mpd = _get_mpd(proj)

    def fmt(dt):
        try:
            if dt is None:
                return None
            return str(dt)[:19]
        except Exception:
            return None

    # Reverse map for constraint type integers
    CONSTRAINT_NAMES = {
        0: "ASAP", 1: "ALAP", 2: "MSO", 3: "MFO",
        4: "SNET", 5: "SNLT", 6: "FNET", 7: "FNLT",
    }
    # Reverse map for task type integers
    TASK_TYPE_NAMES = {0: "FixedUnits", 1: "FixedDuration", 2: "FixedWork"}

    # Safe reads for fields that may not be available on all task types
    def safe(prop, default=None):
        try:
            return prop
        except Exception:
            return default

    return {
        "unique_id":              t.UniqueID,
        "id":                     t.ID,
        "name":                   t.Name,
        "outline_level":          t.OutlineLevel,
        "wbs":                    t.WBS,
        "summary":                bool(t.Summary),
        "milestone":              bool(t.Milestone),
        "start":                  fmt(t.Start),
        "finish":                 fmt(t.Finish),
        "duration_days":          round(t.Duration / mpd, 2) if t.Duration else 0,
        "percent_complete":       t.PercentComplete,
        "actual_start":           fmt(safe(t.ActualStart)),
        "actual_finish":          fmt(safe(t.ActualFinish)),
        "remaining_duration_days": round(safe(t.RemainingDuration, 0) / mpd, 2),
        "total_slack_days":       round(safe(t.TotalSlack, 0) / mpd, 2),
        "free_slack_days":        round(safe(t.FreeSlack, 0) / mpd, 2),
        "deadline":               fmt(safe(t.Deadline)),
        "priority":               safe(t.Priority, 500),
        "constraint_type":        CONSTRAINT_NAMES.get(safe(t.ConstraintType, 0), "ASAP"),
        "constraint_date":        fmt(safe(t.ConstraintDate)),
        "manual":                 bool(safe(t.Manual, False)),
        "type":                   TASK_TYPE_NAMES.get(safe(t.Type, 0), "FixedUnits"),
        "predecessors":           t.Predecessors,
        "resource_names":         t.ResourceNames,
        "notes":                  t.Notes,
        "critical":               bool(t.Critical),
        "active":                 bool(t.Active),
        "rag":                    t.Text1 or "",
        "text1":                  t.Text1 or "",
        "text2":                  t.Text2 or "",
        "text3":                  t.Text3 or "",
        "flag1":                  bool(t.Flag1),
        "flag2":                  bool(t.Flag2),
        "hyperlink":              safe(t.HyperlinkAddress, "") or "",
        "hyperlink_text":         safe(t.Hyperlink, "") or "",
    }


def _count_resources(proj):
    """Count resources safely — returns 0 if resource pool is empty/inaccessible."""
    try:
        return sum(1 for r in proj.Resources if r is not None)
    except Exception:
        return 0


def _fmt_date(dt):
    """Format a COM date to 'YYYY-MM-DD' string. Returns None on failure."""
    try:
        return str(dt)[:10] if dt else None
    except Exception:
        return None


def _to_naive(dt):
    """Strip timezone from COM datetime for safe comparison with datetime.now()."""
    if dt is None:
        return None
    try:
        if hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
            return dt.replace(tzinfo=None)
    except Exception:
        pass
    return dt


def _find_task(proj, unique_id):
    """Find a task by UniqueID. Returns the COM Task object or None."""
    for t in proj.Tasks:
        if t is not None and t.UniqueID == unique_id:
            return t
    return None


def _custom_field_id(field_name):
    """
    Map field name like 'Text5', 'Number1', 'Flag3', 'Date1', 'Duration2'
    to the COM pjCustomTask* field ID constant.
    Returns (field_id, field_type) or raises ValueError.
    """
    name = field_name.strip()
    lower = name.lower()

    # COM field ID bases (pjCustomTask* constants)
    bases = {
        "text":     (188743731, 30),   # Text1-30
        "number":   (188743767, 20),   # Number1-20
        "date":     (188743945, 10),   # Date1-10
        "flag":     (188743752, 20),   # Flag1-20
        "duration": (188743783, 10),   # Duration1-10
    }

    for prefix, (base_id, max_n) in bases.items():
        if lower.startswith(prefix):
            num_str = lower[len(prefix):]
            if num_str.isdigit():
                num = int(num_str)
                if 1 <= num <= max_n:
                    return base_id + (num - 1), prefix
    raise ValueError(f"Unknown custom field: '{field_name}'. Use Text1-30, Number1-20, Date1-10, Flag1-20, Duration1-10.")
