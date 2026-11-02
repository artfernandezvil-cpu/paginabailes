"""Archivo de Bailes Chinos. WSGI + SQLite; no framework required."""
import argparse
import base64
import binascii
import colorsys
import datetime as dt
import getpass
import hashlib
import hmac
import io
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from http.cookies import SimpleCookie
from urllib.parse import unquote, urlparse
from wsgiref.simple_server import make_server, WSGIRequestHandler

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get('BAILES_DATA_DIR', ROOT / 'runtime'))
MAX_BODY = 35 * 1024 * 1024
MAX_FILE = 8 * 1024 * 1024
COOKIE = 'bc_session'


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def dumps(v):
    return json.dumps(v, ensure_ascii=False, separators=(',', ':'))


def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    DATA_DIR.chmod(0o700)
    (DATA_DIR / 'media').mkdir(exist_ok=True, mode=0o700)
    c = sqlite3.connect(DATA_DIR / 'archive.sqlite', timeout=15)
    (DATA_DIR / 'archive.sqlite').chmod(0o600)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c


def init_db():
    with connect() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS territories(code TEXT PRIMARY KEY,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY,kind TEXT NOT NULL,territory TEXT REFERENCES territories(code),payload TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS participations(baile_id TEXT REFERENCES records(id) ON DELETE CASCADE,fiesta_id TEXT REFERENCES records(id) ON DELETE CASCADE,PRIMARY KEY(baile_id,fiesta_id));
        CREATE TABLE IF NOT EXISTS contents(key TEXT PRIMARY KEY,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT NOT NULL UNIQUE,name TEXT NOT NULL,password TEXT NOT NULL,role TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id) ON DELETE CASCADE,csrf TEXT NOT NULL,expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS contributions(id TEXT PRIMARY KEY,payload TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS media(id TEXT PRIMARY KEY,contribution_id TEXT REFERENCES contributions(id) ON DELETE CASCADE,name TEXT NOT NULL,mime TEXT NOT NULL,size INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS layers(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS rate_limits(key TEXT NOT NULL,at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY,name TEXT NOT NULL,mime TEXT NOT NULL,size INTEGER NOT NULL,created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS revisions(id INTEGER PRIMARY KEY AUTOINCREMENT,entity TEXT NOT NULL,entity_key TEXT NOT NULL,payload TEXT NOT NULL,created TEXT NOT NULL);
        ''')
        if not c.execute("SELECT 1 FROM settings WHERE key='seeded'").fetchone():
            territories = json.loads((ROOT / 'data/territories.json').read_text())
            for t in territories:
                c.execute('INSERT INTO territories VALUES(?,?)', (t['code'], dumps(t)))
            for r in json.loads((ROOT / 'data/records.json').read_text()):
                c.execute('INSERT INTO records VALUES(?,?,?,?,?)', (r['id'], r['type'], r['communeCode'], dumps(r), r.get('revision', 0)))
            for k, v in json.loads((ROOT / 'data/content.json').read_text()).items():
                c.execute('INSERT INTO contents VALUES(?,?)', (k, dumps(v)))
            c.execute("INSERT INTO settings VALUES('seeded',?)", (now(),))


class APIError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


def password_hash(password):
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 480000).hex()
    return f'pbkdf2_sha256$480000${salt}${hashed}'


def password_check(password, saved):
    try:
        _, rounds, salt, expected = saved.split('$')
        return hmac.compare_digest(hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), int(rounds)).hex(), expected)
    except (ValueError, TypeError):
        return False


def user_public(u):
    return {k: u[k] for k in ('id', 'email', 'name', 'role', 'active')}


def session(c, env):
    cookies = SimpleCookie()
    try:
        cookies.load(env.get('HTTP_COOKIE', ''))
    except Exception:
        return None
    if COOKIE not in cookies:
        return None
    token = hashlib.sha256(cookies[COOKIE].value.encode()).hexdigest()
    row = c.execute('SELECT u.*,s.csrf,s.token FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires>? AND u.active=1', (token, int(time.time()))).fetchone()
    return dict(row) if row else None


def authenticate(c, env, write=False, admin=False):
    u = session(c, env)
    if not u:
        raise APIError(401, 'Inicia sesión para continuar.')
    if admin and u['role'] != 'admin':
        raise APIError(403, 'Esta acción requiere una cuenta administradora.')
    if write:
        origin = env.get('HTTP_ORIGIN')
        if origin and urlparse(origin).netloc != env.get('HTTP_HOST', ''):
            raise APIError(403, 'Origen de solicitud no autorizado.')
        if not hmac.compare_digest(env.get('HTTP_X_CSRF_TOKEN', ''), u['csrf']):
            raise APIError(403, 'La sesión cambió. Actualiza la página.')
    return u


def rate_limit(c, env, prefix, maximum, seconds):
    key = prefix + ':' + hashlib.sha256(env.get('REMOTE_ADDR', '').encode()).hexdigest()
    cutoff = int(time.time()) - seconds
    c.execute('DELETE FROM rate_limits WHERE at<?', (int(time.time()) - 86400,))
    if c.execute('SELECT COUNT(*) FROM rate_limits WHERE key=? AND at>?', (key, cutoff)).fetchone()[0] >= maximum:
        raise APIError(429, 'Hay demasiados intentos. Inténtalo más tarde.')
    c.execute('INSERT INTO rate_limits VALUES(?,?)', (key, int(time.time())))
    c.commit()


def text(v, key, maximum=500, required=False):
    value = str(v.get(key, '')).strip()
    if len(value) > maximum or (required and not value):
        raise APIError(400, f'Revisa el campo «{key}».')
    return value


def safe_url(value):
    if not value:
        return ''
    if re.fullmatch(r'/uploads/[a-f0-9]{32}', value):
        return value
    p = urlparse(value)
    if p.scheme != 'https' or not p.hostname or p.username or p.password:
        raise APIError(400, 'Los enlaces deben comenzar con https://.')
    return value


def remember(c, entity, key, payload):
    c.execute('INSERT INTO revisions(entity,entity_key,payload,created) VALUES(?,?,?,?)', (entity, key, dumps(payload), now()))


def validate_contents(v):
    required = {'intro', 'chapters', 'community', 'appearance', 'sections', 'extraSections'}
    if set(v) != required: raise APIError(400, 'Revisa las secciones del sitio.')
    def visit(obj, depth=0):
        if depth > 7: raise APIError(400, 'Contenido demasiado complejo.')
        if isinstance(obj, dict):
            if len(obj) > 50: raise APIError(400, 'Contenido demasiado extenso.')
            for key, value in obj.items():
                if not isinstance(key, str) or len(key) > 100: raise APIError(400, 'Campo no válido.')
                visit(value, depth+1)
        elif isinstance(obj, list):
            if len(obj) > 100: raise APIError(400, 'Demasiados elementos.')
            for value in obj: visit(value, depth+1)
        elif isinstance(obj, str):
            if len(obj) > 30000: raise APIError(400, 'Texto demasiado extenso.')
        elif not isinstance(obj, (bool, int, float, type(None))): raise APIError(400, 'Contenido no válido.')
    visit(v)
    if not isinstance(v['intro'], dict) or not isinstance(v['appearance'], dict) or not isinstance(v['chapters'], list) or not v['chapters'] or not isinstance(v['sections'], list) or not isinstance(v['extraSections'], list): raise APIError(400, 'Estructura de contenido no válida.')
    ids = [s.get('id') for s in v['sections']]
    if set(ids) != {'historia', 'mapa', 'calendario', 'memorias', 'participa'} or len(ids) != 5: raise APIError(400, 'Conserva las cinco secciones principales; puedes ocultarlas o cambiar su orden.')
    for s in v['extraSections']:
        if not re.fullmatch(r'[a-z][a-z0-9-]{0,60}', str(s.get('id',''))) or s['id'] in ids: raise APIError(400, 'Identificador de sección no válido.')
        ids.append(s['id'])
        if s.get('image'): safe_url(s['image'])
    for s in v['chapters']:
        for key in ('id', 'label', 'title', 'body'): text(s, key, 30000, True)
        if s.get('source'): safe_url(s['source'])
    for key in ('paper', 'ink', 'accent', 'navy'):
        if not re.fullmatch(r'#[a-fA-F0-9]{6}', v['appearance'].get(key, '')): raise APIError(400, 'Revisa los colores del sitio.')
    for key in ('logoArt', 'heroLeftArt', 'heroRightArt'):
        if v['appearance'].get(key) not in ('andacollo', 'norte', ''): safe_url(v['appearance'].get(key, ''))
    for key in ('instagram', 'facebook'):
        if v['appearance'].get(key): safe_url(v['appearance'][key])


def all_records(c):
    records = []
    for row in c.execute('SELECT payload,revision FROM records ORDER BY json_extract(payload,\'$.markerNumber\')'):
        r = json.loads(row['payload'])
        r['revision'] = row['revision']
        r['participantIds'] = [x[0] for x in c.execute('SELECT baile_id FROM participations WHERE fiesta_id=?', (r['id'],))] if r['type'] == 'fiesta' else []
        records.append(r)
    return records


def contribution(c, row, private=False):
    v = json.loads(row['payload'])
    if not private:
        v.pop('contact', None)
        v.pop('consent', None)
    return {**v, 'id': row['id'], 'status': row['status'], 'created': row['created'], 'files': [dict(m) for m in c.execute('SELECT id,name,mime,size FROM media WHERE contribution_id=?', (row['id'],))]}


def state(c):
    revision=c.execute("SELECT value FROM settings WHERE key='content_revision'").fetchone()
    return {'connected': True, 'records': all_records(c), 'territories': [json.loads(t[0]) for t in c.execute('SELECT payload FROM territories')],
            'contents': {r[0]: json.loads(r[1]) for r in c.execute('SELECT key,payload FROM contents')},
            'contributions': [contribution(c, r) for r in c.execute("SELECT * FROM contributions WHERE status='approved' ORDER BY created DESC")],
            'layers': [json.loads(r[0]) for r in c.execute('SELECT payload FROM layers')], 'contentRevision':int(revision[0]) if revision else 0}


def next_color(c, number):
    used = {json.loads(r[0]).get('color') for r in c.execute('SELECT payload FROM records')}
    for offset in range(10000):
        n = number + offset
        rgb = colorsys.hls_to_rgb((n * 137.507764 % 360) / 360, .38 + (n % 3) * .055, .64)
        col = '#' + ''.join(f'{round(x * 255):02x}' for x in rgb)
        if col not in used:
            return col
    raise APIError(400, 'Selecciona un color disponible.')


def record_save(c, v, record_id=None):
    old = c.execute('SELECT * FROM records WHERE id=?', (record_id,)).fetchone() if record_id else None
    if record_id and not old:
        raise APIError(404, 'La ficha ya no está disponible.')
    if old and v.get('revision') != old['revision']:
        raise APIError(409, 'Otra persona actualizó la ficha. Vuelve a abrirla antes de guardar.')
    kind = v.get('type')
    if kind not in ('baile', 'fiesta') or (old and kind != old['kind']):
        raise APIError(400, 'Tipo de ficha no válido.')
    territory = c.execute('SELECT payload FROM territories WHERE code=?', (v.get('communeCode'),)).fetchone()
    if not territory:
        raise APIError(400, 'Selecciona una comuna.')
    t = json.loads(territory[0])
    old_data = json.loads(old['payload']) if old else {}
    if old:
        old_data['participantIds']=[r[0] for r in c.execute('SELECT baile_id FROM participations WHERE fiesta_id=?',(record_id,))]
        old_data['fiestaIds']=[r[0] for r in c.execute('SELECT fiesta_id FROM participations WHERE baile_id=?',(record_id,))]
        remember(c, 'record', record_id, old_data)
    number = old_data.get('markerNumber') or 1 + max((r.get('markerNumber', 0) for r in all_records(c)), default=0)
    color = v.get('color') or old_data.get('color') or next_color(c, number)
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
        raise APIError(400, 'Color no válido.')
    color = color.lower()
    if any(r['id'] != record_id and r.get('color', '').lower() == color for r in all_records(c)):
        raise APIError(400, 'Ese color identifica otra ficha. Elige uno diferente.')
    try:
        lat, lng = float(v.get('lat', t['lat'])), float(v.get('lng', t['lng']))
        month = int(v.get('month', 0)) if kind == 'fiesta' else 0
        if not (-90 <= lat <= 90 and -180 <= lng <= 180 and 0 <= month <= 12):
            raise ValueError()
    except (ValueError, TypeError):
        raise APIError(400, 'Revisa las coordenadas y el mes.')
    date = text(v, 'date', 10) if kind == 'fiesta' else ''
    if date:
        try:
            parsed = dt.date.fromisoformat(date)
            month = parsed.month
        except ValueError:
            raise APIError(400, 'Fecha no válida.')
    precision = v.get('precision', 'comuna')
    if precision not in ('comuna', 'localidad', 'exacta'):
        raise APIError(400, 'Precisión territorial no válida.')
    if precision == 'comuna':
        lat, lng = t['lat'], t['lng']
    record = {**old_data, 'id': record_id or secrets.token_hex(12), 'type': kind, 'name': text(v, 'name', 250, True),
              'region': t['region'], 'province': t['province'], 'commune': t['name'], 'communeCode': t['code'],
              'locality': text(v, 'locality', 250), 'lat': lat, 'lng': lng, 'precision': precision, 'month': month, 'date': date,
              'history': text(v, 'history', 15000), 'description': text(v, 'description', 15000), 'source': text(v, 'source', 1000),
              'photoUrl': safe_url(text(v, 'photoUrl', 2000)), 'videoUrl': safe_url(text(v, 'videoUrl', 2000)),
              'color': color, 'markerNumber': number, 'revision': old['revision'] + 1 if old else 1,
              'notes': old_data.get('notes', ''), 'status': old_data.get('status', 'sin_verificar')}
    c.execute('INSERT INTO records VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET territory=excluded.territory,payload=excluded.payload,revision=excluded.revision', (record['id'], kind, t['code'], dumps(record), record['revision']))
    if kind == 'fiesta':
        participants = v.get('participantIds', [])
        if not isinstance(participants, list) or len(participants) > 500:
            raise APIError(400, 'Participantes no válidos.')
        c.execute('DELETE FROM participations WHERE fiesta_id=?', (record['id'],))
        for baile_id in set(participants):
            if not c.execute("SELECT 1 FROM records WHERE id=? AND kind='baile'", (baile_id,)).fetchone():
                raise APIError(400, 'Una agrupación participante no existe.')
            c.execute('INSERT INTO participations VALUES(?,?)', (baile_id, record['id']))
    elif 'fiestaIds' in v:
        ids=v['fiestaIds']
        if not isinstance(ids,list) or len(ids)>500: raise APIError(400,'Festividades asociadas no válidas.')
        c.execute('DELETE FROM participations WHERE baile_id=?',(record['id'],))
        for fiesta_id in set(ids):
            if not c.execute("SELECT 1 FROM records WHERE id=? AND kind='fiesta'",(fiesta_id,)).fetchone(): raise APIError(400,'Una festividad asociada no existe.')
            c.execute('INSERT INTO participations VALUES(?,?)',(record['id'],fiesta_id))
    return record


def file_type(raw):
    if raw.startswith(b'\x89PNG\r\n\x1a\n'): return 'image/png'
    if raw.startswith(b'\xff\xd8\xff'): return 'image/jpeg'
    if raw[:4] == b'RIFF' and raw[8:12] == b'WEBP': return 'image/webp'
    if raw[:4] == b'RIFF' and raw[8:12] == b'WAVE': return 'audio/wav'
    if raw.startswith(b'OggS'): return 'audio/ogg'
    if raw.startswith(b'ID3') or (len(raw) > 2 and raw[0] == 255 and raw[1] & 224 == 224): return 'audio/mpeg'
    if raw.startswith(b'%PDF-'): return 'application/pdf'
    return None


def submit_contribution(c, env, v, imported=False):
    if not imported: rate_limit(c, env, 'contribute', 10, 3600)
    if v.get('website'):
        raise APIError(400, 'No se pudo recibir el aporte.')
    if v.get('consent') is not True:
        raise APIError(400, 'Necesitamos tu autorización para recibir y revisar el material.')
    cid = secrets.token_hex(12)
    value = {k: text(v, k, maximum, required) for k, maximum, required in [('name', 160, True), ('title', 220, True), ('body', 15000, False), ('contact', 250, False), ('territory', 250, False), ('year', 100, False), ('credit', 250, False)]}
    value['kind'] = v.get('kind', 'testimonio')
    if value['kind'] not in ('testimonio', 'fotografia', 'audio', 'video', 'documento'):
        raise APIError(400, 'Tipo de aporte no válido.')
    record_id = v.get('recordId') or ''
    if record_id and not c.execute('SELECT 1 FROM records WHERE id=?', (record_id,)).fetchone():
        raise APIError(400, 'La ficha relacionada no existe.')
    value.update(recordId=record_id, consent=True, videoUrl=safe_url(text(v, 'videoUrl', 2000)))
    files = v.get('files', [])
    if not isinstance(files, list) or len(files) > 3:
        raise APIError(400, 'Puedes adjuntar hasta tres archivos.')
    if not value['body'] and not value['videoUrl'] and not files:
        raise APIError(400, 'Escribe tu recuerdo o adjunta material.')
    decoded = []
    for f in files:
        try:
            raw = base64.b64decode(f.get('data', ''), validate=True)
        except (binascii.Error, TypeError):
            raise APIError(400, 'Uno de los archivos no pudo leerse.')
        mime = file_type(raw)
        if not raw or len(raw) > MAX_FILE or not mime:
            raise APIError(400, 'Admite PNG, JPG, WebP, PDF, MP3, OGG o WAV de hasta 8 MB.')
        decoded.append((secrets.token_hex(16), text(f, 'name', 250, True), mime, raw))
    c.execute('INSERT INTO contributions VALUES(?,?,?,?)', (cid, dumps(value), 'pending', now()))
    written = []
    try:
        for mid, name, mime, raw in decoded:
            target = DATA_DIR / 'media' / mid
            target.write_bytes(raw)
            target.chmod(0o600)
            written.append(target)
            c.execute('INSERT INTO media VALUES(?,?,?,?,?)', (mid, cid, name, mime, len(raw)))
    except Exception:
        for p in written: p.unlink(missing_ok=True)
        raise
    return {'id': cid, 'status': 'pending'}


def api(c, env, method, path, body):
    headers = []
    if path == '/api/state' and method == 'GET': return state(c), headers
    if path == '/api/auth/session' and method == 'GET':
        u = session(c, env)
        return {'user': user_public(u) if u else None, 'csrf': u['csrf'] if u else ''}, headers
    if path == '/api/auth/login' and method == 'POST':
        origin = env.get('HTTP_ORIGIN')
        if origin and urlparse(origin).netloc != env.get('HTTP_HOST', ''): raise APIError(403, 'Origen no autorizado.')
        rate_limit(c, env, 'login', 8, 900)
        u = c.execute('SELECT * FROM users WHERE email=? AND active=1', (text(body, 'email', 250).lower(),)).fetchone()
        if not u or not password_check(str(body.get('password', '')), u['password']): raise APIError(401, 'Correo o contraseña incorrectos.')
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        c.execute('DELETE FROM sessions WHERE expires<?', (int(time.time()),))
        c.execute('INSERT INTO sessions VALUES(?,?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), u['id'], csrf, int(time.time()) + 86400))
        secure = '; Secure' if env.get('wsgi.url_scheme') == 'https' else ''
        headers.append(('Set-Cookie', f'{COOKIE}={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age=86400{secure}'))
        return {'user': user_public(u), 'csrf': csrf}, headers
    if path == '/api/contributions' and method == 'POST': return submit_contribution(c, env, body), headers
    if not path.startswith('/api/admin/') and path != '/api/auth/logout': raise APIError(404, 'Ruta no disponible.')
    u = authenticate(c, env, method != 'GET')
    if path == '/api/auth/logout' and method == 'POST':
        c.execute('DELETE FROM sessions WHERE token=?', (u['token'],))
        headers.append(('Set-Cookie', f'{COOKIE}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0'))
        return {'ok': True}, headers
    if path == '/api/admin/export' and method == 'GET':
        return {**state(c), 'contributions': [contribution(c, r, True) for r in c.execute('SELECT * FROM contributions')], 'exportedAt': now()}, headers
    if path == '/api/admin/records' and method == 'POST': return record_save(c, body), headers
    if path.startswith('/api/admin/records/'):
        rid = path.rsplit('/', 1)[-1]
        if method == 'PUT': return record_save(c, body, rid), headers
        if method == 'DELETE':
            previous = c.execute('SELECT payload FROM records WHERE id=?', (rid,)).fetchone()
            if not previous: raise APIError(404, 'Ficha no disponible.')
            snapshot = json.loads(previous[0])
            snapshot['participantIds'] = [r[0] for r in c.execute('SELECT baile_id FROM participations WHERE fiesta_id=?', (rid,))]
            snapshot['fiestaIds'] = [r[0] for r in c.execute('SELECT fiesta_id FROM participations WHERE baile_id=?', (rid,))]
            remember(c, 'record', rid, snapshot)
            c.execute('DELETE FROM records WHERE id=?', (rid,))
            return {'ok': True}, headers
    if path == '/api/admin/contents' and method == 'PUT':
        validate_contents(body)
        current=c.execute("SELECT value FROM settings WHERE key='content_revision'").fetchone()
        revision=int(current[0]) if current else 0
        if env.get('HTTP_IF_MATCH') is not None and env['HTTP_IF_MATCH']!=str(revision): raise APIError(409,'Otra persona actualizó los contenidos. Actualiza el sitio antes de guardar.')
        remember(c, 'contents', 'site', {r[0]:json.loads(r[1]) for r in c.execute('SELECT key,payload FROM contents')})
        for k in body: c.execute('INSERT INTO contents VALUES(?,?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload', (k, dumps(body[k])))
        c.execute("INSERT INTO settings VALUES('content_revision',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(revision+1),))
        return {'ok': True}, headers
    if path.startswith('/api/admin/territories/') and method == 'PUT':
        code = path.rsplit('/', 1)[-1]
        row = c.execute('SELECT payload FROM territories WHERE code=?', (code,)).fetchone()
        if not row: raise APIError(404, 'Comuna no disponible.')
        t = json.loads(row[0])
        remember(c, 'territory', code, t)
        for key in ('name', 'region', 'province'): t[key] = text(body, key, 250, True)
        try:
            t['lat'], t['lng'] = float(body['lat']), float(body['lng'])
            if not (-90 <= t['lat'] <= 90 and -180 <= t['lng'] <= 180): raise ValueError()
        except (ValueError, KeyError, TypeError): raise APIError(400, 'Coordenadas no válidas.')
        t['description'] = text(body, 'description', 5000)
        c.execute('UPDATE territories SET payload=? WHERE code=?', (dumps(t), code))
        for r in all_records(c):
            if r['communeCode'] == code:
                r.update(commune=t['name'], region=t['region'], province=t['province'])
                if r['precision'] == 'comuna': r.update(lat=t['lat'], lng=t['lng'])
                c.execute('UPDATE records SET payload=?,revision=revision+1 WHERE id=?', (dumps(r), r['id']))
        return t, headers
    if path == '/api/admin/contributions' and method == 'GET': return [contribution(c, r, True) for r in c.execute('SELECT * FROM contributions ORDER BY created DESC')], headers
    if path == '/api/admin/import-contribution' and method == 'POST': return submit_contribution(c,env,body,True),headers
    if path.startswith('/api/admin/contributions/') and method == 'PATCH':
        status = body.get('status')
        if status not in ('pending', 'approved', 'rejected'): raise APIError(400, 'Decisión no válida.')
        if not c.execute('SELECT 1 FROM contributions WHERE id=?', (path.rsplit('/', 1)[-1],)).fetchone(): raise APIError(404, 'Aporte no disponible.')
        c.execute('UPDATE contributions SET status=? WHERE id=?', (status, path.rsplit('/', 1)[-1]))
        return {'ok': True}, headers
    if path == '/api/admin/assets' and method == 'GET': return [dict(r) for r in c.execute('SELECT * FROM assets ORDER BY created DESC')], headers
    if path == '/api/admin/assets' and method == 'POST':
        try: raw = base64.b64decode(body.get('data', ''), validate=True)
        except (TypeError, binascii.Error): raise APIError(400, 'La imagen no pudo leerse.')
        mime = file_type(raw)
        if mime not in ('image/png','image/jpeg','image/webp') or len(raw) > MAX_FILE: raise APIError(400, 'Selecciona una imagen PNG, JPG o WebP de hasta 8 MB.')
        aid = secrets.token_hex(16)
        target=DATA_DIR / 'media' / aid
        target.write_bytes(raw)
        target.chmod(0o600)
        c.execute('INSERT INTO assets VALUES(?,?,?,?,?)', (aid, text(body,'name',250,True), mime, len(raw), now()))
        return {'id':aid,'url':'/uploads/'+aid,'mime':mime}, headers
    if path == '/api/admin/revisions' and method == 'GET':
        return [dict(r) for r in c.execute('SELECT id,entity,entity_key,created FROM revisions ORDER BY id DESC LIMIT 100')], headers
    if path.startswith('/api/admin/revisions/') and method == 'POST':
        row=c.execute('SELECT * FROM revisions WHERE id=?',(path.rsplit('/',1)[-1],)).fetchone()
        if not row: raise APIError(404,'Versión no disponible.')
        value=json.loads(row['payload'])
        if row['entity']=='contents':
            return api(c,env,'PUT','/api/admin/contents',value)
        if row['entity']=='territory':
            return api(c,env,'PUT','/api/admin/territories/'+row['entity_key'],value)
        if row['entity']=='record':
            current=c.execute('SELECT * FROM records WHERE id=?',(row['entity_key'],)).fetchone()
            if current:
                value['revision']=current['revision']
                return record_save(c,value,row['entity_key']),headers
            if not c.execute('SELECT 1 FROM territories WHERE code=?',(value['communeCode'],)).fetchone(): raise APIError(400,'Recupera primero el territorio de esta ficha.')
            records=all_records(c)
            if any(r['color']==value['color'] for r in records): value['color']=next_color(c,len(records)+1)
            if any(r['markerNumber']==value['markerNumber'] for r in records): value['markerNumber']=1+max((r['markerNumber'] for r in records),default=0)
            value['revision']=value.get('revision',0)+1
            c.execute('INSERT INTO records VALUES(?,?,?,?,?)',(value['id'],value['type'],value['communeCode'],dumps(value),value['revision']))
            pairs=[(bid,value['id']) for bid in value.get('participantIds',[])] if value['type']=='fiesta' else [(value['id'],fid) for fid in value.get('fiestaIds',[])]
            for bid,fid in pairs:
                if c.execute("SELECT 1 FROM records WHERE id=? AND kind='baile'",(bid,)).fetchone() and c.execute("SELECT 1 FROM records WHERE id=? AND kind='fiesta'",(fid,)).fetchone(): c.execute('INSERT OR IGNORE INTO participations VALUES(?,?)',(bid,fid))
            return {'ok':True},headers
        raise APIError(400,'Esta versión no se puede recuperar.')
    if path == '/api/admin/users':
        authenticate(c, env, method != 'GET', admin=True)
        if method == 'GET': return [user_public(r) for r in c.execute('SELECT * FROM users ORDER BY name')], headers
        if method == 'POST':
            email = text(body, 'email', 250, True).lower()
            name = text(body, 'name', 160, True)
            role, password = body.get('role', 'editor'), str(body.get('password', ''))
            if role not in ('admin', 'editor') or '@' not in email or not 12 <= len(password) <= 200: raise APIError(400, 'Revisa el correo, rol y contraseña (mínimo 12 caracteres).')
            if c.execute('SELECT 1 FROM users WHERE email=?', (email,)).fetchone(): raise APIError(409, 'El correo ya tiene una cuenta.')
            uid = secrets.token_hex(12)
            c.execute('INSERT INTO users VALUES(?,?,?,?,?,1)', (uid, email, name, password_hash(password), role))
            return {'id': uid}, headers
    if path.startswith('/api/admin/users/') and method == 'PATCH':
        authenticate(c, env, True, admin=True)
        uid = path.rsplit('/', 1)[-1]
        row = c.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
        if not row: raise APIError(404, 'Cuenta no disponible.')
        if uid == u['id']: raise APIError(400, 'Mantén activa la cuenta con la que estás trabajando.')
        active = 1 if body.get('active') else 0
        if not active and row['role'] == 'admin' and c.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0] <= 1: raise APIError(400, 'Debe quedar una cuenta administradora activa.')
        c.execute('UPDATE users SET active=? WHERE id=?', (active, uid))
        c.execute('DELETE FROM sessions WHERE user_id=?', (uid,))
        return {'ok': True}, headers
    raise APIError(404, 'Ruta no disponible.')


def response(start, status, body, mime='application/json; charset=utf-8', extra=None):
    if not isinstance(body, bytes): body = dumps(body).encode()
    labels = {200:'OK',201:'Created',400:'Bad Request',401:'Unauthorized',403:'Forbidden',404:'Not Found',409:'Conflict',413:'Content Too Large',429:'Too Many Requests',500:'Internal Server Error'}
    headers = [('Content-Type', mime), ('Content-Length', str(len(body))), ('X-Content-Type-Options', 'nosniff'), ('Referrer-Policy', 'strict-origin-when-cross-origin'), ('X-Frame-Options', 'SAMEORIGIN'), ('Cache-Control', 'no-store')]
    start(f'{status} {labels.get(status,"OK")}', headers + (extra or []))
    return [body]


def app(env, start_response):
    path, method = unquote(env.get('PATH_INFO', '/')), env.get('REQUEST_METHOD', 'GET')
    try:
        if path.startswith('/api/'):
            try: length = int(env.get('CONTENT_LENGTH') or 0)
            except ValueError: raise APIError(400, 'Solicitud no válida.')
            if length < 0 or length > MAX_BODY: raise APIError(413, 'El envío supera el tamaño permitido.')
            body = {}
            if length:
                if 'application/json' not in env.get('CONTENT_TYPE', ''): raise APIError(400, 'Usa contenido JSON.')
                try: body = json.loads(env['wsgi.input'].read(length))
                except (json.JSONDecodeError, UnicodeDecodeError): raise APIError(400, 'El envío no pudo leerse.')
                if not isinstance(body, dict): raise APIError(400, 'Solicitud no válida.')
            with connect() as c:
                value, extra = api(c, env, method, path, body)
            return response(start_response, 200, value, extra=extra)
        if path.startswith('/media/') and method in ('GET', 'HEAD'):
            mid = path.rsplit('/', 1)[-1]
            with connect() as c:
                row = c.execute('SELECT m.*,a.status FROM media m JOIN contributions a ON a.id=m.contribution_id WHERE m.id=?', (mid,)).fetchone()
                if not row or (row['status'] != 'approved' and not session(c, env)): raise APIError(404, 'Archivo no disponible.')
                target = DATA_DIR / 'media' / mid
                if not target.is_file(): raise APIError(404, 'Archivo no disponible.')
                raw = target.read_bytes()
                extra = [('Content-Disposition', 'inline' if row['mime'].startswith(('image/', 'audio/')) else 'attachment; filename="documento.pdf"')]
                if row['mime'] == 'application/pdf': extra.append(('Content-Security-Policy', "sandbox"))
                return response(start_response, 200, raw, row['mime'], extra)
        if path.startswith('/uploads/') and method in ('GET','HEAD'):
            aid=path.rsplit('/',1)[-1]
            with connect() as c:
                row=c.execute('SELECT * FROM assets WHERE id=?',(aid,)).fetchone()
                if not row: raise APIError(404,'Imagen no disponible.')
                target=DATA_DIR/'media'/aid
                if not target.is_file(): raise APIError(404,'Imagen no disponible.')
                return response(start_response,200,target.read_bytes(),row['mime'])
        if method not in ('GET', 'HEAD'): raise APIError(404, 'Ruta no disponible.')
        target = (ROOT / 'public' / path.lstrip('/')).resolve() if path != '/' else ROOT / 'public/index.html'
        if not target.is_relative_to((ROOT / 'public').resolve()) or not target.is_file(): raise APIError(404, 'Página no disponible.')
        return response(start_response, 200, target.read_bytes(), mimetypes.guess_type(target.name)[0] or 'application/octet-stream')
    except APIError as exc:
        return response(start_response, exc.code, {'error': exc.message})
    except Exception:
        import traceback
        traceback.print_exc()
        return response(start_response, 500, {'error': 'No se pudo completar la operación. Inténtalo nuevamente.'})


class QuietHandler(WSGIRequestHandler):
    def log_message(self, fmt, *args):
        if str(args[1] if len(args)>1 else '').startswith('5'): super().log_message(fmt, *args)


def main():
    global DATA_DIR
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=int(os.environ.get('PORT', 8000)))
    p.add_argument('--data-dir')
    p.add_argument('--create-admin', action='store_true')
    p.add_argument('--reset-password', action='store_true')
    p.add_argument('--strictPort', action='store_true', help=argparse.SUPPRESS)
    a = p.parse_args()
    if a.data_dir: DATA_DIR = Path(a.data_dir).resolve()
    init_db()
    if a.create_admin or a.reset_password:
        email = input('Correo: ').strip().lower()
        password = getpass.getpass('Contraseña (mínimo 12 caracteres): ')
        if '@' not in email or not 12 <= len(password) <= 200: raise SystemExit('Correo o contraseña no válidos.')
        if getpass.getpass('Repite la contraseña: ') != password: raise SystemExit('Las contraseñas no coinciden.')
        with connect() as c:
            if a.reset_password:
                row = c.execute('SELECT id FROM users WHERE email=?', (email,)).fetchone()
                if not row: raise SystemExit('Cuenta no disponible.')
                c.execute('UPDATE users SET password=? WHERE email=?', (password_hash(password), email))
                c.execute('DELETE FROM sessions WHERE user_id=?', (row[0],))
            else:
                name = input('Nombre: ').strip() or 'Administración'
                c.execute('INSERT INTO users VALUES(?,?,?,?,?,1)', (secrets.token_hex(12), email, name, password_hash(password), 'admin'))
        print('Cuenta actualizada.')
        return
    print(f'Bailes Chinos: http://{a.host}:{a.port}')
    with make_server(a.host, a.port, app, handler_class=QuietHandler) as server: server.serve_forever()


if __name__ == '__main__': main()
else: init_db()
