# Module Manager — Flask Edition

A full-stack CRUD interface for managing module records in your `al.db` SQLite database.

## Project Structure

```
module-manager/
├── app.py                  ← Flask backend & REST API
├── requirements.txt        ← Python dependencies (just Flask)
├── README.md               ← This file
└── templates/
    └── index.html          ← Dark-themed frontend UI
```

`al.db` must be placed **in the same folder as `app.py`** before launching.

---

## Quick Start

### 1. Place al.db in the project folder
```
module-manager/
├── al.db          ← your database goes here
├── app.py
...
```

### 2. Create and activate a virtual environment (recommended)
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the server
```bash
python app.py
```

Flask will start on **http://localhost:5000** — open that in your browser.

---

## Using a Different Database Path

If `al.db` lives elsewhere, set the `MODULE_DB` environment variable:

```bash
# Windows (PowerShell)
$env:MODULE_DB = "C:\Users\Shane\Documents\al.db"
python app.py

# macOS / Linux
MODULE_DB=/home/shane/al.db python3 app.py
```

---

## REST API Reference

All endpoints return JSON.

| Method | Endpoint                  | Description                  |
|--------|---------------------------|------------------------------|
| GET    | `/api/modules`            | List all modules (by code)   |
| POST   | `/api/modules`            | Create a new module          |
| PUT    | `/api/modules/<rowid>`    | Update an existing module    |
| DELETE | `/api/modules/<rowid>`    | Delete a module              |
| GET    | `/api/items`              | List all items (reward list) |
| GET    | `/api/health`             | DB status and record counts  |

### Module JSON shape
```json
{
  "code":            "DDAL-01",
  "season-setting":  "Season 1",
  "name":            "Defiance in Phlan",
  "tier":            1,
  "apl":             2,
  "running-time":    "1–2 hours",
  "google-link":     "https://docs.google.com/...",
  "last-run":        "2026-06-15",
  "reward":          42,
  "notes":           "Starter adventure."
}
```

---

## Database Schema Expected

```sql
CREATE TABLE modules (
  code           TEXT,
  "season-setting" TEXT,
  name           TEXT,
  tier           INTEGER,
  apl            INTEGER,
  "running-time" TEXT,
  "google-link"  TEXT,
  "last-run"     TEXT,
  reward         INTEGER,   -- references items.id
  notes          TEXT
);

CREATE TABLE items (
  id   INTEGER PRIMARY KEY,
  name TEXT
);
```

The app uses SQLite `rowid` as the internal record identifier — no explicit `id` column is required in `modules`.

---

## Running in Production

For a local LAN setup (accessible from other machines on your network):

```bash
# Already configured — app.py binds to 0.0.0.0:5000
python app.py
```

For a more robust setup, use **Waitress** (Windows-friendly WSGI server):

```bash
pip install waitress
waitress-serve --host=0.0.0.0 --port=5000 app:app
```

Or **Gunicorn** (macOS/Linux):
```bash
pip install gunicorn
gunicorn -w 2 -b 0.0.0.0:5000 app:app
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `Database not found: al.db` | Place `al.db` next to `app.py` or set `MODULE_DB` env var |
| `No 'modules' table` | Verify the table name is exactly `modules` in your DB |
| Port 5000 in use | Change the port in `app.py`: `app.run(port=5001)` |
| Changes not persisting | Ensure the process has write permission to `al.db` |
