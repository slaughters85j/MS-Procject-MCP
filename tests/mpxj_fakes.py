"""
Mock builders for mpxj Java objects (Task, Resource, ResourceAssignment, ProjectCalendar,
ProjectFile) used by the mpxj unit tests.
"""

from unittest.mock import MagicMock


def _make_mock_task(uid=1, task_id=1, name="Task 1", **overrides):
    """Create a mock Java task object."""
    task = MagicMock()
    task.getUniqueID.return_value = uid
    task.getID.return_value = task_id
    task.getName.return_value = name
    task.getOutlineLevel.return_value = 1
    task.getOutlineNumber.return_value = "1"
    task.getWBS.return_value = "1"
    task.getSummary.return_value = False
    task.getStart.return_value = "2026-01-15T08:00"
    task.getFinish.return_value = "2026-01-20T17:00"
    task.getDuration.return_value = None
    task.getActualStart.return_value = None
    task.getActualFinish.return_value = None
    task.getBaselineStart.return_value = None
    task.getBaselineFinish.return_value = None
    task.getBaselineDuration.return_value = None
    task.getPercentageComplete.return_value = 50
    task.getPhysicalPercentComplete.return_value = None
    task.getConstraintType.return_value = None
    task.getConstraintDate.return_value = None
    task.getDeadline.return_value = None
    task.getPriority.return_value = None
    task.getType.return_value = None
    task.getMilestone.return_value = False
    task.getCritical.return_value = False
    task.getActive.return_value = True
    task.getTotalSlack.return_value = None
    task.getFreeSlack.return_value = None
    task.getCost.return_value = None
    task.getActualCost.return_value = None
    task.getBaselineCost.return_value = None
    task.getWork.return_value = None
    task.getActualWork.return_value = None
    task.getRemainingWork.return_value = None
    task.getNotes.return_value = None
    task.getCalendar.return_value = None
    task.getPredecessors.return_value = None
    task.getResourceAssignments.return_value = None

    for k, v in overrides.items():
        getattr(task, k).return_value = v
    return task


def _make_mock_resource(uid=1, res_id=1, name="Resource 1"):
    """Create a mock Java resource object."""
    res = MagicMock()
    res.getUniqueID.return_value = uid
    res.getID.return_value = res_id
    res.getName.return_value = name
    res.getType.return_value = "WORK"
    res.getInitials.return_value = "R1"
    res.getGroup.return_value = None
    res.getEmailAddress.return_value = "res@example.com"
    res.getMaxUnits.return_value = 100
    res.getStandardRate.return_value = None
    res.getOvertimeRate.return_value = None
    res.getCostPerUse.return_value = None
    res.getCost.return_value = None
    res.getActualCost.return_value = None
    res.getWork.return_value = None
    res.getActualWork.return_value = None
    res.getRemainingWork.return_value = None
    res.getAvailableFrom.return_value = None
    res.getAvailableTo.return_value = None
    res.getNotes.return_value = None
    res.getCalendar.return_value = None
    return res


def _make_mock_assignment(uid=1, task_uid=10, task_name="T1", res_uid=5, res_name="R1"):
    """Create a mock Java resource assignment."""
    asn = MagicMock()
    asn.getUniqueID.return_value = uid

    task = MagicMock()
    task.getUniqueID.return_value = task_uid
    task.getName.return_value = task_name
    asn.getTask.return_value = task

    res = MagicMock()
    res.getUniqueID.return_value = res_uid
    res.getName.return_value = res_name
    asn.getResource.return_value = res

    asn.getUnits.return_value = 100
    asn.getWork.return_value = None
    asn.getActualWork.return_value = None
    asn.getRemainingWork.return_value = None
    asn.getCost.return_value = None
    asn.getActualCost.return_value = None
    asn.getStart.return_value = "2026-01-15T08:00"
    asn.getFinish.return_value = "2026-01-20T17:00"
    asn.getPercentageWorkComplete.return_value = 50
    return asn


def _make_mock_calendar(uid=1, name="Standard"):
    """Create a mock Java calendar."""
    cal = MagicMock()
    cal.getUniqueID.return_value = uid
    cal.getName.return_value = name
    cal.getParent.return_value = None
    cal.getCalendarExceptions.return_value = MagicMock(size=MagicMock(return_value=0))
    return cal


def _make_java_list(items):
    """Create a mock Java List with .size() and .get(i)."""
    jlist = MagicMock()
    jlist.size.return_value = len(items)
    jlist.get.side_effect = lambda i: items[i]
    return jlist


def _make_mock_project(tasks=None, resources=None, assignments=None, calendars=None):
    """Create a mock mpxj ProjectFile."""
    project = MagicMock()

    if tasks is None:
        tasks = [_make_mock_task(uid=0, task_id=0, name="Project Summary")]
    project.getTasks.return_value = _make_java_list(tasks)

    if resources is None:
        resources = []
    project.getResources.return_value = _make_java_list(resources)

    if assignments is None:
        assignments = []
    project.getResourceAssignments.return_value = _make_java_list(assignments)

    if calendars is None:
        calendars = []
    project.getCalendars.return_value = _make_java_list(calendars)

    props = MagicMock()
    props.getProjectTitle.return_value = "Test Project"
    props.getSubject.return_value = None
    props.getAuthor.return_value = "John"
    props.getManager.return_value = "Jane"
    props.getCompany.return_value = "Acme"
    props.getCategory.return_value = None
    props.getComments.return_value = None
    props.getStartDate.return_value = "2026-01-01"
    props.getFinishDate.return_value = "2026-12-31"
    props.getCurrentDate.return_value = None
    props.getStatusDate.return_value = None
    props.getCreationDate.return_value = None
    props.getLastSaved.return_value = None
    props.getScheduleFrom.return_value = None
    props.getMinutesPerDay.return_value = 480
    props.getMinutesPerWeek.return_value = 2400
    props.getDaysPerMonth.return_value = 20
    props.getDefaultCalendarName.return_value = "Standard"
    props.getCurrencySymbol.return_value = "$"
    project.getProjectProperties.return_value = props

    return project
