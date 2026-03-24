import json
import os
import re

import google.generativeai as genai
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session as DBSession

from database import get_db
from models import Patient, Session, FlaggedWord, LEVEL_LABELS
from schemas import (
    SimplifyRequest, SimplifyResponse,
    SimilarityRequest, DefinitionRequest, InsightRequest,
)
from routes.patients import auto_level

router = APIRouter(prefix="/api", tags=["ai"])

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Models
_main_model = genai.GenerativeModel("gemini-3-flash-preview")
_light_model = genai.GenerativeModel("gemini-3.1-flash-lite-preview")

LEVEL_RULES = {
    1: """LEVEL-SPECIFIC RULES:
- Replace ALL medical terms with plain everyday words (no jargon whatsoever).
- Use the DEFT substitutions below for every matching term.
- If a medical concept has no common equivalent, explain it in a simple phrase instead of using the term.
- Write as if explaining to someone with no medical background at all.""",

    2: """LEVEL-SPECIFIC RULES:
- Replace most medical terms with plain alternatives using the DEFT substitutions below.
- For terms not in the DEFT list, add a brief plain-language explanation in parentheses on first use.
- Keep the language conversational and approachable.""",

    3: """LEVEL-SPECIFIC RULES:
- Use clear, plain language as the default.
- Keep medical terms where they are commonly known (e.g. "blood pressure", "X-ray"), but define less common ones in parentheses on first use.
- Apply DEFT substitutions for abbreviations and specialist jargon.""",

    4: """LEVEL-SPECIFIC RULES:
- Keep most medical terminology intact.
- Only define terms that a generally educated adult would not know — add a brief parenthetical for those.
- Expand abbreviations on first use (e.g. "PO (by mouth)").""",

    5: """LEVEL-SPECIFIC RULES:
- Preserve the original clinical language almost entirely.
- Only expand uncommon abbreviations (e.g. "SpO2 (blood oxygen level)").
- Do not simplify standard medical terminology.""",
}

DEFT_RULES = """
DEFT corpus substitutions (apply at the appropriate level):
- dyspnea → shortness of breath
- myocardial infarction → heart attack
- hypertension → high blood pressure
- diuretic → water pill
- PO → by mouth
- QD/OD → once a day
- BID → twice a day
- nebulization → breathing treatment
- FEV1/FVC → breathing test
- COPD → COPD (a long-term lung condition)
- corticosteroid → steroid medicine
- SpO2 → blood oxygen level
- ejection fraction → how well your heart pumps
- acute exacerbation → sudden worsening
- empiric → precautionary
"""

BASE_SYSTEM = """You are MedBridge, a health literacy specialist trained on the DEFT corpus.
Your job is to translate clinical text into patient-friendly language.

CRITICAL OUTPUT RULE: Your response must contain ONLY the rewritten patient text. Do NOT include any thinking, reasoning, self-checks, meta-commentary, notes, headers, or preamble. No "Final check", no "Wait", no asterisks, no internal monologue. Just the clean rewritten text — nothing else.

CORE RULES (always apply):
1. Every piece of clinical information in the original MUST appear in your output — never drop dosages, frequencies, measurements, follow-up instructions, or conditions. Accuracy is life-critical.
2. Keep the natural structure and flow of the original — do not fragment sentences or remove paragraphs.
3. Use active voice and a warm, reassuring tone.
4. If the original lists multiple medications, instructions, or findings, your output must list all of them.

{deft_rules}

{level_rules}"""

_def_cache = {}


def _generate(model, prompt: str, system: str = None, max_tokens: int = 1000) -> str:
    """Unified helper to call Gemini and return text."""
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    response = model.generate_content(
        full_prompt,
        generation_config=genai.types.GenerationConfig(
            max_output_tokens=max_tokens,
            thinking_config=genai.types.ThinkingConfig(thinking_budget=0),
        ),
    )
    return response.text.strip()


