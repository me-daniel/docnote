# DoctorTalk features

Planned and existing capabilities. For implementation tasks see [TODO.md](TODO.md).

## Writer

- Simplify clinical text to a chosen reading level with patient context when a patient is selected.
- Patient insight and predicted difficult words from session history.
- Approve and send simplified text to the patient reading view.

## Patient

- Read doctor-authored plain-language text with word-level help and comprehension check-in.
- Sessions record reading time, flagged words, and self-reported understanding.

## Analytics

**Chronic context (familiar ground)**  
Surface conditions and topic areas the patient already engages with often, inferred from repeated terms, stable comprehension on similar content, and recurring vocabulary from sessions. Helps the writer avoid over-explaining what the patient already lives with (for example long-term diagnoses or standing medications).

**New ground (topics learned over time)**  
Show themes that appear more recently or show improving comprehension or shorter read times compared to earlier sessions. Useful to see what the patient is newly exposed to versus what is old news.

**Other analytics (light touch)**  
- Trend of comprehension and reading time across sessions.  
- Word frequency and hover time as difficulty signals.  
- Recommended reading level with a short rationale.

**Demo data**  
The server seeds a test patient **Uwe** with several reading sessions when the database is empty. The Analytics tab selects **Uwe** by default so charts and tables load without manual setup.

These analytics items mix confirmed signals from stored session data with future interpretation logic. Ship them incrementally and label uncertainty when inference is heuristic.
