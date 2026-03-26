# DoctorTalk — FastAPI backend

## Setup

### 1. Install Python dependencies
```bash
pip install -r requirements.txt
```

### 2. Set your Gemini API key
```bash
# Mac/Linux
export GEMINI_API_KEY=...

# Windows (Command Prompt)
set GEMINI_API_KEY=...

# Windows (PowerShell)
$env:GEMINI_API_KEY="..."
```

### 3. Run the server
From the project directory (`docnote/`):

```bash
uv run uvicorn main:app --reload --port 8000
```

Use **`main:app`**: Python module **`main`** (file `main.py`) and the FastAPI instance **`app`**. Do not use `app:main.py` or `uvicorn app:...` unless you add a separate `app` package.

Alternatively: `uv run python main.py` runs the app with reload via the `if __name__ == "__main__"` block in `main.py`.

### 4. Open in browser
```
http://localhost:8000
```

### 5. View auto-generated API docs
```
http://localhost:8000/docs        # Swagger UI
http://localhost:8000/redoc       # ReDoc
```

---

## Project Structure

```
docnote/
├── main.py          # FastAPI app
├── models.py        # SQLAlchemy ORM models (Patient, Session, FlaggedWord)
├── database.py      # DB engine, session, init_db(), demo seed for patient Uwe
├── requirements.txt
├── doctortalk.db    # SQLite (auto-created; was medbridge.db in older checkouts)
├── templates/
│   └── index.html
└── static/
    ├── css/ js/
```

On first run the server seeds a demo patient **Uwe** with sample sessions so the Analytics tab has charts by default. The Writer patient dropdown selects **Uwe** when nothing else is chosen.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/patients` | List all patients |
| POST | `/api/patients` | Create patient |
| GET | `/api/patients/{id}` | Get patient profile |
| GET | `/api/patients/{id}/sessions` | Get all sessions |
| POST | `/api/sessions` | Save a reading session |
| GET | `/api/patients/{id}/analytics` | Full analytics data |
| GET | `/api/patients/{id}/challenging-words` | Ranked difficult words |
| POST | `/api/simplify` | Simplify clinical text with Gemini |
| POST | `/api/check-similarity` | Sentence-level similarity check |
| POST | `/api/define` | Get plain-English word definition |
| POST | `/api/patient-insight` | AI patient reading profile |
| POST | `/api/analytics-summary` | AI writing recommendations |

---

---


## Why FastAPI over Flask?

- **Async by default** — handles multiple concurrent AI calls without blocking
- **Auto docs** — Swagger UI at `/docs` for free
- **Pydantic validation** — request/response types validated automatically
- **Much faster** — built on Starlette + uvicorn (ASGI vs Flask's WSGI)
- **Type hints** — cleaner, more maintainable Python code