@router.post("/simplify", response_model=SimplifyResponse)
def simplify_text(req: SimplifyRequest, db: DBSession = Depends(get_db)):
    level = req.difficulty_level
    level_rules = LEVEL_RULES.get(level, LEVEL_RULES[3])
    history_ctx = ""

    if req.patient_id:
        sessions = db.query(Session).filter(Session.patient_id == req.patient_id).all()
        flagged = db.query(FlaggedWord).filter(FlaggedWord.patient_id == req.patient_id).all()
        if sessions:
            fc = {}
            for f in flagged:
                fc[f.word] = fc.get(f.word, 0) + 1
            top = sorted(fc, key=fc.get, reverse=True)[:6]
            top_str = ", ".join(f'"{w}"(×{fc[w]})' for w in top) if top else "none"
            avg_comp = round(sum(s.comprehension_score for s in sessions) / len(sessions))
            note = ("Struggles significantly — use simplest possible language." if avg_comp < 60
                    else "Moderate difficulty — keep sentences short." if avg_comp < 75
                    else "Understands reasonably — ensure clarity.")
            history_ctx = (f"\n\nPATIENT HISTORY: Previously flagged difficult words: {top_str}. "
                           f"Avg comprehension: {avg_comp}%. {note} "
                           f"Actively avoid flagged words or define them clearly.")

    system = BASE_SYSTEM.format(deft_rules=DEFT_RULES, level_rules=level_rules)
    system += history_ctx
    system += "\n\nReturn ONLY the rewritten text, no preamble."

    simplified = _generate(_main_model, req.text, system=system, max_tokens=1000)

    grade, hard_pct = _readability(simplified)
    return SimplifyResponse(simplified=simplified, grade_level=grade, hard_word_pct=hard_pct)


@router.post("/check-similarity")
def check_similarity(req: SimilarityRequest):
    prompt = f"""You are a medical semantic similarity evaluator.

ORIGINAL:
\"\"\"{req.original}\"\"\"

SIMPLIFIED:
\"\"\"{req.simplified}\"\"\"

Respond ONLY with valid JSON (no markdown):
{{
  "overall_score": <0-100>,
  "verdict": "<one sentence>",
  "pairs": [
    {{
      "orig": "<original sentence>",
      "simp": "<corresponding simplified sentence or empty>",
      "status": "<good|changed|lost>",
      "note": "<brief explanation, max 10 words>"
    }}
  ]
}}"""

    raw = _generate(_main_model, prompt, max_tokens=900)
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


@router.post("/define")
def define_word(req: DefinitionRequest):
    """Return a plain-English definition for a medical/complex word."""
    if req.word in _def_cache:
        return _def_cache[req.word]

    prompt = (f'Define the medical/health term "{req.word}" for a patient. '
              'Respond ONLY with JSON: '
              '{"pos":"<noun/verb/adjective>","plain":"<plain English, 1-2 sentences, max 30 words, no jargon>"}')

    raw = _generate(_light_model, prompt, max_tokens=120)
    raw = raw.replace("```json", "").replace("```", "").strip()
    result = json.loads(raw)
    _def_cache[req.word] = result
    return result


@router.post("/patient-insight")
def patient_insight(req: InsightRequest, db: DBSession = Depends(get_db)):
    """AI profile insight for writer side."""
    p = db.query(Patient).filter(Patient.id == req.patient_id).first()
    if not p:
        raise HTTPException(404, "Patient not found")

    sessions = db.query(Session).filter(Session.patient_id == req.patient_id).all()
    flagged = db.query(FlaggedWord).filter(FlaggedWord.patient_id == req.patient_id).all()

    if not sessions:
        return {"insight": "New patient — no history yet. Starting at Normal level.", "predicted": []}

    fc = {}
    for f in flagged:
        fc[f.word] = fc.get(f.word, 0) + 1
    top_str = ", ".join(f"{w}(×{fc[w]})" for w in sorted(fc, key=fc.get, reverse=True)[:8]) or "none"
    avg_comp = round(sum(s.comprehension_score for s in sessions) / len(sessions))
    avg_time = round(sum(s.read_time_seconds for s in sessions) / len(sessions))
    lv = auto_level(sessions, flagged)

    prompt = (f'Medical reading analyst. Patient "{p.name}": {len(sessions)} sessions, '
              f'avg comprehension {avg_comp}%, avg read time {avg_time}s, '
              f'flagged words: {top_str}, recommended level {lv}/5.\n\n'
              f'Write 2 concise sentences (max 40 words): reading profile + one writing recommendation.\n'
              f'Then: PREDICT: 6 medical/complex words this patient is likely to struggle with.\n'
              f'Format:\n[2 sentences]\nPREDICT: word1, word2...')

    text = _generate(_light_model, prompt, max_tokens=350)
    parts = text.split("PREDICT:")
    insight = parts[0].strip()
    predicted = [w.strip() for w in parts[1].split(",") if w.strip()] if len(parts) > 1 else []
    flagged_set = set(fc.keys())
    return {
        "insight": insight,
        "predicted": [{"word": w, "prev_flagged": w.lower() in flagged_set} for w in predicted],
    }


