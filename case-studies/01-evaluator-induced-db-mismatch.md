# When a Zero Reward Does Not Mean the Agent Failed

## Summary

I evaluated a tool-using agent on the `update_task_with_user_tools` task in the τ²-bench mock domain. The run received a total reward of `0.0`, but the trace showed that the agent completed the requested work correctly.

The failure came from the database evaluator. The required agent action passed, the final environment assertion passed, and the task was updated successfully. However, the user-side database hash did not match the evaluator's gold state after the simulated user dismissed a notification.

This case shows why a benchmark score should be treated as a signal to investigate, not as a complete explanation of agent behavior.

## Experimental setup

| Component | Configuration |
|---|---|
| Benchmark | τ²-bench 1.0.1 |
| Benchmark commit | `4ce7c0397c1eb65c9bbe59aeacfe1ca44a1cd699` |
| Domain | `mock` |
| Task | `update_task_with_user_tools` |
| Agent model | DeepSeek V4.1 Flash through OpenRouter |
| User simulator | DeepSeek V4.1 Flash through OpenRouter |
| Observability | LangSmith |
| Temperature | `0` |
| Seed | `42` |

The task asked the simulated user to check an assigned-task notification, request that `task_1` be marked as completed, and dismiss `notif_1` after the agent confirmed the update.

## Evaluation contract

The task used three reward components:

1. **ACTION** — the assistant must call `update_task_status` with `task_id="task_1"` and `status="completed"`.
2. **ENV_ASSERTION** — `notif_1` must end with the expected `read` status.
3. **DB** — the final agent and user database hashes must match the evaluator's gold environment.

All three components gated the final reward:

```text
total reward = DB × ACTION × ENV_ASSERTION
```

## What happened

The LangSmith trace showed the following sequence:

1. The simulated user called `check_notifications`.
2. The environment returned `notif_1`, linked to `task_1`.
3. The user asked the agent to mark `task_1` as completed.
4. The agent called:

   ```json
   {
     "name": "update_task_status",
     "arguments": {
       "task_id": "task_1",
       "status": "completed"
     }
   }
   ```

5. The tool returned `task_1` with `status="completed"`.
6. The agent accurately confirmed the update.
7. The simulated user called `dismiss_notification` for `notif_1` as instructed.
8. The notification assertion passed.

## Result breakdown

| Component | Score | Evidence |
|---|---:|---|
| ACTION | `1.0` | The required tool and arguments matched exactly. |
| ENV_ASSERTION | `1.0` | The required notification-state assertion passed. |
| DB | `0.0` | The user-side database hash differed from the gold environment. |
| Total reward | `0.0` | `0.0 × 1.0 × 1.0 = 0.0` |

The agent-side database matched the expected state. The mismatch was isolated to the user-side database after the required notification dismissal.

## Diagnosis

The zero reward does not identify an agent-action failure:

- The agent selected the required tool.
- The tool arguments were correct.
- The tool executed successfully.
- The task reached the required `completed` state.
- The simulated user followed the scenario instructions.
- The explicit environment assertion passed.

The likely issue is an inconsistency between the user-side state produced by the full simulation and the user-side state represented by the evaluator's gold environment. The exact database comparison failed even though the observable task requirements passed.

I classify this run as a **likely evaluator-induced failure**, rather than a demonstrated agent failure. Confirming a benchmark defect would require reproducing the mismatch and inspecting the gold-state construction across additional runs.

## Why this matters

A single aggregate score hides the source of failure. If I had stopped at `reward=0.0`, I would have incorrectly concluded that the agent failed the task.

The useful workflow was:

1. Read the task's evaluation contract.
2. Decompose the aggregate reward.
3. Inspect the model decision, tool inputs, and tool outputs.
4. Compare the observed trajectory with each grader independently.
5. Separate agent failures from evaluator and ground-truth failures.

This distinction matters in production evaluation systems. An unreliable grader can send teams toward prompt or model changes when the actual problem is the evaluation harness.

## Reproduction

From the `tau-study` directory:

```bash
./study inspect --domain mock --task-id update_task_with_user_tools
./study run --domain mock --task-id update_task_with_user_tools
```

Then inspect the generated `results.json` and the corresponding LangSmith root trace:

- `task.evaluation_criteria` defines the expected action and environment assertion.
- `reward_info.action_checks` records the action match.
- `reward_info.env_assertions` records whether the final condition was met.
- `reward_info.db_check` records the final database comparison.
- The child tool runs show the actual inputs and returned state.

API keys and full raw traces are excluded from the repository.

## Limitations and next step

This is one deterministic run in a mock domain. It does not establish a general failure rate or prove that every zero reward with the same signature is an evaluator defect.

The next step is to run a small repeated evaluation set containing:

- clean successes,
- genuine agent-action failures, and
- suspected evaluator-induced failures.

That comparison will support a failure taxonomy and measure how often aggregate reward disagrees with trace-level evidence.
