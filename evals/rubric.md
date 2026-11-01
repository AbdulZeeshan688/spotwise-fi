# LLM-judge rubric (EVAL-04)

The judge scores each answer from 1 (bad) to 5 (excellent) on four criteria. It sees the
question, the agent's answer **and the raw tool outputs**, so it can check where every
number came from.

Score each criterion on its own. When a criterion doesn't apply (for example "time range"
for a polite refusal of an off-topic question), score it **5**.

## clarity
- **5**: Direct answer first, short, easy to follow, right units (c/kWh, €).
- **3**: Correct but wordy, buried, or slightly confusing.
- **1**: Hard to understand, or doesn't answer the question.

## states_range
- **5**: Clearly says which time range it used (dates/times, Finnish time), and mentions
  partial data when a tool's coverage was incomplete.
- **3**: The range is only implied ("today") or a partial-data warning is missing.
- **1**: No range, or the wrong range.

## states_vat
- **5**: Says whether prices include VAT (or that a cost is incl./excl. VAT).
- **3**: Ambiguous ("about 5 cents").
- **1**: Not mentioned, or wrong (says incl. VAT when the tool returned excl.).

## no_invented_numbers
- **5**: Every number, time and date in the answer appears in (or is a plain rounding of)
  the tool outputs or the question.
- **3**: One small derived number (e.g. a subtraction of two tool values).
- **1**: Prices, times or dates that no tool returned, or a guess about unpublished prices.

## overall
The mean of the four scores (computed in code, not by the judge).