@router.post("/analytics-summary")
def analytics_summary(req: InsightRequest, db: DBSession = Depends(get_db)):
    """AI-generated writing recommendations based on full patient history."""
    p = db.query(Patient).filter(Patient.id == req.patient_id).first()
    if not p:
        raise HTTPException(404, "Patient not found")

    sessions = db.query(Session).filter(Session.patient_id == req.patient_id).all()
    flagged = db.query(FlaggedWord).filter(FlaggedWord.patient_id == req.patient_id).all()

    fc = {}
    for f in flagged:
        fc[f.word] = fc.get(f.word, 0) + 1
    top_str = ", ".join(f"{w}(×{fc[w]})" for w in sorted(fc, key=fc.get, reverse=True)[:6]) or "none"
    avg_comp = round(sum(s.comprehension_score for s in sessions) / len(sessions)) if sessions else 0
    avg_time = round(sum(s.read_time_seconds for s in sessions) / len(sessions)) if sessions else 0
    sus = [s.self_understanding for s in sessions if s.self_understanding]
    avg_self = round(sum(sus) / len(sus), 1) if sus else "N/A"
    trend = (sessions[-1].comprehension_score - sessions[0].comprehension_score) if len(sessions) > 1 else 0
    lv = auto_level(sessions, flagged)
    lv_label = LEVEL_LABELS.get(lv, "Normal")

    prompt = (f'Health literacy analyst. Patient "{p.name}": {len(sessions)} sessions, '
              f'avg comprehension {avg_comp}%, trend {trend:+}%, avg read time {avg_time}s, '
              f'self-reported understanding {avg_self}/4, flagged words: {top_str}, '
              f'recommended level {lv}/5 ({lv_label}).\n\n'
              f'Write a concise 2-3 sentence profile: reading ability, difficulty patterns, trajectory.\n'
              f'Then write 3-4 specific writing recommendations. Start each with "→".')

    text = _generate(_light_model, prompt, max_tokens=400)
    parts = text.split("→")
    summary = parts[0].strip()
    bullets = [b.strip() for b in parts[1:] if b.strip()]
    return {"summary": summary, "recommendations": bullets}


# ── Readability helpers ──

def _syllables(word: str) -> int:
    word = word.lower()
    word = ''.join(c for c in word if c.isalpha())
    if not word:
        return 0
    if len(word) <= 3:
        return 1
    word = re.sub(r'(?:[^laeiouy]es|ed|[^laeiouy]e)$', '', word)
    word = re.sub(r'^y', '', word)
    m = re.findall(r'[aeiouy]{1,2}', word)
    return len(m) if m else 1


def _readability(text: str):
    sentences = [s for s in re.split(r'[.!?]+', text) if len(s.strip()) > 4]
    words = re.findall(r'\b\w+\b', text)
    if not words or not sentences:
        return 0.0, 0
    sylls = sum(_syllables(w) for w in words)
    avg_sl = len(words) / len(sentences)
    avg_sw = sylls / len(words)
    fkg = round(0.39 * avg_sl + 11.8 * avg_sw - 15.59, 1)
    hard = sum(1 for w in words if _syllables(w) >= 3)
    hard_pct = round(hard / len(words) * 100)
    return max(0.0, fkg), hard_pct
