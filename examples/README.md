# Examples

SafeAgentEval evaluates **black-box session agents** (Agent Contract
Profile C): the harness sends scripted customer utterances, the agent
executes its own tools internally, and the harness grades the final state
read back through the agent owner's StateProvider. The harness provides
no tools and executes no calls.

Install first:

```bash
python -m pip install -e .
```

## Banking demo

Run the built-in safe and unsafe demo session agents over the banking
scenarios. The safe agent passes everything; the unsafe agent passes the
benign controls but fails the adversarial scenarios:

```bash
python examples/black_box/banking_demo.py
safeagenteval run --domain banking --agent session-reference
safeagenteval run --domain banking --agent session-unsafe   # exits 1
```

## Your own agent

Scaffold a starter, point it at your agent and sandbox, certify the
adapter and provider, then run:

```bash
safeagenteval new-session-agent myshop
safeagenteval certify-agent --agent myshop.agent:StarterSessionAgent
safeagenteval certify-state-provider --provider myshop.agent:StarterStateProvider
safeagenteval run --agent myshop.agent:StarterSessionAgent \
  --state-provider myshop.agent:StarterStateProvider --repeats 5 --out runs/
```

One fresh agent instance per run; agent-reported metadata is recorded as
an untrusted claim, never as ground truth. See `docs/agent_contract.md`
and `docs/developer_guide.md`.
