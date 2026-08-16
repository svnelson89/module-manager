import os
import json
import sqlite3
from flask import Flask, jsonify, request, render_template, g

app = Flask(__name__)

DB_PATH = os.environ.get("MODULE_DB", os.path.join(os.path.dirname(__file__), "al.db"))


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        if not os.path.exists(DB_PATH):
            raise FileNotFoundError(f"Database not found: {DB_PATH}")
        db = g._database = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()


def rows_to_list(cursor):
    return [dict(row) for row in cursor.fetchall()]


def _parse_reward(val):
    """Normalize any stored reward value → list of ints."""
    if val is None or val == '':
        return []
    if isinstance(val, int):
        return [val]
    if isinstance(val, list):
        return [int(x) for x in val if x is not None]
    if isinstance(val, str):
        s = val.strip()
        if s.startswith('['):
            try:
                arr = json.loads(s)
                return [int(x) for x in arr if x is not None]
            except Exception:
                pass
        try:
            return [int(s)]
        except Exception:
            pass
    return []


def _serialize_reward(val):
    """Serialize a reward list to a JSON string for DB storage, or None."""
    if not val:
        return None
    ids = [int(x) for x in val if x is not None]
    return json.dumps(ids) if ids else None


def _serialize_multi_int(val):
    """Serialize a list of integers to a JSON string for DB storage, or None."""
    if not val:
        return None
    if isinstance(val, (list, tuple)):
        ids = [int(x) for x in val if x is not None]
    else:
        ids = [int(val)]
    return json.dumps(ids) if ids else None


def _parse_multi_int(val):
    """Normalize any stored multi-int value → list of ints."""
    if val is None or val == '':
        return []
    if isinstance(val, int):
        return [val]
    if isinstance(val, list):
        return [int(x) for x in val if x is not None]
    if isinstance(val, str):
        s = val.strip()
        if s.startswith('['):
            try:
                arr = json.loads(s)
                return [int(x) for x in arr if x is not None]
            except Exception:
                pass
        try:
            return [int(s)]
        except Exception:
            pass
    return []


# ---------------------------------------------------------------------------
# Global JSON error handlers — Flask always returns JSON, never HTML
# ---------------------------------------------------------------------------

@app.errorhandler(400)
def bad_request(e):
    return jsonify(error=str(e)), 400

@app.errorhandler(404)
def not_found(e):
    return jsonify(error=str(e)), 404

@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify(error=str(e)), 405

@app.errorhandler(500)
def internal_error(e):
    return jsonify(error=str(e)), 500

@app.errorhandler(Exception)
def unhandled_exception(e):
    app.logger.error(f"Unhandled exception: {e}", exc_info=True)
    return jsonify(error=f"Server error: {str(e)}"), 500


# ---------------------------------------------------------------------------
# Modules schema introspection + field mapping
# ---------------------------------------------------------------------------

# For each logical app field, a priority list of substrings to match
# against real column names (lowercased, symbols stripped).
MODULE_FIELD_KEYWORDS = {
    'code':           [['code']],
    'season-setting': [['season']],
    'name':           [['name']],
    'tier':           [['tier']],
    'apl':            [['apl'], ['level'], ['party']],
    'running-time':   [['running', 'time'], ['runtime'], ['run_time'],
                       ['runningtime'], ['duration'], ['running'], ['time']],
    'google-link':    [['google', 'link'], ['google'], ['link'], ['url'], ['doc']],
    'last-run':       [['last', 'run'], ['lastrun'], ['last_run'], ['last']],
    'reward':         [['reward']],
    'notes':          [['note']],
    'epic':           [['epic']],
}

# Logical app fields in INSERT order
APP_FIELDS = [
    'code', 'season-setting', 'name', 'tier', 'apl',
    'running-time', 'google-link', 'last-run', 'reward', 'notes', 'epic'
]


def _normalize(col):
    """Lowercase + strip hyphens/underscores/spaces for fuzzy matching."""
    return col.lower().replace('-', '').replace('_', '').replace(' ', '')


