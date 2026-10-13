\# Track C — AI Agent Constitution



\## 1. PROJECT IDENTITY



Project:

Contrastive Speech Analytics \& Temporal Flaw Grounding



Challenge:

Track C — Speech evaluation through contrastive analysis,

temporal flaw grounding, acoustic feature extraction,

reproducible scoring, and actionable feedback.



Primary Goal:



Build one integrated system that compares participant speech

against an effective same-content baseline, detects meaningful

delivery deviations, grounds those deviations to precise

timestamps, explains the evidence causally, and presents the

results through an interactive dashboard.



\---



\# 2. PRIMARY PRODUCT PIPELINE



The canonical pipeline is:



Audio

→ Preprocessing

→ Transcription

→ Forced Alignment

→ Feature Extraction

→ Baseline Normalization

→ Contrastive Comparison

→ Temporal Flaw Detection

→ Severity Estimation

→ Deterministic Scoring

→ Evidence-backed Explanation

→ API Response

→ Dashboard Visualization



An agent MUST NOT silently introduce a competing pipeline.



Any architectural change must be recorded in DECISIONS.md and

approved by the team leader.



\---



\# 3. CORE PROBLEM DEFINITION



The system evaluates DELIVERY, not the factual correctness

or literary quality of the speech.



The system should answer:



1\. Where did delivery deviate from the effective baseline?

2\. Which measurable acoustic behavior changed?

3\. How large was the deviation?

4\. When did the deviation occur?

5\. Why does the deviation represent a delivery flaw?

6\. What actionable feedback should the participant receive?



The output must connect:



timestamp

→ measurable evidence

→ flaw type

→ explanation

→ recommendation



\---



\# 4. CORE FEATURES



The initial analytical feature set is:



\- Pitch / F0

\- MFCCs

\- Energy / loudness-related features

\- Speech rate

\- Pause intervals

\- Vocal clarity or an explicitly documented acoustic proxy



Feature implementations must be centralized.



Do not implement the same feature independently in multiple files,

services, notebooks, or frontend components.



\---



\# 5. CORE FLAW VOCABULARY



Initial supported flaw categories:



\- Too Fast

\- Too Slow

\- Excessive Pause

\- Flat Pitch

\- Pitch Instability

\- Low Energy

\- High Energy

\- Reduced Clarity



These categories may evolve after empirical testing.



Do not add new flaw categories merely because an AI model

suggests them.



A new category requires:



1\. measurable evidence

2\. a detection rule

3\. temporal grounding

4\. a scoring policy

5\. an explanation policy

6\. test coverage

7\. team approval



\---



\# 6. NON-NEGOTIABLE ANALYTICAL RULES



\## 6.1 Deterministic Numerical Analysis



The following must be deterministic:



\- feature extraction

\- normalization

\- baseline comparison

\- deviation calculations

\- flaw detection

\- severity calculation

\- numerical scoring



Same input + same configuration must produce the same result.



Randomness must not affect the final score unless explicitly

controlled by a documented seed or configuration.



\---



\## 6.2 LLM Boundary



LLMs may be used for:



\- converting evidence into natural language

\- generating coaching recommendations

\- summarizing already-calculated findings

\- assisting developers with code

\- assisting documentation



LLMs must NOT invent:



\- timestamps

\- feature values

\- deviation percentages

\- severity values

\- numerical scores

\- evidence



Every numerical statement shown to the user must originate from

the analytical pipeline.



\---



\## 6.3 Evidence Before Explanation



No flaw explanation should exist without measurable evidence.



Bad:



"You need to speak more clearly."



Good:



"12.4–15.8 s: speech rate was 31% above the normalized

baseline, indicating accelerated delivery."



The explanation layer must consume structured analytical evidence.



\---



\# 7. BASELINE PRINCIPLE



A baseline represents effective delivery of the same speech content.



The baseline is not a universal human average.



Comparisons must account for speaker variability where applicable,

especially for pitch and energy.



Do not compare raw absolute speaker characteristics blindly.



Normalization methodology must be documented before final scoring.



\---



\# 8. TEMPORAL GROUNDING PRINCIPLE



A flaw is incomplete without a time interval.



A detected flaw should, where possible, contain:



\- start time

\- end time

\- flaw type

\- severity

\- evidence

\- explanation

\- recommendation



Example:



{

&#x20; "start": 12.4,

&#x20; "end": 15.8,

&#x20; "type": "fast\_speech",

&#x20; "severity": 0.78,

&#x20; "evidence": {

&#x20;   "rate\_delta\_pct": 31

&#x20; },

&#x20; "explanation": "...",

&#x20; "recommendation": "..."

}



Do not report only global statements when temporal evidence is

available.



\---



\# 9. FRONTEND BOUNDARY



The frontend is responsible for:



\- presentation

\- user interaction

\- visualization

\- API communication

\- navigation

\- playback interaction



The frontend must NOT calculate:



\- MFCC

\- pitch

\- speech rate

\- pause metrics

\- flaw severity

\- analytical scores



Analytical truth belongs to the backend.



\---



\# 10. BACKEND BOUNDARY



The backend owns:



\- input validation

\- audio processing orchestration

\- transcription integration

\- alignment

\- feature extraction

\- baseline comparison

\- flaw grounding

\- scoring

\- explanation generation

\- final analysis response



The backend must expose stable, documented APIs.



\---



\# 11. SINGLE SOURCE OF TRUTH



Each concept must have one canonical implementation.



Examples:



Pitch:

→ backend/app/services/features/



