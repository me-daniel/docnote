"""Flask app: Dual-Interface Healthcare Translation Suite (concept demo)."""

import json
import math
import re
from pathlib import Path

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _load_deft():
    path = STATIC_DIR / "deft_terms.json"
    if path.exists():
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    return {}


DEFT_TERMS = _load_deft()


def _hash_sim(a: str, b: str) -> float:
    """Deterministic pseudo-similarity from character n-grams (demo only, not ClinicalBERT)."""
    def grams(s, n=3):
        s = re.sub(r"\s+", " ", (s or "").lower())
        return {s[i : i + n] for i in range(max(0, len(s) - n + 1))} or {""}

    ga, gb = grams(a), grams(b)
    if not ga and not gb:
        return 1.0
    inter = len(ga & gb)
    union = len(ga | gb) or 1
    return inter / union


@app.route("/")
def index():
    return render_template("suite.html", deft_terms=DEFT_TERMS)


@app.post("/api/clinicalbert-verify")
def clinicalbert_verify():
    """
    Concept endpoint: returns scores shaped like a verification dashboard.
    In production this would call medicalai/ClinicalBERT or a hosted embedding service.
    """
    data = request.get_json(silent=True) or {}
    original = (data.get("original") or "").strip()
    simplified = (data.get("simplified") or "").strip()
    complexity = int(data.get("complexity") or 2)  # 1 high, 2 normal, 3 simple

    if not original or not simplified:
        return jsonify(
            {
                "overall_match_pct": None,
                "fact_preservation_pct": None,
                "reading_level_label": "—",
                "reading_grade_approx": None,
                "note": "Provide both original and simplified text.",
            }
        ), 400

    base = _hash_sim(original, simplified)
    # Simpler targets may score slightly lower on lexical overlap while still being valid
    complexity_adj = {1: 6, 2: 0, 3: -4}.get(complexity, 0)
    overall = max(52, min(99, round(base * 88 + 10 + complexity_adj + math.sin(len(simplified)) * 2)))
    fact = max(58, min(99, overall - (3 - min(complexity, 3)) * 2))

    words = len(re.findall(r"\b\w+\b", simplified))
    sents = max(1, len(re.findall(r"[.!?]+", simplified)) or 1)
    asl = words / sents
    syll_proxy = sum(max(1, len(re.findall(r"[aeiouy]+", w.lower()))) for w in re.findall(r"\b\w+\b", simplified))
    asw = syll_proxy / max(words, 1)
    grade = max(3, min(16, round(0.39 * asl + 11.8 * asw - 15.59)))

    labels = {1: "Professional / clinical-adjacent", 2: "Standard plain language", 3: "Simplified / low literacy"}
    reading_label = f"~Grade {grade} — {labels.get(complexity, labels[2])}"

    return jsonify(
        {
            "overall_match_pct": overall,
            "fact_preservation_pct": fact,
            "reading_level_label": reading_label,
            "reading_grade_approx": grade,
            "model_note": "Demo scoring (deterministic heuristic). Replace with ClinicalBERT embeddings + calibration.",
        }
    )


@app.post("/api/demo-simplify")
def demo_simplify():
    """Rule-based demo 'LLM' output so the concept works without external API keys."""
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    level = int(data.get("complexity") or 2)  # 1 professional, 2 normal, 3 simple

    replacements_professional = [
        (r"\bq4h\b", "every 4 hours"),
        (r"\bPO\b", "by mouth"),
        (r"\bOD\b", "once daily"),
        (r"\bBID\b", "twice daily"),
    ]
    replacements_normal = [
        (r"\bCOPD\b", "COPD (a long-term lung disease)"),
        (r"\bCOPD \(chronic obstructive pulmonary disease\)\b", "COPD (a long-term lung disease)"),
        (r"\bexacerbation\b", "sudden worsening"),
        (r"\bSpirometry\b", "a breathing test"),
        (r"\bFEV1/FVC\b", "breathing test ratio"),
        (r"\bnebulization\b", "breathing mist treatment"),
        (r"\bsystemic corticosteroids\b", "steroid pills"),
        (r"\bprednisolone\b", "prednisolone (a steroid)"),
        (r"\bempiric antibiotic therapy\b", "antibiotic treatment"),
        (r"\bamoxicillin-clavulanate\b", "amoxicillin-clavulanate (an antibiotic)"),
        (r"\bSpO2\b", "blood oxygen level"),
        (r"\bpulmonology\b", "lung specialist"),
    ]
    replacements_simple = [
        (r"\bThe patient is a (\d+)-year-old male\b", r"This is a \1-year-old man"),
        (r"\bpresenting with acute exacerbation of chronic obstructive pulmonary disease \(COPD\)\.", "who has a sudden flare-up of COPD — a long-term lung disease that makes breathing harder."),
        (r"\bSpirometry indicates a post-bronchodilator FEV1/FVC ratio of ([0-9.]+), consistent with moderate obstructive ventilatory defect\.", r"A breathing test after medicine shows a ratio of \1. This fits moderate blockage of airflow."),
        (r"\bInitiate short-acting beta-2 agonist \(salbutamol 2\.5mg via nebulization q4h\)\b", "Start a quick-relief breathing medicine (salbutamol 2.5 mg) with a mist machine every 4 hours"),
        (r"\bsystemic corticosteroids \(prednisolone 40mg PO OD x 5 days\)\b", "and steroid pills (prednisolone 40 mg once a day for 5 days)"),
        (r"\bempiric antibiotic therapy with amoxicillin-clavulanate 875/125mg PO BID\b", "Also start an antibiotic (amoxicillin-clavulanate) twice a day by mouth"),
        (r"\bfor suspected bacterial exacerbation\.", "in case bacteria caused the flare-up."),
        (r"\bMonitor SpO2, target 88–92%\b", "Check blood oxygen; aim for 88–92%."),
        (r"\bArrange pulmonology follow-up in 2 weeks post-discharge\.", "Plan a visit with a lung doctor about 2 weeks after leaving the hospital."),
    ]

    out = text
    if level >= 1:
        for pat, rep in replacements_professional:
            out = re.sub(pat, rep, out, flags=re.IGNORECASE)
    if level >= 2:
        for pat, rep in replacements_normal:
            out = re.sub(pat, rep, out, flags=re.IGNORECASE)
    if level >= 3:
        for pat, rep in replacements_simple:
            out = re.sub(pat, rep, out, flags=re.IGNORECASE)

    if out == text and text:
        out = text + "\n\n[Demo] Try the sample note or adjust the complexity slider — this endpoint uses pattern rules only."

    return jsonify({"simplified": out.strip(), "level": level})


@app.get("/api/deft/<path:term>")
def deft_lookup(term: str):
    key = term.lower().strip()
    definition = DEFT_TERMS.get(key)
    if not definition:
        return jsonify({"term": term, "definition": None}), 404
    return jsonify({"term": term, "definition": definition})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