def _get_modules_schema(db):
    """
    Introspects the real modules table and returns:
      {
        'all_cols':  [...],          # every real column name
        'pk_col':    'rowid',        # always rowid for modules
        'field_map': {               # app field → real column name (or None)
            'code': 'code',
            'season-setting': 'season_setting',
            ...
        }
      }
    Returns None if modules table doesn't exist.
    """
    try:
        info = db.execute("PRAGMA table_info(modules)").fetchall()
        if not info:
            return None

        all_cols = [row[1] for row in info]
        norm_map = {_normalize(c): c for c in all_cols}  # normalized → real

        field_map = {}
        for app_field, keyword_groups in MODULE_FIELD_KEYWORDS.items():
            matched = None
            for keywords in keyword_groups:
                # All keywords in the group must appear in the normalized column name
                for norm_col, real_col in norm_map.items():
                    if all(kw in norm_col for kw in keywords):
                        matched = real_col
                        break
                if matched:
                    break
            field_map[app_field] = matched

        return {'all_cols': all_cols, 'field_map': field_map}
    except sqlite3.OperationalError:
        return None


def _build_insert_sql(field_map):
    """Build INSERT SQL using only fields that mapped to real columns."""
    cols   = []
    fields = []
    for app_field in APP_FIELDS:
        real_col = field_map.get(app_field)
        if real_col:
            cols.append(f'"{real_col}"')
            fields.append(app_field)
    placeholders = ', '.join(['?'] * len(cols))
    col_str = ', '.join(cols)
    return f'INSERT INTO modules ({col_str}) VALUES ({placeholders})', fields


def _build_update_sql(field_map):
    """Build UPDATE SQL using only fields that mapped to real columns."""
    parts  = []
    fields = []
    for app_field in APP_FIELDS:
        real_col = field_map.get(app_field)
        if real_col:
            parts.append(f'"{real_col}"=?')
            fields.append(app_field)
    set_str = ', '.join(parts)
    return f'UPDATE modules SET {set_str} WHERE rowid=?', fields


def _extract_params(data, fields, field_map):
    """Pull values from request data in the correct order for a SQL statement."""
    params = []
    is_epic = data.get('epic', False)
    for app_field in fields:
        val = data.get(app_field)
        if app_field == 'reward':
            val = _serialize_reward(val or [])
        elif app_field == 'tier' and is_epic:
            val = _serialize_multi_int(val or [])
        elif app_field == 'apl' and is_epic:
            val = _serialize_multi_int(val or [])
        params.append(val)
    return params


# ---------------------------------------------------------------------------
# Items schema introspection (unchanged)
# ---------------------------------------------------------------------------

def _get_items_schema(db):
    try:
        info = db.execute("PRAGMA table_info(items)").fetchall()
        if not info:
            return None
        all_cols    = [row[1] for row in info]
        pk_cols     = [row[1] for row in info if row[5] > 0]
        pk_col      = pk_cols[0] if pk_cols else all_cols[0]
        data_cols   = [c for c in all_cols if c != pk_col]
        display_col = next(
            (c for c in data_cols if 'name' in c.lower()),
            data_cols[0] if data_cols else pk_col
        )
        return {
            'all_cols':    all_cols,
            'pk_col':      pk_col,
            'data_cols':   data_cols,
            'display_col': display_col,
        }
    except sqlite3.OperationalError:
        return None


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Modules API
# ---------------------------------------------------------------------------

@app.route("/api/modules/schema", methods=["GET"])
def get_modules_schema():
    """Return real modules table schema + field mapping for debugging."""
    try:
        db     = get_db()
        schema = _get_modules_schema(db)
        if schema is None:
            return jsonify({"error": "modules table not found"}), 404
        return jsonify(schema)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 503


