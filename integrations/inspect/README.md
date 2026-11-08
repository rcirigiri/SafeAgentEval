# Inspect integration

`safeagenteval_task.py` exposes the 14 public banking scenarios as an Inspect
(UK AISI) task, one sample per scenario, tagged with category and kind.

```bash
pip install inspect-ai
inspect eval integrations/inspect/safeagenteval_task.py@safeagenteval_banking --model <provider/model>
```

Status: dataset/task surface. Scoring inside Inspect requires a solver that
drives the agent under test through the SafeAgentEval harness; the
authoritative scorer remains `safeagenteval`'s deterministic state scorer
(`safeagenteval run`), whose run records can be converted with
`safeagenteval report`. Do not treat the Inspect target string as a scorer.