Scoring:

→ backend/app/services/scoring/



Grounding:

→ backend/app/services/grounding/



API schemas:

→ backend/app/schemas/



Frontend must consume the canonical backend output.



\---



\# 12. DIRECTORY RESPONSIBILITY



backend/

&#x20;   application and analytical services



frontend/

&#x20;   user interface and visualization



data/

&#x20;   datasets, annotations, processed artifacts



scripts/

&#x20;   offline utilities, dataset generation, evaluation scripts



docs/

&#x20;   architecture, methodology, demo/submission documentation



tests/

&#x20;   integration/end-to-end testing



backend/tests/

&#x20;   backend unit/API testing



\---



\# 13. AI AGENT WORK PROTOCOL



Before starting a task, an agent MUST read:



1\. AGENTS.md

2\. ARCHITECTURE.md

3\. PROJECT\_STATE.md

4\. TASKS.md

5\. DECISIONS.md when relevant



Then determine:



\- assigned task

\- accepted scope

\- files likely to change

\- inputs

\- outputs

\- dependencies

\- test requirements



The agent must not begin implementation before understanding these.



\---



\# 14. TASK SCOPE CONTROL



Agents must work on ONE clearly defined task at a time.



An agent MUST NOT:



\- refactor unrelated code

\- rename large portions of the project unnecessarily

\- change frameworks

\- change API contracts silently

\- rewrite working components without reason

\- create duplicate implementations

\- introduce unrelated features

\- modify another person's active task

\- delete working functionality without justification



If a broader problem is discovered:



1\. complete the current task if possible

2\. document the issue

3\. create a new task

4\. do not silently expand scope



\---



\# 15. FILE-SCOPE CONTROL



Every implementation task should identify:



Allowed files/directories:

\- explicitly listed in the task when practical



If additional files are required, the agent must explain why.



Agents should prefer the smallest safe change.



\---



\# 16. TESTING REQUIREMENT



Important analytical logic must have tests.



At minimum:



\- normal input

\- edge case

\- invalid input where applicable

\- deterministic repeated run



A feature is not complete merely because it executes once.



\---



\# 17. STATE MANAGEMENT



After completing a task, the agent should report:



1\. What changed

2\. Which files changed

3\. What was tested

4\. Test result

5\. Known limitations

6\. Suggested TASKS.md update

7\. Suggested PROJECT\_STATE.md update



The agent may update TASKS.md and PROJECT\_STATE.md only when the

task prompt explicitly permits state synchronization.



Do not automatically modify DECISIONS.md or AGENTS.md.



\---



\# 18. DECISION CONTROL



AGENTS.md and DECISIONS.md are protected project-control files.



An agent may propose changes.



The team leader approves architectural decisions.



An agent MUST NOT silently alter:



\- architecture

\- core pipeline

\- scoring methodology

\- API contracts

\- dataset definition

\- supported flaw taxonomy



\---



\# 19. DEPENDENCY CONTROL



Do not add a package merely because it is convenient.



Before adding a significant dependency, consider:



\- why it is needed

\- whether an existing dependency can solve the problem

\- installation complexity

\- deployment compatibility

\- license implications

\- runtime cost

\- maintenance risk



Significant dependency changes should be recorded in DECISIONS.md.



\---



\# 20. REPRODUCIBILITY



The system should be reproducible across:



\- repeated runs

\- different machines where practical

\- controlled environments

\- deployment



Configuration should be explicit.



Do not hide important thresholds or scoring weights inside

hard-coded unexplained constants.



\---



\# 21. PERFORMANCE PRINCIPLE



Optimize only after correctness is established.



Priority:



1\. correctness

2\. reproducibility

3\. temporal precision

4\. robustness

5\. performance

6\. visual polish



\---



\# 22. SECURITY AND DATA HANDLING



Never commit:



\- API keys

\- passwords

\- secrets

\- private credentials

\- local machine secrets

\- user-sensitive recordings unless intentionally included

&#x20; as part of the public dataset



Use environment variables for secrets.



Use .env.example for required configuration names.



\---



\# 23. DEVELOPMENT PRINCIPLE



Prefer simple, understandable implementations over unnecessary

abstraction.



This is an 8-day hackathon project.



Do not build enterprise complexity without a measurable benefit.



\---



\# 24. AI CODING QUALITY STANDARD



Before declaring a task complete, the agent must verify:



\- code runs

\- imports resolve

\- expected output exists

\- tests pass or manual validation is documented

\- no obvious unrelated files changed

\- API/schema compatibility is preserved

\- project state is not inconsistent



\---



\# 25. WHEN UNCERTAIN



If an agent is uncertain about an architectural decision,

it must NOT guess silently.



It should state:



"Architectural decision required."



Then describe:



\- current situation

\- options

\- recommended option

\- trade-offs

\- affected files



The team leader makes the final decision.



\---



\# 26. PROJECT SUCCESS DEFINITION



The project succeeds when a judge can upload or select a speech

and clearly see:



participant delivery

→ comparison against effective baseline

→ measurable feature difference

→ exact flaw location

→ evidence

→ causal explanation

→ actionable recommendation

→ reproducible score



The system must demonstrate technical evidence rather than

presenting a generic black-box AI score.



\---



\# 27. CURRENT PROJECT STAGE



Stage:

Initialization



Major implementation has NOT yet started.



Do not assume missing technical decisions.



Do not invent unfinished architecture.



When information is missing, identify it explicitly and wait for

the approved project architecture/task.



\# END OF PROJECT CONSTITUTION



