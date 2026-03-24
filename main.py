from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
import anthropic
import json

from database import init_db, get_db
from models import Patient, Session, FlaggedWord
from sqlalchemy.orm import Session as DBSession
from fastapi import Depends

app = FastAPI(title="MedBridge API", version="1.0.0")

# Mount static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Anthropic client
client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

# ── Startup ──
@app.on_event("startup")
def startup():
    init_db()

# ── Serve frontend ──
@app.get("/", response_class=HTMLResponse)
def serve_app(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# ══════════════════════════════════════
# PATIENT ROUTES
# ══════════════════════════════════════

class PatientCreate(BaseModel):
    name: str

class PatientOut(BaseModel):
    id: int
    name: str
    session_count: int
    avg_comprehension: Optional[float]
    recommended_level: int
    top_flagged: list[str]

@app.get("/api/patients", response_model=list[PatientOut])
def list_patients(db: DBSession = Depends(get_db)):
    patients = db.query(Patient).all()
    return [_patient_out(p, db) for p in patients]

@app.post("/api/patients", response_model=PatientOut)
def create_patient(data: PatientCreate, db: DBSession = Depends(get_db)):
    p = Patient(name=data.name.strip())
    db.add(p)
    db.commit()
    db.refresh(p)
    return _patient_out(p, db)

@app.get("/api/patients/{patient_id}", response_model=PatientOut)
def get_patient(patient_id: int, db: DBSession = Depends(get_db)):
    p = db.query(Patient).filter(Patient.id == patient_id).first()
    if not p:
        raise HTTPException(404, "Patient not found")
    return _patient_out(p, db)

def _patient_out(p: Patient, db: DBSession) -> PatientOut:
    sessions = db.query(Session).filter(Session.patient_id == p.id).all()
    avg_comp = None
    if sessions:
        avg_comp = round(sum(s.comprehension_score for s in sessions) / len(sessions), 1)
    flagged = db.query(FlaggedWord).filter(FlaggedWord.patient_id == p.id).all()
    fc = {}
    for f in flagged:
        fc[f.word] = fc.get(f.word, 0) + 1
    top = sorted(fc, key=fc.get, reverse=True)[:3]
    return PatientOut(
        id=p.id,
        name=p.name,
        session_count=len(sessions),
        avg_comprehension=avg_comp,
        recommended_level=_auto_level(sessions, flagged),
        top_flagged=top,
    )

def _auto_level(sessions, flagged) -> int:
    if not sessions:
        return 3
    recent = sessions[-3:]
    avg_comp = sum(s.comprehension_score for s in recent) / len(recent)
    avg_flagged = sum(s.flagged_word_count for s in recent) / len(recent)
    avg_self = sum(s.self_understanding for s in recent) / len(recent)
    if avg_comp < 50 or avg_flagged > 6 or avg_self < 1.7:
        return 1
    if avg_comp < 65 or avg_flagged > 3.5 or avg_self < 2.2:
        return 2
    if avg_comp >= 88 and avg_flagged < 0.5 and avg_self >= 3.5:
        return 5
    if avg_comp >= 78 and avg_flagged < 1:
        return 4
    return 3

# ══════════════════════════════════════
# SESSION ROUTES
# ══════════════════════════════════════

class SessionCreate(BaseModel):
    patient_id: int
    comprehension_score: int
    read_time_seconds: int
    self_understanding: int          # 1-4
    difficulty_level: int            # 1-5
    flagged_words: list[str]
    word_frequencies: dict           # word -> count of hard words in text
    hover_times: dict                # word -> ms hovered

class SessionOut(BaseModel):
    id: int
    patient_id: int
    date: str
    comprehension_score: int
    read_time_seconds: int
    self_understanding: int
    difficulty_level: int
    flagged_word_count: int

@app.post("/api/sessions", response_model=SessionOut)
def create_session(data: SessionCreate, db: DBSession = Depends(get_db)):
    p = db.query(Patient).filter(Patient.id == data.patient_id).first()
    if not p:
        raise HTTPException(404, "Patient not found")

    s = Session(
        patient_id=data.patient_id,
        comprehension_score=data.comprehension_score,
        read_time_seconds=data.read_time_seconds,
        self_understanding=data.self_understanding,
        difficulty_level=data.difficulty_level,
        flagged_word_count=len(data.flagged_words),
        word_frequencies=json.dumps(data.word_frequencies),
        hover_times=json.dumps(data.hover_times),
    )
    db.add(s)
    db.flush()

    # Save flagged words
    for word in data.flagged_words:
        fw = FlaggedWord(patient_id=data.patient_id, session_id=s.id, word=word.lower())
        db.add(fw)

    db.commit()
    db.refresh(s)
    return _session_out(s)

def _session_out(s: Session) -> SessionOut:
    return SessionOut(
        id=s.id,
        patient_id=s.patient_id,
        date=s.created_at.strftime("%d/%m/%Y") if s.created_at else "—",
        comprehension_score=s.comprehension_score,
        read_time_seconds=s.read_time_seconds,
        self_understanding=s.self_understanding,
        difficulty_level=s.difficulty_level,
        flagged_word_count=s.flagged_word_count,
    )

@app.get("/api/patients/{patient_id}/sessions", response_model=list[SessionOut])
def get_sessions(patient_id: int, db: DBSession = Depends(get_db)):
    sessions = db.query(Session).filter(Session.patient_id == patient_id).order_by(Session.id).all()
    return [_session_out(s) for s in sessions]

# ══════════════════════════════════════
# ANALYTICS ROUTES
# ══════════════════════════════════════

@app.get("/api/patients/{patient_id}/analytics")
def get_analytics(patient_id: int, db: DBSession = Depends(get_db)):
    sessions = db.query(Session).filter(Session.patient_id == patient_id).order_by(Session.id).all()
    flagged = db.query(FlaggedWord).filter(FlaggedWord.patient_id == patient_id).all()

    fc = {}
    for f in flagged:
        fc[f.word] = fc.get(f.word, 0) + 1

    wf_total = {}
    ht_total = {}
    for s in sessions:
        wf = json.loads(s.word_frequencies or "{}")
        ht = json.loads(s.hover_times or "{}")
        for w, n in wf.items():
            wf_total[w] = wf_total.get(w, 0) + n
        for w, t in ht.items():
            ht_total[w] = ht_total.get(w, 0) + t

    avg_comp = round(sum(s.comprehension_score for s in sessions) / len(sessions)) if sessions else 0
    avg_time = round(sum(s.read_time_seconds for s in sessions) / len(sessions)) if sessions else 0
    trend = (sessions[-1].comprehension_score - sessions[0].comprehension_score) if len(sessions) > 1 else 0

    return {
        "session_count": len(sessions),
        "avg_comprehension": avg_comp,
        "avg_read_time": avg_time,
        "comprehension_trend": trend,
        "recommended_level": _auto_level(sessions, flagged),
        "flagged_word_freq": sorted(fc.items(), key=lambda x: x[1], reverse=True)[:8],
        "word_frequencies": sorted(wf_total.items(), key=lambda x: x[1], reverse=True)[:10],
        "hover_times": sorted(ht_total.items(), key=lambda x: x[1], reverse=True)[:10],
        "sessions": [_session_out(s).__dict__ for s in sessions],
    }

@app.get("/api/patients/{patient_id}/challenging-words")
def get_challenging_words(patient_id: int, db: DBSession = Depends(get_db)):
    """Returns ranked list of words this patient struggles with — used on writer side."""
    sessions = db.query(Session).filter(Session.patient_id == patient_id).all()
    flagged = db.query(FlaggedWord).filter(FlaggedWord.patient_id == patient_id).all()

    scores = {}
    flagged_set = set()

    # Flagged words = weight 2
    for f in flagged:
        w = f.word.lower()
        scores[w] = scores.get(w, 0) + 2
        flagged_set.add(w)

    # Hover time = bonus if > 2s total
    ht_total = {}
    for s in sessions:
        ht = json.loads(s.hover_times or "{}")
        for w, t in ht.items():
            ht_total[w] = ht_total.get(w, 0) + t

    for w, t in ht_total.items():
        if t > 2000:
            scores[w] = scores.get(w, 0) + (t // 1000)

    # Word frequency in texts = weight 0.5
    for s in sessions:
        wf = json.loads(s.word_frequencies or "{}")
        for w, n in wf.items():
            scores[w] = scores.get(w, 0) + n * 0.5

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:8]
    return [
        {
            "word": w,
            "score": round(sc, 1),
            "flagged": w in flagged_set,
            "slow_read": ht_total.get(w, 0) > 2000,
        }
        for w, sc in ranked
    ]

# ══════════════════════════════════════
# AI ROUTES (Claude via Anthropic SDK)
# ══════════════════════════════════════

class SimplifyRequest(BaseModel):
    text: str
    difficulty_level: int           # 1-5
    patient_id: Optional[int] = None

class SimplifyResponse(BaseModel):
    simplified: str
    grade_level: float
    hard_word_pct: int

class SimilarityRequest(BaseModel):
    original: str
    simplified: str

class DefinitionRequest(BaseModel):
    word: str

class InsightRequest(BaseModel):
    patient_id: int

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

@app.post("/api/simplify", response_model=SimplifyResponse)
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

    message = client.messages.create(
        model="claude-sonnet-4-5-20251001",
        max_tokens=1000,
        system=system,
        messages=[{"role": "user", "content": req.text}],
    )
    simplified = message.content[0].text.strip()

    # Calculate readability
    grade, hard_pct = _readability(simplified)
    return SimplifyResponse(simplified=simplified, grade_level=grade, hard_word_pct=hard_pct)


@app.post("/api/check-similarity")
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

    message = client.messages.create(
        model="claude-sonnet-4-5-20251001",
        max_tokens=900,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


@app.post("/api/define")
def define_word(req: DefinitionRequest):
    """Return a plain-English definition for a medical/complex word."""
    if req.word in _def_cache:
        return _def_cache[req.word]

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",   # use cheapest model for definitions
        max_tokens=120,
        messages=[{
            "role": "user",
            "content": (f'Define the medical/health term "{req.word}" for a patient. '
                        'Respond ONLY with JSON: '
                        '{"pos":"<noun/verb/adjective>","plain":"<plain English, 1-2 sentences, max 30 words, no jargon>"}')
        }],
    )
    raw = message.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    result = json.loads(raw)
    _def_cache[req.word] = result
    return result

_def_cache = {}


@app.post("/api/patient-insight")
def patient_insight(req: InsightRequest, db: DBSession = Depends(get_db)):
    """AI profile insight for writer side — reading profile + predicted difficult words."""
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
    lv = _auto_level(sessions, flagged)

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=350,
        messages=[{
            "role": "user",
            "content": (f'Medical reading analyst. Patient "{p.name}": {len(sessions)} sessions, '
                        f'avg comprehension {avg_comp}%, avg read time {avg_time}s, '
                        f'flagged words: {top_str}, recommended level {lv}/5.\n\n'
                        f'Write 2 concise sentences (max 40 words): reading profile + one writing recommendation.\n'
                        f'Then: PREDICT: 6 medical/complex words this patient is likely to struggle with.\n'
                        f'Format:\n[2 sentences]\nPREDICT: word1, word2...')
        }],
    )
    text = message.content[0].text.strip()
    parts = text.split("PREDICT:")
    insight = parts[0].strip()
    predicted = [w.strip() for w in parts[1].split(",") if w.strip()] if len(parts) > 1 else []
    flagged_set = set(fc.keys())
    return {
        "insight": insight,
        "predicted": [{"word": w, "prev_flagged": w.lower() in flagged_set} for w in predicted],
    }


@app.post("/api/analytics-summary")
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
    lv = _auto_level(sessions, flagged)
    from models import LEVEL_LABELS
    lv_label = LEVEL_LABELS.get(lv, "Normal")

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        messages=[{
            "role": "user",
            "content": (f'Health literacy analyst. Patient "{p.name}": {len(sessions)} sessions, '
                        f'avg comprehension {avg_comp}%, trend {trend:+}%, avg read time {avg_time}s, '
                        f'self-reported understanding {avg_self}/4, flagged words: {top_str}, '
                        f'recommended level {lv}/5 ({lv_label}).\n\n'
                        f'Write a concise 2-3 sentence profile: reading ability, difficulty patterns, trajectory.\n'
                        f'Then write 3-4 specific writing recommendations. Start each with "→".')
        }],
    )
    text = message.content[0].text.strip()
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
    import re
    word = re.sub(r'(?:[^laeiouy]es|ed|[^laeiouy]e)$', '', word)
    word = re.sub(r'^y', '', word)
    m = re.findall(r'[aeiouy]{1,2}', word)
    return len(m) if m else 1

def _readability(text: str):
    import re
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
