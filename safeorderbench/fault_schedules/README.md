# Fault schedules

Faults are declared inline in each scenario's `fault_schedule` and injected
deterministically by `safeagenteval.faults.injector.FaultInjector`:

```yaml
fault_schedule:
  - tool: initiate_transfer
    occurrence: 1          # the first executed call to this tool
    kind: timeout_after_commit
```

| Kind | Backend state | Agent sees |
|---|---|---|
| `timeout_before_commit` | Unchanged; the call never ran | Timeout |
| `timeout_after_commit` | Changed; the call committed | Timeout |

Only calls admitted by the policy are counted as occurrences. The trace keeps
the ground-truth result under `result` and, when a fault fired, the
agent-visible result under `agent_visible_result`. Scoring always uses ground
truth, so a commit hidden by a timeout still counts.

Duplicate delivery and other error kinds are planned. Shared, reusable schedule
files may be added to this directory once more than one scenario needs the
same schedule.
