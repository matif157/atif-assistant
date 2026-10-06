# Session documentation and prompt templates

Reusable structures for working with an AI assistant on a project. Stored here
so the format is available next time instead of being rewritten each session.

Two parts: a template for handing over a project, and a checklist for closing a
session out.

---

## Project handover template

Copy this, replace the bracketed sections, send it.

```
<continue_carefully>

# PROJECT: [name]

## OVERVIEW
[What this is and what success looks like.]

## MY ROLE vs AI'S ROLE
- What I do: [decisions, credentials, things only you can do]
- What the AI does: [code, copy, research, analysis]
- Decision points: [where you stop and choose]

## TECHNICAL SPECIFICATIONS
- Platform and stack: [...]
- Current state: [what exists today]
- Desired state: [what should exist]
- Constraints: [hosting limits, budget, privacy, time]

## TASKS
[Numbered, ordered by priority. One task per line.]

## SUCCESS CRITERIA
[How you will know each task is done. Be concrete enough to be checked.]

## COMMUNICATION
- Format: [exact copy vs explanation vs code only]
- Confirm before: [anything destructive or outward-facing]
- Escalate when: [what should stop work and come back to me]

## CONSTRAINTS
[Safety, privacy, budget, or platform limits.]
```

---

## Session close-out checklist

Run this at the end of a working session so the next one starts from facts
rather than recollection.

- [ ] Every claim of "done" is verified against a live source, not a summary.
- [ ] Anything deployed is reachable right now; note the HTTP status.
- [ ] Anything claimed as updated is confirmed in the deployed file, not just
      in the local edit.
- [ ] Files created and where they live.
- [ ] URLs touched, with current state.
- [ ] Open questions, stated as questions rather than assumptions.
- [ ] Next actions, ordered.

The most common failure is recording a link as updated when the deployed file
still holds the old value. Check the deployed artifact, not the intent.

---

## Request formats

**Information**

```
I need help understanding [topic]. Provide key concepts, the step-by-step
process, important considerations, and a quick reference.
```

**Exact copy or code**

```
I need [specific output]. Provide the exact text or code, what to replace,
where it goes, and how to test it.
```

**Strategy**

```
I am working on [goal]. Define scope and objectives, give a roadmap, identify
obstacles, and suggest success metrics.
```

**Platform changes**

```
I need to update [platform]. Give exact steps, what to change, what to leave
alone, and how to confirm it worked.
```

**Feature work**

```
I want [feature] on [platform]. Provide the code or config, where to place it,
what to customise, how to test it, and how to revert.
```

---

## Operating principles

- Accurate and verified information over confident-sounding claims.
- Step-by-step guidance with the reasoning stated.
- Consistency across sessions; record what changed rather than assuming.
- Respect the user's decisions; present options, do not push.
- Never guess. Ask when the answer changes what gets built.

## Constraints worth stating up front

Say these explicitly when they apply, because an assistant cannot infer them:

- **Read-only mode** — cannot edit, create or modify files. Text output only.
- **No private account access** — work from what is pasted in.
- **Confirm before outward-facing actions** — deployments, profile changes,
  anything sent to a third party.

When a constraint is not stated, assume it is not in force. An assistant that
believes it is read-only will describe changes instead of making them, which
looks like agreement but leaves the work undone.