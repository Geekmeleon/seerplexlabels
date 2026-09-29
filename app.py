import hmac
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from flask import Flask, abort, redirect, render_template, request, session, url_for
from plexapi.server import PlexServer

LABELS = ('Anime', 'Shared', 'Kids', 'Teen', 'Unavailable', 'Hide')
SEERR_URL = os.environ.get('SEERR_URL', 'http://seerr:5055').rstrip('/')
PLEX_URL = os.environ.get('PLEX_URL', 'http://plex:32400').rstrip('/')
API_KEY = os.environ.get('SEERR_API_KEY', '')
PLEX_TOKEN = os.environ.get('PLEX_TOKEN', '')
PASSWORD = os.environ.get('APP_PASSWORD', '')
SECRET = os.environ.get('SESSION_SECRET', '')
DB_PATH = os.environ.get('DB_PATH', '/data/labels.sqlite3')
POLL_SECONDS = max(30, int(os.environ.get('POLL_SECONDS', '120')))
PAGE_SIZE = 100
app = Flask(__name__, template_folder=str(Path(__file__).resolve().parent))
app.secret_key = SECRET
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict')
log = logging.getLogger(__name__)
lock = threading.RLock()


def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('CREATE TABLE IF NOT EXISTS selections (request_id INTEGER PRIMARY KEY, labels TEXT NOT NULL, applied TEXT NOT NULL DEFAULT "", last_error TEXT NOT NULL DEFAULT "", updated_at TEXT NOT NULL)')
    return conn


def seerr_get(path, params=None):
    response = requests.get(f'{SEERR_URL}/api/v1/{path.lstrip("/")}', headers={'X-Api-Key': API_KEY}, params=params, timeout=20)
    response.raise_for_status()
    return response.json()


def seerr_post(path, payload):
    response = requests.post(f'{SEERR_URL}/api/v1/{path.lstrip("/")}',
                             headers={'X-Api-Key': API_KEY}, json=payload, timeout=30)
    response.raise_for_status()
    return response.json()


def requests_list():
    output = []
    skip = 0
    while True:
        page = seerr_get('request', {'take': PAGE_SIZE, 'skip': skip, 'sort': 'added'})
        batch = page.get('results', [])
        output.extend(batch)
        if not batch or len(batch) < PAGE_SIZE:
            break
        skip += len(batch)
    return output


def selected(conn, request_id):
    row = conn.execute('SELECT * FROM selections WHERE request_id=?', (request_id,)).fetchone()
    return row


def update_state(request_id, applied=None, error=None):
    with lock, db() as conn:
        row = selected(conn, request_id)
        if row:
            conn.execute('UPDATE selections SET applied=?, last_error=? WHERE request_id=?',
                         (row['applied'] if applied is None else applied, row['last_error'] if error is None else error, request_id))


def find_plex_item(plex, media, kind):
    key = media.get('plexId') or media.get('plexRatingKey')
    if key:
        try:
            item = plex.fetchItem(int(key))
            if (kind == 'movie' and item.type == 'movie') or (kind == 'tv' and item.type == 'show'):
                return item
        except Exception as exc:
            log.warning('Plex rating key %s unavailable: %s', key, exc)
    ids = {f'tmdb://{media["tmdbId"]}'} if media.get('tmdbId') else set()
    if media.get('tvdbId'):
        ids.add(f'tvdb://{media["tvdbId"]}')
    if not ids:
        return None
    # GUID match avoids applying access labels to a similarly named title or remake.
    for section in plex.library.sections():
        if section.type != ('movie' if kind == 'movie' else 'show'):
            continue
        for item in section.all():
            if any(str(g.id).lower() in ids for g in item.guids):
                return item
    return None


