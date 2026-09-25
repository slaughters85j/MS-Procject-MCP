"""
Field normalisation for bulk_update items.

Requested values arrive as JSON (dates are strings). Before a dry run or an apply, each
field name is checked against the COM task and date fields are converted with
com_write.to_com_date, so the dry run predicts exactly what apply will attempt and apply
never hands COM a raw string for a date.
"""

import re

from .com_write import to_com_date

_DATE_FIELD = re.compile(
    r"^(Start|Finish|Deadline|ConstraintDate|ActualStart|ActualFinish|Resume|Stop|"
    r"Date\d{1,2}|Start\d{1,2}|Finish\d{1,2})$")
_END_OF_DAY = re.compile(r"(Finish|Deadline|Stop)")


def normalize_fields(project, task, fields):
    """
    Return a copy of fields with date strings converted for COM.
    Raises ValueError for a field the task does not have or an unparseable date.
    """
    out = {}
    for name, value in fields.items():
        try:
            getattr(task, name)
        except AttributeError:
            raise ValueError(f"Unknown task field '{name}'.") from None
        if _DATE_FIELD.match(name) and isinstance(value, str):
            value = to_com_date(project, value, end_of_day=bool(_END_OF_DAY.search(name)), field=name)
        out[name] = value
    return out


def normalized_or_error(project, task, fields):
    """(normalised fields, None) or (None, error message) for one bulk item."""
    try:
        return normalize_fields(project, task, fields), None
    except ValueError as e:
        return None, str(e)
