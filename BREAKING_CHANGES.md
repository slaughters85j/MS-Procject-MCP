# Breaking Changes

## Sprint 3: Response Size Management (v0.9.0)

### Response shape changes for high-volume read tools

The following tools now return paginated, field-stripped responses by default:

- `get_tasks`
- `get_resources`
- `filter_tasks`
- `search_tasks`
- `get_task_dependencies`
- `get_wbs_structure`

#### 1. Pagination wrapper

**Before (v0.8.x):**
```json
{"count": 8243, "tasks": [...all 8243 tasks...]}
```

**After (v0.9.0):**
```json
{
  "pagination": {
    "total": 8243,
    "returned": 200,
    "offset": 0,
    "truncated": true,
    "next_offset": 200,
    "how_to_get_more": "..."
  },
  "tasks": [...first 200 tasks...]
}
```

**Migration:** Clients reading `response["count"]` must now read
`response["pagination"]["total"]`. Clients reading `response["tasks"]`
continue to work. Pass `offset` and `limit` parameters to page through
large result sets. Use `limit=-1` to get all items in one response.

#### 2. Empty field stripping

Task dicts now omit fields with empty/zero/false values. A missing key
means the value was empty (`""`), `None`, `False`, or `0` (for non-measurement
fields).

**Before:**
```json
{"unique_id": 1, "name": "Task", "notes": "", "deadline": null,
 "critical": false, "hyperlink": "", "priority": 0}
```

**After:**
```json
{"unique_id": 1, "name": "Task", "percent_complete": 0, "outline_level": 1}
```

**Always kept:** `unique_id`, `id`, `name` (identity fields).
**Zero preserved:** `percent_complete`, `duration_days`, `total_slack_days`,
`free_slack_days`, `outline_level`, `remaining_duration_days`.

**Migration:** Replace `task["field"]` with `task.get("field", default)`.

#### 3. Adaptive JSON formatting

Responses larger than 4 KB are now compact JSON (no indentation).
Responses smaller than 4 KB remain indented for readability.

**Migration:** No code changes needed — `json.loads()` handles both formats.
If you were parsing with regex or string matching, switch to proper JSON parsing.

### New parameters on read tools

`get_tasks`, `get_resources`, `search_tasks` now accept `offset` (int, default 0)
and `limit` (int, default 200). These are additive — existing calls without
these parameters get the first 200 items (previously all items).

### ToolAnnotations

All tools now carry MCP `ToolAnnotations` metadata (`readOnlyHint`,
`destructiveHint`, `idempotentHint`). This is additive and non-breaking
for clients that don't read annotations. Clients that do read annotations
can use them for safety checks and UI hints.
