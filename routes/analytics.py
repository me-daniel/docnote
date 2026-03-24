import json

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from database import get_db
from models import Session, FlaggedWord
from routes.sessions import session_out
from routes.patients import auto_level

router = APIRouter(prefix="/api", tags=["analytics"])


@router.get("/patients/{patient_id}/analytics")
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
        "recommended_level": auto_level(sessions, flagged),
        "flagged_word_freq": sorted(fc.items(), key=lambda x: x[1], reverse=True)[:8],
        "word_frequencies": sorted(wf_total.items(), key=lambda x: x[1], reverse=True)[:10],
        "hover_times": sorted(ht_total.items(), key=lambda x: x[1], reverse=True)[:10],
        "sessions": [session_out(s).__dict__ for s in sessions],
    }


@router.get("/patients/{patient_id}/challenging-words")
def get_challenging_words(patient_id: int, db: DBSession = Depends(get_db)):
    """Returns ranked list of words this patient struggles with."""
    sessions = db.query(Session).filter(Session.patient_id == patient_id).all()
    flagged = db.query(FlaggedWord).filter(FlaggedWord.patient_id == patient_id).all()

    scores = {}
    flagged_set = set()

    for f in flagged:
        w = f.word.lower()
        scores[w] = scores.get(w, 0) + 2
        flagged_set.add(w)

    ht_total = {}
    for s in sessions:
        ht = json.loads(s.hover_times or "{}")
        for w, t in ht.items():
            ht_total[w] = ht_total.get(w, 0) + t

    for w, t in ht_total.items():
        if t > 2000:
            scores[w] = scores.get(w, 0) + (t // 1000)

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
