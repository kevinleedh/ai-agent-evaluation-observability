# Evaluating Reply Priority in Email Triage

## Summary

I evaluated an email triage agent that labels messages `respond`, `notify`, or `ignore`. A reminder from HR also asked the recipient to confirm receipt by email. The original policy described HR deadline reminders as `notify` but did not say which rule should win when the message explicitly requested a reply.

In a two-email contrast test, the agent labeled both the ordinary reminder and the reply-request version `notify`. I added a rule giving explicit email reply requests priority, then tested the original and revised policies on the same nine synthetic HR emails, three times each. The original completed 25 of 27 runs with the expected label; the revision completed 27 of 27. The difference is evidence from this small test, not a production reliability claim.

The diagnostic pair differed in one sentence. The ordinary expense-report reminder said recipients could contact HR if they had questions; its expected and observed label was `notify`. Replacing that sentence with “Please reply to this email to confirm whether you can submit your expense reports by Friday” changed the expected label to `respond`, but the original agent still returned `notify`. This exposed the rule conflict before the held-out test.

## Evaluation setup

The agent used DeepSeek V4.1 Flash through OpenRouter. LangSmith stored the dataset, experiments, and traces. The held-out set contained nine synthetic emails: four with a direct reply request (`respond`), four important notices without one (`notify`), and one optional promotion (`ignore`). I assigned the reference labels by applying the stated triage rules. These examples were separate from the two emails used to identify the rule conflict.

The policy change was narrow: an HR deadline reminder remains `notify` unless it explicitly asks the recipient to reply or confirm by email. Submitting a form elsewhere or offering to answer questions does not itself require `respond`.

Each policy saw the same nine emails three times. A run passed only when it completed without an error **and** its parsed classification matched the reference label. Consistency means all three recorded outcomes for an email were identical; an error counts as a distinct outcome. Neither measure alone explains why a run failed.

| Policy | Expected labels returned | Execution errors | Cases with consistent outcomes across three runs |
|---|---:|---:|---:|
| Original | 25/27 | 2 | 8/9 |
| Revised | 27/27 | 0 | 9/9 |

## Failure analysis

Both original-policy errors occurred on the same email: “Open enrollment closes Friday. Please reply to confirm that you received this notice.” Its reference label was `respond`. Across three repetitions, the recorded outcomes were `ERROR`, `respond`, and `ERROR`.

The two failed traces reported `Model returned no structured classification`. Inspecting the model calls revealed more than the top-level error: in both failed calls, the model wrote `classification: notify` in text and justified it by prioritizing the HR deadline-reminder rule. The application could not parse those responses into the required structured decision, so the experiment recorded errors rather than `notify` outputs. The successful repetition returned a structured `Decision` with `classification: respond` and cited the explicit confirmation request.

This separates two observed failure modes: the model applied the wrong rule in the failed calls, and the output was unusable by the application. The 25/27 score treats both as execution failures; it does not show the mistaken `notify` decisions inside those traces. Reading the model output was necessary to identify the rule-priority problem.

## What changed and what remains uncertain

With the revised rule, all three repetitions of that email returned a structured `respond` decision. The other eight examples also returned their expected labels in all three repetitions. The result supports the revised policy on this dataset, but the small synthetic sample cannot establish a general error rate. It also cannot show whether the revised wording itself prevented the output-format errors or whether those errors would recur under more repetitions.

A production evaluation would track classification errors, structured-output failures, and repeated-run consistency separately, then test on reviewed real examples before relying on the agent for live email handling.

## Evidence

- [LangSmith held-out experiment comparison](https://smith.langchain.com/o/19a23f7a-3509-4ad2-b3fa-a1481e553b10/datasets/120caa32-a468-4931-bad3-489b2a1c7227/compare?selectedSessions=2793b580-0087-420d-97c5-dd8993f61186%2C73d9686a-7d10-4a02-84e1-f3e880ff0ac9)
- Evaluation script and results retained locally in `email-evaluation-lab`; they are not part of this repository.
- [Official example source at the commit used](https://github.com/langchain-ai/agents-from-scratch/tree/603fc7a4ac6119004f43894395e504a1fefcc6c0)
