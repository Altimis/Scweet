The engineering documents. Keep each document short and correct, or delete it.

> This document uses ASD-STE100 Simplified Technical English. All documents in this directory use it.

| Directory | Rule |
|---|---|
| `findings/` | The result of an investigation. The name is `YYYY-MM-DD-<topic>.md`. A finding gives the evidence and the command that produced it. If a later test contradicts a finding, correct the file and record what changed. |
| `decisions/` | One file for each decision. It gives the context, the options, the decision, and the condition to examine it again. The name is `YYYY-MM-DD-<slug>.md`. Add a file. Do not rewrite history. |
| `plans/` | The plan for a piece of work. The name is `YYYY-MM-DD-NNN-<type>-<name>.md`. The type is `feat`, `fix`, `chore`, or `spike`. Git records the progress, not the body of the plan. |
| `reference/` | A long description of how something works. Delete reference material that is no longer correct rather than keep it. |


## The rule that matters most

**Give the command, not only the claim.** A reader must be able to repeat a measurement. A finding that says
"the run is slow" is worth nothing. A finding that says "an order of 20,000 tweets delivered 4,760, then 0, then
4,700, from `python scripts/compare.py --max-items 20000`" is worth the file.

Record the date of every measurement. A number about X is true on a day, not for ever.
