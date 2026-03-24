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

LEVEL_CONFIG = {
    1: {"label": "Very Easy — Grade 3", "desc": "very simple, very short sentences", "max_words": 13},
    2: {"label": "Easy — Grade 5",      "desc": "simple everyday language",          "max_words": 17},
    3: {"label": "Normal — Grade 7",    "desc": "clear and plain language",          "max_words": 19},
    4: {"label": "Advanced — Grade 9",  "desc": "somewhat detailed language",        "max_words": 23},
    5: {"label": "Complex — Clinical",  "desc": "clinically detailed",              "max_words": 30},
}

DEFT_RULES = """
DEFT corpus substitutions (apply these):
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

_def_cache = {}


def _generate(model, prompt: str, system: str = None, max_tokens: int = 1000) -> str:
    """Unified helper to call Gemini and return text."""
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    response = model.generate_content(
        full_prompt,
        generation_config=genai.types.GenerationConfig(max_output_tokens=max_tokens),
    )
    return response.text.strip()


@router.post("/simplify", response_model=SimplifyResponse)
def simplify_text(req: SimplifyRequest, db: DBSession = Depends(get_db)):
    lv = LEVEL_CONFIG.get(req.difficulty_level, LEVEL_CONFIG[3])
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

    system = f"""You are MedBridge, a health literacy specialist trained on the DEFT corpus.
Rewrite clinical text for a patient at level: {lv['label']}.

RULES:
1. Preserve ALL clinical meaning — accuracy is life-critical.
2. Use {lv['desc']}. Max sentence: {lv['max_words']} words.
3. Active voice. Short paragraphs (2-3 sentences max).
4. {DEFT_RULES}
5. Define any remaining medical terms in parentheses on first use.
6. Warm, reassuring tone.{history_ctx}

Return ONLY the simplified text, no preamble."""

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