@app.route("/api/modules", methods=["GET"])
def get_modules():
    try:
        db     = get_db()
        schema = _get_modules_schema(db)
        if schema is None:
            return jsonify({"error": "modules table not found"}), 404

        field_map   = schema['field_map']
        reward_col  = field_map.get('reward')

        # Use _rowid_ alias to avoid collision with an explicit INTEGER PRIMARY KEY column
        rows = rows_to_list(db.execute('SELECT rowid as _rowid_, * FROM modules ORDER BY rowid'))

        # Re-key each row using app field names so the frontend always sees
        # consistent keys regardless of what the DB columns are called.
        result = []
        for row in rows:
            rec = {'rowid': row['_rowid_']}
            for app_field in APP_FIELDS:
                real_col = field_map.get(app_field)
                val      = row.get(real_col) if real_col else None
                if app_field == 'reward':
                    val = _parse_reward(val)
                rec[app_field] = val
            result.append(rec)

        return jsonify(result)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 503
    except sqlite3.OperationalError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/modules", methods=["POST"])
def create_module():
    data   = request.get_json(force=True)
    db     = get_db()
    schema = _get_modules_schema(db)
    if schema is None:
        return jsonify({"error": "modules table not found"}), 404

    sql, fields = _build_insert_sql(schema['field_map'])
    params      = _extract_params(data, fields, schema['field_map'])
    cur         = db.execute(sql, params)
    db.commit()
    return jsonify({"success": True, "rowid": cur.lastrowid}), 201


@app.route("/api/modules/<int:rowid>", methods=["PUT"])
def update_module(rowid):
    data   = request.get_json(force=True)
    db     = get_db()
    schema = _get_modules_schema(db)
    if schema is None:
        return jsonify({"error": "modules table not found"}), 404

    sql, fields = _build_update_sql(schema['field_map'])
    params      = _extract_params(data, fields, schema['field_map']) + [rowid]
    db.execute(sql, params)
    db.commit()
    return jsonify({"success": True})


@app.route("/api/modules/<int:rowid>", methods=["DELETE"])
def delete_module(rowid):
    db = get_db()
    db.execute("DELETE FROM modules WHERE rowid=?", (rowid,))
    db.commit()
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Items API — fully schema-aware
# ---------------------------------------------------------------------------

@app.route("/api/items/schema", methods=["GET"])
def get_items_schema():
    try:
        db     = get_db()
        schema = _get_items_schema(db)
        if schema is None:
            return jsonify({"error": "items table not found"}), 404
        return jsonify(schema)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 503


@app.route("/api/items", methods=["GET"])
def get_items():
    try:
        db     = get_db()
        schema = _get_items_schema(db)
        if schema is None:
            return jsonify([])
        pk   = schema['pk_col']
        disp = schema['display_col']
        rows = rows_to_list(db.execute(f'SELECT * FROM items ORDER BY "{disp}"'))
        for row in rows:
            row['_pk']      = row.get(pk)
            row['_display'] = row.get(disp) or ''
        return jsonify(rows)
    except sqlite3.OperationalError:
        return jsonify([])
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 503


@app.route("/api/items", methods=["POST"])
def create_item():
    data = request.get_json(force=True)
    if not data:
        return jsonify({"error": "Empty request body"}), 400
    try:
        db     = get_db()
        schema = _get_items_schema(db)
        if schema is None:
            return jsonify({"error": "items table not found"}), 404

        valid_cols  = schema['data_cols']
        insert_cols = [c for c in valid_cols if c in data and data[c] not in (None, '')]

        if not insert_cols:
            return jsonify({
                "error": f"No valid column values provided. "
                         f"items table has these insertable columns: {valid_cols}"
            }), 400

        placeholders = ', '.join(['?'] * len(insert_cols))
        col_names    = ', '.join(f'"{c}"' for c in insert_cols)
        values       = [data[c] for c in insert_cols]

        cur    = db.execute(f'INSERT INTO items ({col_names}) VALUES ({placeholders})', values)
        db.commit()
        new_id  = cur.lastrowid
        pk_col  = schema['pk_col']
        new_row = dict(db.execute(
            f'SELECT * FROM items WHERE "{pk_col}"=?', (new_id,)
        ).fetchone())
        new_row['_pk']      = new_id
        new_row['_display'] = new_row.get(schema['display_col']) or ''
        return jsonify({"success": True, "item": new_row}), 201
    except sqlite3.OperationalError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/items/<int:item_id>", methods=["PUT"])