def reconcile():
    reqs = requests_list()
    with lock, db() as conn:
        choices = {r['request_id']: r for r in conn.execute('SELECT * FROM selections WHERE labels != ""')}
    if not choices:
        return
    plex = PlexServer(PLEX_URL, PLEX_TOKEN)
    for req in reqs:
        rid = req.get('id')
        row = choices.get(rid)
        if not row:
            continue
        wanted = set(row['labels'].split(','))
        if wanted.issubset(set(filter(None, row['applied'].split(',')))):
            continue
        try:
            media = req.get('media') or {}
            kind = req.get('type') or media.get('mediaType')
            if kind not in ('movie', 'tv'):
                raise ValueError(f'Unsupported media type: {kind}')
            item = find_plex_item(plex, media, kind)
            if item is None:
                update_state(rid, error='Waiting for Plex match')
                continue
            existing = {label.tag for label in item.labels}
            missing = wanted - existing
            if missing:
                item.addLabel(sorted(missing))
                item.reload()
            if not wanted.issubset({label.tag for label in item.labels}):
                raise RuntimeError('Plex did not confirm all labels')
            update_state(rid, applied=','.join(sorted(wanted)), error='')
        except Exception as exc:
            log.exception('Request %s: label update failed', rid)
            update_state(rid, error=str(exc)[:250])


def worker():
    while True:
        try:
            reconcile()
        except Exception:
            log.exception('Reconciliation failed; retrying')
        time.sleep(POLL_SECONDS)


@app.before_request
def auth():
    if request.endpoint == 'health':
        return None
    if request.endpoint == 'login':
        return None
    if not session.get('authorized'):
        return redirect(url_for('login'))
    if request.method == 'POST' and not hmac.compare_digest(request.form.get('csrf', ''), session.get('csrf', '')):
        abort(403)


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if hmac.compare_digest(request.form.get('password', ''), PASSWORD):
            session.clear()
            session['authorized'] = True
            session['csrf'] = os.urandom(24).hex()
            return redirect(url_for('index'))
        error = 'Incorrect password'
    return render_template('login.html', error=error)


@app.get('/health')
def health():
    return 'ok'


@app.get('/')
def index():
    try:
        reqs = requests_list()
        with db() as conn:
            choices = {r['request_id']: dict(r) for r in conn.execute('SELECT * FROM selections')}
        entries = []
        for req in reqs:
            media = req.get('media') or {}
            kind = req.get('type') or media.get('mediaType')
            mid = media.get('tmdbId')
            details = {}
            if mid and kind in ('movie', 'tv'):
                try:
                    details = seerr_get(f'{kind}/{mid}')
                except requests.RequestException:
                    log.warning('Could not fetch details for %s %s', kind, mid)
            row = choices.get(req['id'], {})
            entries.append({'id': req['id'], 'title': details.get('title') or details.get('name') or f'{kind} · TMDB {mid}',
                            'kind': kind, 'selected': set(filter(None, row.get('labels', '').split(','))),
                            'applied': row.get('applied', ''), 'error': row.get('last_error', ''),
                            'date': str(req.get('createdAt', ''))[:10]})
        return render_template('index.html', entries=entries, labels=LABELS)
    except requests.RequestException as exc:
        return render_template('index.html', entries=[], labels=LABELS, error=f'Seerr connection failed: {exc}'), 503


def media_badges(info, previous):
    info = info or {}
    badges = []
    for field, suffix in (('status', ''), ('status4k', ' (4K)')):
        status = info.get(field)
        if status == 5:
            badges.append({'text': '✓ In Plex' + suffix, 'style': 'available'})
        elif status == 4:
            badges.append({'text': '◐ Partly in Plex' + suffix, 'style': 'available'})
        elif status in (2, 3):
            badges.append({'text': '⌛ ' + ('Pending request' if status == 2 else 'Processing') + suffix, 'style': 'requested'})
    if previous or info.get('requests'):
        badges.append({'text': '↻ Existing request', 'style': 'requested'})
    return badges


def matching_requests(reqs, kind, media_id):
    return [r for r in reqs if (r.get('type') or (r.get('media') or {}).get('mediaType')) == kind
            and (r.get('media') or {}).get('tmdbId') == media_id]


