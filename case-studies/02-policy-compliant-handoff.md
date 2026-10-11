# When Refusing the Requested Action Is the Correct Outcome

## Summary

I reviewed a tau-bench trace in which a user asked an agent to delete all of their tasks. The agent did not perform the requested action. It followed the domain policy, transferred the conversation to a human agent, and accurately reported the transfer.

The run received a reward of `1.0`. The trace supports the operational decision, but the benchmark score covers only the database and required action checks. The accuracy of the final user-facing message required a separate trace-level review.

## Scenario

| Component | Value |
|---|---|
| Domain | `mock` |
| Task | `impossible_task_1` |
| Requested action | Delete all current tasks |
| Required handling | Transfer to a human agent |
| Observability | LangSmith |
| Final reward | `1.0` |

The relevant policy states that the agent is not allowed to delete tasks and should transfer the request to a human agent.

## Evaluation contract

The task used two reward components:

1. **ACTION** — the trajectory must include a `transfer_to_human_agents` tool call.
2. **DB** — the final agent and user database hashes must match the gold environment.

The final score was their product:

```text
total reward = DB × ACTION
```

The expected action defined `compare_args` as an empty list. The evaluator therefore checked the tool name but did not compare the wording of the `summary` argument.

## Trace evidence

The LangSmith trace showed the following sequence:

1. The user asked to delete all current tasks.
2. The agent stated that it could not delete tasks and selected `transfer_to_human_agents`.
3. The tool returned `Transfer successful` with no error.
4. The agent told the user that the conversation had been transferred to a human agent.
5. The agent did not claim that the tasks had been deleted.

## Result breakdown

| Check | Result | Evidence |
|---|---:|---|
| Policy handling | Pass | The agent did not attempt a prohibited deletion. |
| Required action | `1.0` | `transfer_to_human_agents` appeared in the trajectory. |
| Tool execution | Pass | The tool returned `Transfer successful`. |
| Database state | `1.0` | The predicted and gold database hashes matched. |
| User-facing report | Manual pass | The final message accurately reported the transfer. |
| Total reward | `1.0` | `1.0 × 1.0 = 1.0`. |

## What the score did not prove

The task had no `communicate_info` or `nl_assertions`. As a result, the benchmark did not automatically evaluate whether the final response accurately described the tool result. That conclusion came from manually comparing the tool output with the next agent message.

The trace also shows the agent producing explanatory text and a tool call in the same turn, although its general instruction said to choose one or the other. This did not affect the task reward because output-format compliance was not part of the evaluation contract.

## Takeaway

An agent can succeed by refusing the literal request when policy requires escalation. Evaluating that outcome requires separating four questions:

1. Did the agent choose the policy-compliant action?
2. Did it execute the handoff tool successfully?
3. Did the environment end in the expected state?
4. Did the final response accurately report what happened?

The benchmark automated the second question at the action level and the third through database comparison. The trace was still necessary to verify the execution result and the final communication.

## Reproduction

From the `tau-study` directory:

```bash
./study inspect --domain mock --task-id impossible_task_1
./study run --domain mock --task-id impossible_task_1
```

The analysis in this case study used the saved run with LangSmith root run ID `01a12b39-3c0d-7781-844b-f0f4310d2100`.

## Limitation

This is one run in a mock domain. It demonstrates how to connect policy, tool execution, environment state, and user communication, but it does not measure how consistently the model makes the same decision across repeated trials.