def update_item(item_id):
    data = request.get_json(force=True)
    if not data:
        return jsonify({"error": "Empty request body"}), 400
    try:
        db     = get_db()
        schema = _get_items_schema(db)
        if schema is None:
            return jsonify({"error": "items table not found"}), 404

        valid_cols  = schema['data_cols']
        update_cols = [c for c in valid_cols if c in data]
        if not update_cols:
            return jsonify({"error": f"No valid column values provided. items table has these columns: {valid_cols}"}), 400

        set_clause = ', '.join(f'"{c}"=?' for c in update_cols)
        values     = [data[c] if data[c] != '' else None for c in update_cols]
        pk_col     = schema['pk_col']
        values.append(item_id)

        db.execute(f'UPDATE items SET {set_clause} WHERE "{pk_col}"=?', values)
        db.commit()
        updated_row = db.execute(f'SELECT * FROM items WHERE "{pk_col}"=?', (item_id,)).fetchone()
        if updated_row is None:
            return jsonify({"error": "Item not found"}), 404
        row = dict(updated_row)
        row['_pk']      = item_id
        row['_display'] = row.get(schema['display_col']) or ''
        return jsonify({"success": True, "item": row})
    except sqlite3.OperationalError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/items/<int:item_id>", methods=["DELETE"])
def delete_item(item_id):
    db     = get_db()
    schema = _get_items_schema(db)
    if schema is None:
        return jsonify({"error": "items table not found"}), 404

    # Strip this item id from any module's reward list before deleting it.
    mod_schema = _get_modules_schema(db)
    if mod_schema:
        reward_col = mod_schema['field_map'].get('reward')
        if reward_col:
            rows = rows_to_list(db.execute(f'SELECT rowid as _rowid_, "{reward_col}" as reward FROM modules'))
            for row in rows:
                ids = _parse_reward(row['reward'])
                if item_id in ids:
                    new_ids = [i for i in ids if i != item_id]
                    new_val = _serialize_reward(new_ids)
                    db.execute(f'UPDATE modules SET "{reward_col}"=? WHERE rowid=?', (new_val, row['_rowid_']))

    pk_col = schema['pk_col']
    db.execute(f'DELETE FROM items WHERE "{pk_col}"=?', (item_id,))
    db.commit()
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Item Properties API
# ---------------------------------------------------------------------------

@app.route("/api/item-properties", methods=["GET"])
def get_item_properties():
    try:
        db   = get_db()
        rows = rows_to_list(db.execute("SELECT * FROM item_properties ORDER BY property_name"))
        return jsonify(rows)
    except sqlite3.OperationalError:
        return jsonify([])
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 503


@app.route("/api/item-properties", methods=["POST"])
def create_item_property():
    data = request.get_json(force=True)
    name = (data or {}).get('property_name', '').strip()
    if not name:
        return jsonify({"error": "property_name is required"}), 400
    try:
        db  = get_db()
        cur = db.execute("INSERT INTO item_properties (property_name) VALUES (?)", (name,))
        db.commit()
        return jsonify({"success": True, "id": cur.lastrowid, "property_name": name}), 201
    except sqlite3.OperationalError as e:
        return jsonify({"error": str(e)}), 400


# ---------------------------------------------------------------------------
# Health + schema debug
# ---------------------------------------------------------------------------

@app.route("/api/health")
def health():
    try:
        db           = get_db()
        module_count = db.execute("SELECT COUNT(*) FROM modules").fetchone()[0]
        mod_schema   = _get_modules_schema(db)
        try:
            item_count = db.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        except sqlite3.OperationalError:
            item_count = 0
        return jsonify({
            "status":        "ok",
            "db":            DB_PATH,
            "modules":       module_count,
            "items":         item_count,
            "field_mapping": mod_schema['field_map'] if mod_schema else None
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 503


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