@app.get('/request')
def new_request():
    query = request.args.get('q', '').strip()[:120]
    results = []
    error = None
    if query:
        try:
            # Match the plus-separated search accepted by Seerr while keeping
            # the user's normal title text in the search box.
            search_query = '+'.join(query.split())
            response = seerr_get('search', {'query': search_query, 'page': 1})
            existing = requests_list()
            for item in response.get('results', []):
                if item.get('mediaType') in ('movie', 'tv') and isinstance(item.get('id'), int):
                    results.append({'id': item['id'], 'kind': item['mediaType'],
                                    'title': item.get('title') or item.get('name') or 'Untitled',
                                    'date': (item.get('releaseDate') or item.get('firstAirDate') or '')[:4],
                                    'badges': media_badges(item.get('mediaInfo'), matching_requests(existing, item['mediaType'], item['id']))})
        except requests.RequestException as exc:
            error = f'Seerr search failed: {exc}'
    return render_template('request_search.html', query=query, results=results, error=error)


@app.route('/request/<kind>/<int:media_id>', methods=['GET', 'POST'])
def request_detail(kind, media_id):
    if kind not in ('movie', 'tv') or media_id <= 0:
        abort(404)
    try:
        details = seerr_get(f'{kind}/{media_id}')
        previous = matching_requests(requests_list(), kind, media_id)
    except requests.RequestException as exc:
        return render_template('request_detail.html', error=f'Could not load Seerr details: {exc}',
                               details={}, kind=kind, media_id=media_id, labels=LABELS, seasons=[]), 503
    if details.get('id') != media_id:
        abort(404)
    seasons = sorted({s['seasonNumber'] for s in details.get('seasons', [])
                      if isinstance(s.get('seasonNumber'), int) and s['seasonNumber'] > 0}) if kind == 'tv' else []
    error = None
    badges = media_badges(details.get('mediaInfo'), previous)
    if badges:
        return render_template('request_detail.html', details=details, kind=kind, media_id=media_id,
                               seasons=seasons, labels=LABELS, badges=badges, blocked=True,
                               error='This title already has a request or Plex availability. Review it in Seerr or Existing requests before making changes.'), 409 if request.method == 'POST' else 200
    if request.method == 'POST':
        choices = request.form.getlist('label')
        if len(choices) != len(set(choices)) or set(choices) - set(LABELS):
            abort(400)
        payload = {'mediaType': kind, 'mediaId': media_id}
        if kind == 'tv':
            chosen = request.form.getlist('season')
            if not chosen or any(not value.isdecimal() for value in chosen):
                error = 'Select at least one season.'
            elif not set(map(int, chosen)).issubset(set(seasons)):
                abort(400)
            else:
                payload['seasons'] = sorted(set(map(int, chosen)))
        if not error:
            try:
                created = seerr_post('request', payload)
            except requests.HTTPError as exc:
                body = {}
                if exc.response is not None and 'json' in exc.response.headers.get('Content-Type', ''):
                    try:
                        body = exc.response.json()
                    except ValueError:
                        pass
                error = (body.get('message') if isinstance(body, dict) else None) or f'Seerr rejected the request: {exc}'
            except requests.RequestException as exc:
                error = f'Could not confirm the Seerr request. Check Seerr before trying again: {exc}'
            else:
                rid = created.get('id')
                if not isinstance(rid, int):
                    error = 'Seerr accepted the request, but did not return an ID. Find it on Existing requests and save its labels there.'
                else:
                    chosen_labels = ','.join(label for label in LABELS if label in choices)
                    try:
                        with lock, db() as conn:
                            conn.execute('INSERT INTO selections(request_id, labels, applied, last_error, updated_at) VALUES(?,?,?,?,?) '
                                         'ON CONFLICT(request_id) DO UPDATE SET labels=excluded.labels, last_error="", updated_at=excluded.updated_at',
                                         (rid, chosen_labels, '', '', datetime.now(timezone.utc).isoformat()))
                    except sqlite3.Error:
                        log.exception('Request %s created but labels could not be saved', rid)
                        error = f'Seerr request #{rid} was created, but labels could not be saved. Open Existing requests and save its labels there.'
                    else:
                        return redirect(url_for('index', created=rid))
    return render_template('request_detail.html', details=details, kind=kind, media_id=media_id,
                           seasons=seasons, labels=LABELS, error=error), 400 if error else 200


