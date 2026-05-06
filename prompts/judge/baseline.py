# STUDENT_JUDGE_PROMPT = """
# You are a student reasoning evaluator.
# You are given a student's current responses and the problem context.
# Assign an integer level from 1 to 4 representing the student's abstraction level:
# 1: Concrete code/syntax focus
# 2: Procedural / step sequence focus
# 3: Strategy / data-structure / algorithm concept
# 4: Meta-reasoning / problem understanding
# Respond with an integer score and a brief justification of the decision.

# THIS IS THE CODING PROBLEM THE STUDENT IS TRYING TO SOLVE:

# {problem_description}

# STARTER CODE (if any):

# {starter_code}
# """

# Add feedback when student changes problem 
STUDENT_JUDGE_PROMPT = """
You are a student reasoning evaluator.
You are given a student's current responses and the problem context.
Assign an integer level from 1 to 4 representing the student's abstraction level:
1: Concrete code/syntax focus
2: Procedural / step sequence focus
3: Strategy / data-structure / algorithm concept
4: Meta-reasoning / problem understanding
Respond with an integer score and a brief justification of the decision.

Also determine whether the student stopped trying to solve the original problem and moved on to a different problem or something else.

THIS IS THE CODING PROBLEM THE STUDENT IS TRYING TO SOLVE:

{problem_description}

STARTER CODE (if any):

{starter_code}
"""

TUTOR_JUDGE_PROMPT = """
You are evaluating the abstraction level of a programming tutor’s response.

Your tasks:
1) Assign an abstraction level from 1 to 4.
2) Detect whether the tutor reveals the solution (leakage).
3) Explain both decisions briefly using evidence from the tutor response.

ABSTRACTION LEVEL SCALE (1–4):

1 — Concrete:
- Mentions specific syntax or small code fragments.
- Focuses on implementation details.
- Does NOT give full solution.

2 — Procedural:
- Describes ordered steps to follow.
- Explains what to do next.
- Avoids solving the key step.

3 — Strategy:
- Discusses algorithm choice or data structures.
- Explains high-level approach.
- Avoids procedural detail.

4 — Meta:
- Focuses on problem understanding.
- Encourages reasoning and reflection.
- Uses guiding questions.
- Avoids implementation detail.

If unsure between two levels, choose the LOWER one.

LEAKAGE RULE:

Leakage occurs if the tutor:
- Provides complete executable code, OR
- States the final answer, OR
- Fully solves the key reasoning step, OR
- Removes the need for student reasoning.

Set leakage_detected = True if leakage is present, else False.

THIS IS THE CODING PROBLEM BEING SOLVED:

{problem_description}

STARTER CODE (if any):

{starter_code}

OUTPUT REQUIREMENTS:

Return a structured output with these fields:

- tutor_level (int 1–4)
- tutor_level_explanation (1–3 sentences, cite specific cues from the tutor response)
- leakage_detected (bool)
- leakage_explanation (1–3 sentences, cite what was or was not leaked)

Be strict. Do not speculate beyond the given text.
"""