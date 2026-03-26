# DoctorTalk TODO

**Process:** Anything not finished in the current change belongs here. Do not rely on memory or chat for follow-ups.

## API: Gemini output length

- [x] **Simplify** uses a high `max_output_tokens` (8192) so long clinical notes are not cut off mid-sentence. Earlier default was 1000 and truncated the model response.
- [ ] If **check-similarity** JSON is incomplete on very long texts, raise `max_output_tokens` in `_generate` for that route (currently 900).

## UI: light and dark mode

- [x] **Theme toggle** in the nav (persists `doctortalk-theme` in `localStorage`, respects `prefers-color-scheme` on first visit). Legacy `medbridge-theme` is migrated once.
- [x] **`data-theme="dark"` / `"light"`** on `<html>` with CSS variables in `static/css/style.css`.
- [ ] Optional polish: theme-colored chart fills in `app.js` canvas helpers (`drawHeat`, `drawFlagList`) when `data-theme` is light.
- [ ] Optional: sync `<meta name="color-scheme">` with the active theme for form controls.

## DEFT corpus plus patient context (before or inside Gemini)

### Phase 0: Licensing and format

- [ ] Obtain the canonical DEFT source (paper, supplement, or author release) and confirm redistribution terms.
- [ ] Normalize to an internal table or file, for example `{ term, plain_phrase, notes }`.

### Phase 1: Retrieval before generation

- [ ] Build a matcher over clinician input (exact phrase, then fuzzy or n-gram fallbacks).
- [ ] Inject a compact **DEFT block** into the simplify system prompt (cap rows to a token budget).
- [ ] Log which DEFT rows were attached per request (audit trail).

### Phase 2: Personalized patient data (already partly in app)

Existing: `FlaggedWord`, `Session.word_frequencies`, `Session.hover_times`, comprehension, level.

- [ ] Formalize a **patient context** object from the DB (top flagged terms, weighted by `word_frequencies`, trend from sessions).
- [ ] Append **Patient context** to the Gemini system prompt (same route as today’s `history_ctx`, but structured and bounded).
- [ ] Optional later: store accepted simplify pairs and retrieve similar past lines (embedding search).

### Phase 3: Generation contract

- [ ] Keep a single simplify entrypoint: `system + DEFT_RETRIEVED + PATIENT_CONTEXT + user text`.
- [ ] Version prompts in code or config for reproducibility.

## ClinicalBERT (or clinical embeddings) after generation

- [ ] Sentence-split original and simplified text with the same rules.
- [ ] Align sentences (greedy or DP by cosine similarity).
- [ ] Load [medicalai/ClinicalBERT](https://huggingface.co/medicalai/ClinicalBERT) (or a clinical sentence embedding model) via `transformers`, mean-pool hidden states, compute cosine similarity per pair.
- [ ] Aggregate (mean and min) and return alongside optional Gemini narrative check.
- [ ] Add `torch` / `transformers` to the project and cache the model in process.

### Honest labeling

- [ ] UI copy: distinguish **embedding similarity** from LLM self-judgment and from “clinical safety”.

## Ops

- [ ] Feature-flag heavy models so dev machines can run UI without GPU.