@app.route('/collection/<int:collection_id>', methods=['GET', 'POST'])
def collection_request(collection_id):
    entries, outcomes, error = [], [], None
    try:
        collection = seerr_get(f'collection/{collection_id}')
        existing = requests_list()
        for part in collection.get('parts', []):
            mid = part.get('id')
            if not isinstance(mid, int):
                continue
            details = seerr_get(f'movie/{mid}')
            badges = media_badges(details.get('mediaInfo'), matching_requests(existing, 'movie', mid))
            entries.append({'id': mid, 'title': details.get('title') or part.get('title'),
                            'date': details.get('releaseDate') or '', 'badges': badges,
                            'blocked': bool(badges)})
    except requests.RequestException as exc:
        return render_template('collection.html', collection={}, entries=[], labels=LABELS,
                               outcomes=[], error=f'Could not load collection status: {exc}'), 503
    entries.sort(key=lambda entry: (entry['date'] or '9999', entry['id']))
    if request.method == 'POST':
        values = request.form.getlist('movie')
        choices = request.form.getlist('label')
        if set(choices) - set(LABELS) or any(not value.isdecimal() for value in values):
            abort(400)
        ids = set(map(int, values))
        if not ids.issubset({entry['id'] for entry in entries}):
            abort(400)
        if not ids:
            error = 'Select at least one missing movie.'
        for entry in entries:
            if entry['id'] not in ids:
                continue
            if entry['blocked']:
                outcomes.append(f'{entry["title"]}: skipped — already requested or in Plex.')
                continue
            # Recheck immediately before submission, including requests made in another tab.
            try:
                fresh = seerr_get(f'movie/{entry["id"]}')
                if media_badges(fresh.get('mediaInfo'), matching_requests(requests_list(), 'movie', entry['id'])):
                    entry['blocked'] = True
                    outcomes.append(f'{entry["title"]}: skipped — status changed.')
                    continue
                created = seerr_post('request', {'mediaType': 'movie', 'mediaId': entry['id']})
            except requests.RequestException as exc:
                outcomes.append(f'{entry["title"]}: could not confirm request; check Seerr before retrying. {exc}')
                continue
            rid = created.get('id')
            entry['blocked'] = True
            if not isinstance(rid, int):
                outcomes.append(f'{entry["title"]}: submitted, but no request ID returned. Save labels on Existing requests.')
                continue
            try:
                with lock, db() as conn:
                    conn.execute('INSERT INTO selections(request_id, labels, applied, last_error, updated_at) VALUES(?,?,?,?,?) '
                                 'ON CONFLICT(request_id) DO NOTHING',
                                 (rid, ','.join(label for label in LABELS if label in choices), '', '', datetime.now(timezone.utc).isoformat()))
                outcomes.append(f'{entry["title"]}: request #{rid} created; selected labels saved.')
            except sqlite3.Error:
                log.exception('Collection request %s created but labels were not saved', rid)
                outcomes.append(f'{entry["title"]}: request #{rid} created, but labels could not be saved. Use Existing requests.')
    return render_template('collection.html', collection=collection, entries=entries, labels=LABELS,
                           outcomes=outcomes, error=error)


@app.post('/request/<int:rid>')
def save(rid):
    values = request.form.getlist('label')
    if len(values) != len(set(values)) or set(values) - set(LABELS):
        abort(400)
    try:
        if not any(r.get('id') == rid for r in requests_list()):
            abort(404)
    except requests.RequestException:
        abort(503)
    labels = ','.join(label for label in LABELS if label in values)
    with lock, db() as conn:
        previous = selected(conn, rid)
        # Empty selection stops automation. Existing Plex labels are never removed.
        conn.execute('INSERT INTO selections(request_id, labels, applied, last_error, updated_at) VALUES(?,?,?,?,?) '
                     'ON CONFLICT(request_id) DO UPDATE SET labels=excluded.labels, applied=excluded.applied, last_error="", updated_at=excluded.updated_at',
                     (rid, labels, previous['applied'] if previous else '', '', datetime.now(timezone.utc).isoformat()))
    return redirect(url_for('index'))


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    if not all((API_KEY, PLEX_TOKEN, PASSWORD, SECRET)) or len(SECRET) < 32:
        raise SystemExit('Set SEERR_API_KEY, PLEX_TOKEN, APP_PASSWORD, and SESSION_SECRET (32+ characters)')
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with db():
        pass
    threading.Thread(target=worker, daemon=True).start()
    app.run(host='0.0.0.0', port=8080, use_reloader=False)
