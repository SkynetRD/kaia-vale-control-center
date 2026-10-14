"""KAIA VALE — Mission Control v8.0.
Approval-path hardening over v6.5. GitHub bus and inbox + ACK protocol unchanged;
decision records only gain additive fields (asset_file, asset_sha = SHA-256 of the asset bytes, asset_git_sha).
- Asset approvals only through job/version decisions: Muse's yes/no channel can no
  longer approve an asset that is not registered as a version.
- Decisions are bound to the exact asset blob (sha) and are idempotent (uuid5 id +
  create-only write), so double taps / stale API reads cannot create duplicates.
- Sync health banner: unprocessed inbox decisions and Muse heartbeat age are shown
  from real bus data, so a stopped backend is visible instead of looking "Idle".
- Default job = one waiting for Elvin, else the most recently updated.
- v6.7: asset_sha is SHA-256 of the asset bytes (what the backend verifies); non-protocol
  decision records (e.g. chat approvals) are shown as not valid, never as approved.
- v6.8: QC panel reads the supervisor's current visual_coverage (Spanish groups); versions
  without decision buttons explain why (CORREGIR / ESCALAR / not synced).
- v6.9: publish/v1 — authorize/revoke publication separately from approve_final, shown only
  when the backend declares protocol/capabilities.json publish_v1=true.
- v8.0: speed + reliability. The whole branch is read with ONE recursive git-tree call (10 s cache) and files
  are fetched by blob sha (cached): a rerun costs ~0 API calls instead of ~100. The 30 s full-page
  st_autorefresh (which dropped clicks and re-fetched everything) is replaced by a fragment that polls the bus
  and reruns only when something changed. Login survives page reloads (signed 30-day cookie). Approving a
  piece removes it from the queue and Studio jumps to the next one waiting for Elvin.
- v7.0: Agenda tab — proposals by planned day (jobs/<job>/plan.json, plan/v1) with
  approve / reject / request changes per image; same decision protocol as Studio.

v8.1: pestaña Publicar (autorizadas / sin autorizar / sin aprobar / historial con fecha, hora PT, formato y caption, y revocar);
Studio muestra la propuesta de Muse y un resumen antes de autorizar; tarjetas de Agenda muestran estado de autorización;
ELVIN_DECISION_REQUIRED decidible cuando capabilities.elvin_decision_actionable es true (tarea 0011).
"""
import base64, hashlib, hmac, html, inspect, io, json, re, time, uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
import requests
import streamlit as st
import streamlit.components.v1 as components

APP_VERSION = "v10.2"
DECISION_NS = uuid.UUID("6f1c2d3e-9a4b-4c5d-8e7f-0a1b2c3d4e5f")   # fixed namespace for idempotent decision ids
HEARTBEAT_STALE_H = 2          # Muse heartbeat older than this = no live activity
MUSE_DOWN_MIN = 15             # v10: Muse with an open task and no own heartbeat for this long = down
DAEMON_DOWN_S = 600            # v10: daemon_health reaches the bus every 5 min (was every cycle)
# Questions that try to approve/authorize an asset or a publication must go through job/version decisions.
ASSET_APPROVAL_RE = re.compile(r"aprob|apru[eé]b|autoriz|publica|regener", re.I)
WATCH_EVERY_S = 12          # cheap bus poll (1 API call, no full rerun unless something changed)
WATCH_PENDING_S = 5         # faster poll while a decision waits for its ACK
MIN_RERUN_GAP_S = 30        # never rerun the whole app more often than this because of background changes
AUTH_COOKIE = "kv_auth"
AUTH_DAYS = 30
ACK_TIMEOUT_S = 180            # warn if the backend has not ACKed after 3 min
NOTICE_TTL_S = 180             # how long decision notices stay visible
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_S = 60
RECENT_ACK_WINDOW_H = 6       # window for the accepted-ACK-not-yet-synced check
RECENT_ACK_MAX_COMMITS = 20
ACK_OK = {"accepted"}
ACK_FAIL = {"rejected", "error", "failed", "invalid"}
DECISION_LABELS = {"approve_final": "Approved by Elvin", "reject": "Rejected by Elvin",
                   "request_changes": "Changes requested"}
DECISION_TONE = {"approve_final": "green", "reject": "red", "request_changes": "amber"}
ACTION_NAMES = {"approve_final": "Approve", "reject": "Reject", "request_changes": "Request changes"}
VERDICT_LABELS = {"READY_FOR_ELVIN_REVIEW": ("Ready for review", "violet"), "CORREGIR": ("Needs fixes", "amber"),
                  "ESCALAR": ("Escalated", "red"), "ELVIN_DECISION_REQUIRED": ("Needs your decision", "violet"), "APROBADO": ("QA approved", "green"),
                  "APPROVED": ("Approved by Elvin", "green"), "DECIDIDO": ("Decided by Elvin", "green"),
                  "CHANGES_REQUESTED": ("Changes requested", "amber"), "REJECTED": ("Rejected by Elvin", "red"),
                  "READY_PENDING_PUSH": ("Uploading to bus", "violet")}
DECISION_ICONS = {"approve_final": "✓", "reject": "✕", "request_changes": "↻"}

st.set_page_config(page_title="Kaia Vale · Mission Control", layout="wide", initial_sidebar_state="collapsed")

try:
    PASSWORD = str(st.secrets["DASHBOARD_PASSWORD"])
    TOKEN = st.secrets["GITHUB_TOKEN"]
    REPO = st.secrets["SYNC_REPO"]
    BRANCH = st.secrets.get("SYNC_BRANCH", "main")
except Exception:
    st.error("Faltan DASHBOARD_PASSWORD, GITHUB_TOKEN y SYNC_REPO en Secrets.")
    st.stop()

API = f"https://api.github.com/repos/{REPO}/contents"
GIT_API = f"https://api.github.com/repos/{REPO}"
H_RAW = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github.raw"}
H_JSON = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"}

DEFAULTS = {"auth": False, "login_attempts": 0, "login_locked_until": 0.0,
            "tab": "Hoy", "sel_ver": None, "compare": False, "focus": False, "inspector": False,
            "change_open": False, "inflight": {}, "local_decided": {}, "notice": None,
            "answered_q": None}
for k, v in DEFAULTS.items():
    st.session_state.setdefault(k, v.copy() if isinstance(v, dict) else v)

st.markdown(r"""<style>
:root{--bg:#08090e;--panel:#10121a;--panel2:#151824;--line:#252a3a;--text:#f5f7ff;--muted:#8e96ad;
--violet:#8b5cf6;--cyan:#22d3ee;--green:#34d399;--red:#fb7185;--amber:#fbbf24}
html,body,[data-testid="stAppViewContainer"]{background:var(--bg);color:var(--text)}
[data-testid="stHeader"],[data-testid="stToolbar"],#MainMenu,footer{display:none!important}
[data-testid="stMain"]{padding-top:0!important}
.block-container,[data-testid="stMainBlockContainer"]{max-width:2200px;padding:.4rem .75rem .75rem!important}
[data-testid="stVerticalBlock"]{gap:.45rem}
/* hidden refresh timers: keep the iframes alive but take no space */
.st-key-mission_control_refresh,.st-key-pending_decision_refresh{position:absolute!important;height:0!important;overflow:hidden!important;margin:0!important}
/* header */
.kv-top{display:flex;align-items:center;gap:12px;height:40px;margin-bottom:2px}
.kv-logo{font-weight:900;letter-spacing:.14em;white-space:nowrap}.kv-logo span{background:linear-gradient(90deg,var(--violet),var(--cyan));-webkit-background-clip:text;color:transparent}
.kv-job{color:var(--muted);font-size:.74rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.kv-live{margin-left:auto;display:flex;align-items:center;gap:7px;color:var(--muted);font-size:.82rem;white-space:nowrap}
.dot{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 10px var(--green);flex:none}.dot.off{background:#4a5062;box-shadow:none}
/* no fade while Streamlit reruns: content stays crisp and clickable */
[data-stale="true"],[data-stale="true"] *{opacity:1!important;transition:none!important}
[data-testid="stStatusWidget"]{display:none!important}
/* buttons */
[data-testid="stButton"] button,[data-testid="stFormSubmitButton"] button{border-radius:10px;min-height:36px;font-weight:600}
button[kind="secondary"]{border:1px solid var(--line)!important;background:#11131b!important;color:var(--text)!important}
button[kind="secondary"]:hover{border-color:#545b74!important}
button[kind="primary"]{background:var(--violet)!important;border:1px solid var(--violet)!important;color:#fff!important}
button[kind="primary"]:hover{background:#7c4cf0!important}
.st-key-dec_approve button{min-height:44px;font-weight:800;letter-spacing:.04em;box-shadow:0 0 0 1px rgba(139,92,246,.4),0 6px 22px rgba(139,92,246,.28)}
.st-key-dec_reject button{min-height:44px;border-color:rgba(251,113,133,.55)!important;color:#ffb3c0!important}
.st-key-dec_reject button:hover{background:rgba(251,113,133,.1)!important}
.st-key-dec_changes button{min-height:44px;border-color:rgba(251,191,36,.5)!important;color:#ffe2a0!important}
.st-key-dec_changes button:hover{background:rgba(251,191,36,.08)!important}
/* pipeline */
.pipe-title,.ins-title{font-size:.66rem;letter-spacing:.16em;color:var(--muted);font-weight:800;text-transform:uppercase;margin:2px 0 8px}
.pipe-item{display:flex;align-items:center;gap:9px;padding:9px 10px;border-radius:10px;color:var(--muted);font-size:.82rem;margin-bottom:5px;border:1px solid transparent}
.pipe-item.done{color:#b7f7d4}.pipe-item.active{color:white;background:#17152a;border-color:#5b3eb0}.pipe-item.pending{opacity:.58}
.pipe-item.stopped{color:#ffd1d9;background:#2a1519;border-color:#7a2d3b}
.pi{width:19px;height:19px;border-radius:50%;display:grid;place-items:center;border:1px solid #4a5062;font-size:.66rem;flex:none}.done .pi{border-color:var(--green);color:var(--green)}.active .pi{border-color:var(--violet);background:#6d45db;color:white}
.stopped .pi{border-color:var(--red);color:var(--red)}
.pipe-mini{display:flex;gap:4px;overflow-x:auto;scrollbar-width:none;margin-bottom:2px}.pipe-mini::-webkit-scrollbar{display:none}
.pipe-mini .pipe-item{margin:0;padding:5px 8px;font-size:.7rem;gap:5px;flex:none}.pipe-mini .pi{width:15px;height:15px;font-size:.58rem}
/* canvas */
.canvas-label{display:flex;justify-content:space-between;align-items:center;gap:8px;color:var(--muted);font-size:.75rem;margin:0 2px 4px;padding-top:3px}
.badge{padding:4px 9px;border-radius:999px;background:#171923;border:1px solid var(--line);font-size:.7rem;font-weight:800;white-space:nowrap}
.badge.violet{color:#d9ccff;border-color:rgba(139,92,246,.6);background:rgba(139,92,246,.12)}
.badge.green{color:#b7f7d4;border-color:rgba(52,211,153,.55);background:rgba(52,211,153,.1)}
.badge.red{color:#ffc2cc;border-color:rgba(251,113,133,.55);background:rgba(251,113,133,.1)}
.badge.amber{color:#ffe2a0;border-color:rgba(251,191,36,.5);background:rgba(251,191,36,.08)}
[data-testid="stImage"] img{max-height:calc(100vh - 300px);object-fit:contain!important;background:#05060a;border-radius:10px}
video{max-height:calc(100vh - 300px)!important;background:#05060a!important;border-radius:10px}
.st-key-kv_focus [data-testid="stImage"] img,.st-key-kv_focus video{max-height:calc(100vh - 110px)!important}
/* agenda cards: smaller media so several proposals fit on screen */
[class*="st-key-ag_card_"] [data-testid="stImage"] img,[class*="st-key-ag_card_"] video,[class*="st-key-na_card_"] [data-testid="stImage"] img{max-height:46vh!important}
[class*="st-key-na_auth_"] [data-testid="stImage"] img{max-height:160px!important}
/* review / decision */
.review{margin-bottom:8px;border:1px solid rgba(139,92,246,.55);background:linear-gradient(90deg,rgba(139,92,246,.1),rgba(34,211,238,.04));border-radius:12px;padding:9px 12px;color:#ddd9ff;font-size:.8rem}
.review.green{border-color:rgba(52,211,153,.5);background:rgba(52,211,153,.07);color:#c9f8e2}
.review.red{border-color:rgba(251,113,133,.5);background:rgba(251,113,133,.07);color:#ffd1d9}
.review.amber,.review.warn{border-color:rgba(251,191,36,.55);background:rgba(251,191,36,.06);color:#ffe9b0}
/* inspector */
.ins{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:10px;margin-top:8px}.ins:first-child{margin-top:0}
.ins-head{display:flex;justify-content:space-between;align-items:center;gap:8px;font-size:.9rem}
.qc{display:flex;justify-content:space-between;padding:7px 8px;background:#171923;border-radius:8px;margin:5px 0;font-size:.78rem}.ok{color:var(--green)}.bad{color:var(--red)}.na{color:var(--muted)}
.find{font-size:.76rem;line-height:1.42;color:#c5cada;padding:6px 0;border-bottom:1px solid #202432}.find:last-child{border-bottom:0;margin-bottom:8px}
.spec{display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:.72rem;color:var(--muted)}.spec b{display:block;color:var(--text);margin-top:2px}
.livebar{display:flex;align-items:center;gap:9px;height:34px;padding:0 12px;background:#0e1017;border:1px solid var(--line);border-radius:11px;color:var(--muted);font-size:.78rem;overflow:hidden;white-space:nowrap}.livebar b{color:var(--text)}
.livebar span:last-child{overflow:hidden;text-overflow:ellipsis}
.small{font-size:.72rem;color:var(--muted)}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:2px 0 6px}
.chip{display:inline-flex;align-items:center;gap:7px;padding:6px 12px;border-radius:999px;background:#12151b;border:1px solid var(--line);font-size:.82rem;font-weight:600}
.chip i{width:8px;height:8px;border-radius:50%;background:var(--green);flex:none}
.chip.red{border-color:rgba(251,113,133,.6);color:#ffc2cc}.chip.red i{background:var(--red)}
.chip.amber{border-color:rgba(251,191,36,.5);color:#ffe2a0}.chip.amber i{background:var(--amber)}
.rt{font-weight:600;line-height:1.25}.rs{color:var(--muted);font-size:.78rem;line-height:1.3}
.sec{font-size:.7rem;letter-spacing:.16em;color:var(--muted);font-weight:800;text-transform:uppercase;margin:10px 0 2px}
[class*="st-key-hoy_row_"] [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;gap:.5rem!important;align-items:center}
[class*="st-key-hoy_row_"] [data-testid="stColumn"]{min-width:0!important}
[class*="st-key-hoy_row_"] [data-testid="stImage"] img{max-height:72px!important;width:auto!important;border-radius:6px}
.kv-foot{font-size:.66rem;color:#4a5062;text-align:right;margin-top:4px}
.mobile-only{display:none}
@media(min-width:761px){
.st-key-ag_grid,.st-key-ag_review_grid,.st-key-ag_auth_grid,.st-key-pb_grid_active,.st-key-pb_grid_auth{display:grid!important;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:.9rem!important;align-items:start}
.st-key-ag_grid>*,.st-key-ag_review_grid>*,.st-key-ag_auth_grid>*,.st-key-pb_grid_active>*,.st-key-pb_grid_auth>*{min-width:0}
[class*="st-key-na_auth_"] [data-testid="stImage"] img{max-height:220px!important}
}
@media(max-width:760px){
[class*="st-key-pba_"] [data-testid="stImage"] img,[class*="st-key-pb_auth_"] [data-testid="stImage"] img,[class*="st-key-na_auth_"] [data-testid="stImage"] img{max-height:240px!important;width:auto!important;margin:0 auto}
.block-container,[data-testid="stMainBlockContainer"]{padding:.35rem .6rem 5rem!important}
.desktop-only,.st-key-kv_pipe,.st-key-kv_insp,.st-key-tog_insp{display:none!important}
.mobile-only{display:block}.pipe-mini.mobile-only{display:flex}div.mobile-only{padding-bottom:10px}
.pipe-mini .pipe-item:not(.active):not(.stopped) b{display:none}
.kv-logo{font-size:.8rem}.kv-top{height:36px}
/* nav: tabs + Salir in one row, job selector full width below */
.st-key-kv_nav [data-testid="stHorizontalBlock"]{flex-wrap:wrap!important;gap:.4rem!important}
.st-key-kv_nav [data-testid="stColumn"]{flex:1 1 0!important;min-width:0!important;width:auto!important}
.st-key-kv_nav [data-testid="stColumn"]:nth-child(5){order:8;flex:1 1 100%!important}
.st-key-kv_nav button{min-height:34px!important;padding:0 2px!important}
.st-key-kv_nav button p{font-size:.72rem!important;white-space:nowrap!important}
/* decision + tools rows never stack */
.st-key-kv_decide [data-testid="stHorizontalBlock"],.st-key-kv_tools [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;gap:.4rem!important}
.st-key-kv_decide [data-testid="stColumn"],.st-key-kv_tools [data-testid="stColumn"]{flex:1 1 0!important;min-width:0!important;width:auto!important}
.st-key-kv_decide button{padding:0 4px!important;font-size:.8rem!important}
.st-key-ag_quick [data-testid="stHorizontalBlock"],[class*="st-key-ag_card_"] [data-testid="stHorizontalBlock"],[class*="st-key-na_card_"] [data-testid="stHorizontalBlock"],[class*="st-key-na_auth_"] [data-testid="stHorizontalBlock"],[class*="st-key-na_unpl_row_"] [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;gap:.5rem!important;align-items:center}
[class*="st-key-na_unpl_row_"] [data-testid="stColumn"]{flex:1 1 0!important;min-width:0!important;width:auto!important}
.st-key-ag_quick [data-testid="stColumn"],[class*="st-key-ag_card_"] [data-testid="stColumn"],[class*="st-key-na_card_"] [data-testid="stColumn"]{flex:1 1 0!important;min-width:0!important;width:auto!important}
[class*="st-key-na_auth_"] [data-testid="stColumn"]:first-child{flex:0 0 30%!important;min-width:0!important}
[class*="st-key-na_auth_"] [data-testid="stColumn"]:last-child{flex:1 1 0!important;min-width:0!important}
.st-key-ag_quick button,[class*="st-key-ag_card_"] button,[class*="st-key-na_card_"] button{padding:0 4px!important;font-size:.78rem!important}
[data-testid="stImage"] img,video{max-height:58vh!important}
.livebar{position:sticky;bottom:4px;z-index:20}}
</style>""", unsafe_allow_html=True)


# ───────────────────────── helpers ─────────────────────────
def esc(x):
    return html.escape("" if x is None else str(x))

def num(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default

def _url(path):
    return f"{API}/{quote(str(path), safe='/')}"

def _get(path, headers):
    """Returns (status_code, response) — status -1 on network error."""
    try:
        r = requests.get(_url(path), params={"ref": BRANCH}, headers=headers, timeout=20)
        return r.status_code, r
    except requests.RequestException:
        return -1, None

def _fetch(path):
    code, r = _get(path, H_RAW)
    return code, (r.content if code == 200 else None)

@st.cache_resource(ttl=10, show_spinner=False)
def gh_index():
    """The whole branch in ONE call (recursive git tree). Every control-file lookup below is answered from
    this index + blobs cached by sha, so a rerun costs ~1 API call instead of ~100.
    Returns {'files': {path: entry}, 'dirs': {parent: {name: entry}}, 'subdirs': {parent: [names]}}; None if unavailable."""
    try:
        r = requests.get(f"{GIT_API}/git/trees/{quote(BRANCH, safe='')}", params={"recursive": "1"},
                         headers=H_JSON, timeout=20)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("truncated") or not isinstance(data.get("tree"), list):
        return None
    files, dirs, subdirs = {}, {}, {}
    for e in data["tree"]:
        if not isinstance(e, dict) or not e.get("path"):
            continue
        path = e["path"]
        parent, _, name = path.rpartition("/")
        if e.get("type") == "blob":
            ent = {"sha": e.get("sha"), "path": path, "size": e.get("size", 0)}
            files[path] = ent
            dirs.setdefault(parent, {})[name] = ent
        elif e.get("type") == "tree":
            subdirs.setdefault(parent, []).append(name)
    for v in subdirs.values():
        v.sort()
    return {"files": files, "dirs": dirs, "subdirs": subdirs}

@st.cache_data(ttl=20, show_spinner=False, max_entries=500)
def _gh_fetch_legacy(path):
    return _fetch(path)

@st.cache_data(ttl=3600, show_spinner=False, max_entries=3000)
def gh_blob_by_sha(sha):
    """Immutable: a git blob never changes, so it is cached by sha."""
    r = requests.get(f"{GIT_API}/git/blobs/{sha}", headers=H_RAW, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    return r.content

def gh_fetch(path):
    """Small control files. (status, bytes); 404 when the path is not in the branch."""
    idx = gh_index()
    if idx is not None:
        ent = idx["files"].get(path)
        if ent is None:
            return 404, None
        if num(ent.get("size")) <= 2_000_000:
            try:
                return 200, gh_blob_by_sha(ent["sha"])
            except Exception:
                pass
    return _gh_fetch_legacy(path)

def _dir(path):
    code, r = _get(path, H_JSON)
    if code == 404:
        return {}
    if code != 200:
        return None
    try:
        data = r.json()
    except ValueError:
        return None
    if not isinstance(data, list):
        return None
    return {e["name"]: {"sha": e.get("sha"), "path": e.get("path"), "size": e.get("size", 0)}
            for e in data if isinstance(e, dict) and e.get("type") == "file" and e.get("name")}

@st.cache_data(ttl=20, show_spinner=False, max_entries=50)
def _gh_subdirs_legacy(path):
    code, r = _get(path, H_JSON)
    if code != 200:
        return []
    try:
        data = r.json()
    except ValueError:
        return []
    return sorted(e["name"] for e in data if isinstance(data, list) and isinstance(e, dict) and e.get("type") == "dir" and e.get("name"))

@st.cache_data(ttl=20, show_spinner=False, max_entries=300)
def _gh_dir_legacy(path):
    return _dir(path)

def gh_subdirs(path):
    """Names of subdirectories of path; [] if missing or on error."""
    idx = gh_index()
    return list(idx["subdirs"].get(str(path), [])) if idx is not None else _gh_subdirs_legacy(path)

def gh_dir(path):
    """Directory listing {name: {sha, path, size}}; {} if missing; None on error."""
    idx = gh_index()
    if idx is None:
        return _gh_dir_legacy(path)
    return {n: dict(e) for n, e in idx["dirs"].get(str(path), {}).items()}

def _clear_all_listings():
    _MEMO.clear() if "_MEMO" in globals() else None
    for f in (gh_index, _gh_fetch_legacy, _gh_subdirs_legacy, _gh_dir_legacy):
        f.clear()
gh_fetch.clear = _clear_all_listings
gh_dir.clear = _clear_all_listings
gh_subdirs.clear = _clear_all_listings

def _blob(path):
    code, b = _fetch(path)
    if code != 200 or b is None:
        raise RuntimeError(f"HTTP {code}")
    return b

@st.cache_data(ttl=3600, show_spinner=False, max_entries=48)
def gh_blob(path, sha):
    """Large immutable assets keyed by git sha. Raises on failure so errors are never cached."""
    return _blob(path)

@st.cache_data(ttl=3600, show_spinner=False, max_entries=2000)
def gh_small_blob(path, sha):
    """Small immutable JSON files keyed by git sha (verdict/meta/decision/inbox)."""
    return _blob(path)

@st.cache_data(ttl=86400, show_spinner=False, max_entries=800)
def gh_thumb(path, sha, width=640):
    """Small JPEG preview (~60-100 KB) of a big PNG, cached by git sha. Raises on failure (never cached)."""
    from PIL import Image
    im = Image.open(io.BytesIO(_blob(path))).convert("RGB")
    im.thumbnail((width, width * 2))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=82, optimize=True)
    return out.getvalue()

def thumb(info):
    if not info or not info.get("sha"):
        return None
    try:
        return gh_thumb(info["path"], info["sha"])
    except Exception:
        return None

def blob(info, *, small=True):
    if not info or not info.get("sha"):
        return None
    try:
        return (gh_small_blob if small else gh_blob)(info["path"], info["sha"])
    except Exception:
        return None

def parse_json(b, default):
    if not b:
        return default
    try:
        return json.loads(b.decode("utf-8"))
    except Exception:
        return default

def gh_json(path, default=None, *, fresh=False):
    _, b = _fetch(path) if fresh else gh_fetch(path)
    return parse_json(b, default)

def actionable_verdicts():
    """Verdicts on which Elvin can decide. ELVIN_DECISION_REQUIRED only when the backend declares it can apply it."""
    caps = gh_json("protocol/capabilities.json", {})
    caps = caps if isinstance(caps, dict) else {}
    return {"READY_FOR_ELVIN_REVIEW"} | ({"ELVIN_DECISION_REQUIRED"} if caps.get("elvin_decision_actionable") is True else set())

def as_dict(x):
    return x if isinstance(x, dict) else {}

def as_list(x):
    return x if isinstance(x, list) else []

def clear_bus_cache():
    gh_fetch.clear()
    gh_dir.clear()
    try:
        gh_tree.clear()
    except NameError:
        pass

def gh_put_json(path, obj, msg, *, create_only=False, raw=False):
    data = obj if raw else json.dumps(obj, ensure_ascii=False, indent=2)
    content = base64.b64encode(data.encode("utf-8")).decode()
    last = "error desconocido"
    for attempt in range(2):
        body = {"message": msg, "content": content, "branch": BRANCH}
        if not create_only:
            code, r = _get(path, H_JSON)
            if code == 200:
                try:
                    sha = r.json().get("sha")
                except ValueError:
                    sha = None
                if sha:
                    body["sha"] = sha
        try:
            r = requests.put(_url(path), headers=H_JSON, json=body, timeout=20)
        except requests.RequestException as e:
            return False, f"sin conexión: {type(e).__name__}"
        if r.status_code in (200, 201):
            return True, "ok"
        try:
            detail = r.json().get("message", "")[:160]
        except ValueError:
            detail = r.text[:160]
        hint = {401: "token inválido", 403: "token sin permiso de escritura", 404: "repo/ruta no encontrada",
                409: "conflicto de escritura concurrente",
                422: "el archivo ya existe" if create_only else ""}.get(r.status_code, "")
        last = f"HTTP {r.status_code}: {detail} {hint}".strip()
        if r.status_code == 409 and not create_only and attempt == 0:
            time.sleep(0.6)   # one retry with a fresh sha
            continue
        break
    return False, last

def set_notice(text, level="info"):
    st.session_state.notice = {"text": text, "level": level, "ts": time.time()}

def hours_since(iso):
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except Exception:
        return 999

def human_age(h):
    if h >= 999:
        return "?"
    m = int(h * 60)
    return "ahora" if m < 1 else f"{m} min" if m < 60 else f"{int(h)} h" if h < 24 else f"{int(h / 24)} d"

def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ───────────────────────── auth ─────────────────────────
def _auth_token(exp):
    sig = hmac.new(PASSWORD.encode("utf-8"), f"kv-auth|{exp}".encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"

def _auth_token_ok(tok):
    try:
        exp, sig = str(tok).split(".", 1)
        return int(exp) > time.time() and hmac.compare_digest(sig, _auth_token(int(exp)).split(".", 1)[1])
    except Exception:
        return False

def _cookie_script(value, max_age):
    # Runs inside the component iframe (same origin as the app); Secure only on https.
    return ("<script>try{var s=location.protocol==='https:'?'; Secure':'';"
            f"document.cookie='{AUTH_COOKIE}={value}; max-age={max_age}; path=/; SameSite=Lax'+s;"
            "}catch(e){}</script>")

def _run_html(code):
    """Invisible same-origin iframe that runs a tiny script (st.iframe on current Streamlit; components.html before)."""
    if hasattr(st, "iframe"):
        st.iframe(code, height=1)
    else:
        components.html(code, height=0)

if not st.session_state.auth and not st.session_state.get("cookie_clear"):
    try:
        if _auth_token_ok(st.context.cookies.get(AUTH_COOKIE)):
            st.session_state.auth = True
    except Exception:
        pass

if not st.session_state.auth:
    st.markdown("<div style='max-width:360px;margin:14vh auto 1rem;text-align:center'><div class='kv-logo'><span>KAIA VALE</span></div><h2>Mission Control</h2></div>", unsafe_allow_html=True)
    with st.form("login"):
        pw = st.text_input("Password", type="password", label_visibility="collapsed", placeholder="Password")
        go = st.form_submit_button("Entrar", width="stretch")
    if go:
        wait = st.session_state.login_locked_until - time.time()
        if wait > 0:
            st.error(f"Demasiados intentos. Espera {int(wait) + 1} s.")
        elif hmac.compare_digest(pw.encode("utf-8"), PASSWORD.encode("utf-8")):
            st.session_state.auth = True
            st.session_state.login_attempts = 0
            st.session_state.cookie_to_set = _auth_token(int(time.time()) + AUTH_DAYS * 86400)
            st.rerun()
        else:
            st.session_state.login_attempts += 1
            if st.session_state.login_attempts >= MAX_LOGIN_ATTEMPTS:
                st.session_state.login_attempts = 0
                st.session_state.login_locked_until = time.time() + LOGIN_LOCKOUT_S
                st.error(f"Password incorrecto. Bloqueado {LOGIN_LOCKOUT_S} s.")
            else:
                st.error("Password incorrecto.")
    if st.session_state.pop("cookie_clear", False):
        _run_html(_cookie_script("", 0))
    st.stop()

_ck = st.session_state.pop("cookie_to_set", None)
if _ck:
    _run_html(_cookie_script(_ck, AUTH_DAYS * 86400))

# Background refresh: a tiny fragment polls the bus (1 cached API call) and only reruns the whole app when
# something actually changed, never interrupting a click for nothing (the old 30 s st_autorefresh did).
def _bus_sig():
    idx = gh_index()
    if idx is None:
        return None
    h = hashlib.md5()
    for p_, e_ in idx["files"].items():
        if p_ == "progress/daemon_health.json":
            continue   # v10: daemon liveness alone never reruns the whole app
        h.update(p_.encode("utf-8")); h.update(str(e_.get("sha")).encode("utf-8"))
    return h.hexdigest()

def _make_watcher(every):
    @st.fragment(run_every=every)
    def _watch():
        pending = bool(st.session_state.get("inflight"))
        if pending:
            gh_index.clear()          # waiting for an ACK: look at the bus right now
        sig = _bus_sig()
        last = st.session_state.get("bus_sig")
        if sig is None:
            return
        if last is None:
            st.session_state.bus_sig = sig
            return
        if sig != last and (pending or time.time() - st.session_state.get("last_full", 0) >= MIN_RERUN_GAP_S):
            st.rerun()
    return _watch
st.session_state.bus_sig = _bus_sig()
st.session_state.last_full = time.time()
_make_watcher(WATCH_PENDING_S if st.session_state.get("inflight") else WATCH_EVERY_S)()


# ───────────────────────── snapshot / job ─────────────────────────
snap_code, snap_b = gh_fetch("snapshot.json")
if snap_code == 404:
    st.info("Sin jobs sincronizados (snapshot.json no existe todavía).")
    st.stop()
if snap_code != 200:
    st.error("No se pudo leer snapshot.json: " + ("sin conexión con GitHub" if snap_code == -1 else f"HTTP {snap_code}") + ". Reintentando en el próximo refresco.")
    st.stop()
snap = as_dict(parse_json(snap_b, {}))
jobs = [j for j in as_list(snap.get("jobs")) if isinstance(j, dict) and j.get("job_id")]
if not jobs:
    st.info("Sin jobs sincronizados.")
    st.stop()
def _job_sort_key(j):
    # Most recently updated first; jobs without a timestamp go last.
    return -_parse_ts_or(j.get("updated"), 0.0)

def _parse_ts_or(iso, fallback):
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()
    except Exception:
        return fallback

def _job_waiting(j):
    # Waiting = the LATEST version is ready for Elvin and undecided (older superseded versions don't count).
    vs = [v for v in as_list(j.get("versions")) if isinstance(v, dict) and v.get("version")]
    if not vs:
        return False
    last = max(vs, key=lambda v: int(str(v["version"]).lstrip("vV") or -1) if str(v["version"]).lstrip("vV").isdigit() else -1)
    return last.get("veredicto_efectivo") in actionable_verdicts() and not last.get("decidido")

jobs = sorted(jobs, key=_job_sort_key)
ALL_JOBS = list(jobs)
ARCHIVED = {j["job_id"] for j in jobs if as_dict(gh_json(f"jobs/{j['job_id']}/archived.json", {})).get("archived") is True}
jobs = [j for j in jobs if j["job_id"] not in ARCHIVED] or jobs   # never end up with an empty dashboard
job_ids = [j["job_id"] for j in jobs]

if st.session_state.get("jid") not in job_ids:
    # Open a job that is waiting for Elvin; otherwise the most recently updated one.
    st.session_state.jid = next((j["job_id"] for j in jobs if _job_waiting(j)), job_ids[0])
jid = st.session_state.jid
job = next(j for j in jobs if j.get("job_id") == jid)

def _vnum(v):
    try:
        return int(str(v.get("version", "")).strip().lstrip("vV"))
    except Exception:
        return -1

versions = sorted([v for v in as_list(job.get("versions")) if isinstance(v, dict) and v.get("version")], key=_vnum)
version_ids = [v["version"] for v in versions]
cur = version_ids[-1] if version_ids else None
if st.session_state.sel_ver not in version_ids:
    st.session_state.sel_ver = cur
sel = st.session_state.sel_ver

state = as_dict(gh_json(f"jobs/{jid}/state.json", {}))
ms = as_dict(gh_json("progress/muse_status.json", {}))
budget = as_dict(gh_json("budget.json", {}))

# muse_status.json is global. If it names a job, only apply it to that job.
MS_JOB = ms.get("job_id") or ms.get("job")
MS_APPLIES = (not MS_JOB) or MS_JOB == jid

MUSE_ACTIVE = {"RECEIVED", "PLANNING", "WORKING", "WAITING_ON_TOOL", "VALIDATING",
               "SUPERVISOR_REVIEW", "CORRECTING", "BLOCKED"}

def muse_activity():
    """v10: Muse's real activity, from ITS OWN events. The old sync daemon renewed last_heartbeat and reset
    active states to IDLE ("IDLE: daemon reseteó..."), which hid a stopped Muse; those events are ignored here."""
    hist = [h for h in as_list(ms.get("history")) if isinstance(h, dict)]
    own = [h for h in hist if not str(h.get("event", "")).startswith("IDLE: daemon")]
    last = own[-1] if own else {}
    status = str(ms.get("status") or "")
    hb_min = hours_since(ms.get("last_heartbeat")) * 60
    interrupted = status == "IDLE" and str(ms.get("current_step") or "").startswith("daemon: sin heartbeat")
    return {"status": status, "interrupted": interrupted,
            "down": interrupted or (status in MUSE_ACTIVE and hb_min > MUSE_DOWN_MIN),
            "last_event": str(last.get("event") or ""), "own_age_h": hours_since(last.get("ts")),
            "task": ms.get("current_task")}

MUSE = muse_activity()

AGE = hours_since(state.get("updated"))
LIVE = AGE < .25
cur_info = next((v for v in versions if v["version"] == cur), {})

JOBS_BY_ID = {j["job_id"]: j for j in jobs}

def job_versions(job_id):
    """Sorted versions of any job from the snapshot."""
    j = JOBS_BY_ID.get(job_id) or {}
    return sorted([v for v in as_list(j.get("versions")) if isinstance(v, dict) and v.get("version")], key=_vnum)

def vinfo(vn, job_id=None):
    if job_id and job_id != jid:
        return next((v for v in job_versions(job_id) if v["version"] == vn), {})
    return next((v for v in versions if v["version"] == vn), {})

def vkey(vn, job_id=None):
    return f"{job_id or jid}|{vn}"

def vfiles(vn, job_id=None):
    if not vn:
        return {}
    return gh_dir(f"jobs/{job_id or jid}/versions/{vn}") or {}

def vjson(vn, name, job_id=None):
    return as_dict(parse_json(blob(vfiles(vn, job_id).get(name)), {}))

def verdict(vn, job_id=None): return vjson(vn, "verdict.json", job_id)
def meta(vn, job_id=None): return vjson(vn, "meta.json", job_id)

def asset_info(vn, job_id=None):
    files = vfiles(vn, job_id)
    for typ, ext in (("video", "mp4"), ("image", "png"), ("image", "jpg"), ("image", "jpeg")):
        f = files.get(f"asset.{ext}")
        if f:
            return typ, f
    return None, None

def show_asset(vn, job_id=None, preview=False):
    typ, info = asset_info(vn, job_id)
    data = (thumb(info) if preview and typ == "image" else None) or (blob(info, small=False) if info else None)
    if typ and data is None:
        st.warning("No se pudo descargar el asset. Reintentando en el próximo refresco.")
    elif typ == "image":
        st.image(data, width="stretch")
    elif typ == "video":
        st.video(data)
    else:
        st.info("Asset todavía no sincronizado.")

def decision_action(vn, job_id=None):
    if not vn:
        return None
    local = st.session_state.local_decided.get(vkey(vn, job_id))
    if local:
        return local
    d = vjson(vn, "decision_elvin.json", job_id)
    act = d.get("decision") or d.get("action")
    # Only protocol actions are decisions. Historical records such as
    # "chat_approval_sin_validez" must never render as approved.
    return act if act in DECISION_LABELS else None

def invalid_decision(vn, job_id=None):
    """Value of a decision_elvin.json that is NOT a protocol action (e.g. a chat approval), else None."""
    if not vn:
        return None
    d = vjson(vn, "decision_elvin.json", job_id)
    act = d.get("decision") or d.get("action")
    return act if act and act not in DECISION_LABELS else None

def is_decided(vn, job_id=None):
    if decision_action(vn, job_id):
        return True
    return bool(vinfo(vn, job_id).get("decidido")) and not invalid_decision(vn, job_id)

def _parse_ts(iso):
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()
    except Exception:
        return time.time()

def _tree(dir_path):
    """All files of a directory via the Git Trees API (no 1000-file limit of the contents API).
    Returns {name: {sha, path}}; {} if the directory does not exist; None on error."""
    parent, _, name = str(dir_path).rpartition("/")
    code, r = _get(parent, H_JSON)
    if code == 404:
        return {}
    if code != 200:
        return None
    try:
        entries = r.json()
    except ValueError:
        return None
    tree_sha = next((e.get("sha") for e in entries if isinstance(e, dict) and e.get("type") == "dir" and e.get("name") == name), None)
    if not tree_sha:
        return {}
    try:
        tr = requests.get(f"{GIT_API}/git/trees/{tree_sha}", headers=H_JSON, timeout=20)
    except requests.RequestException:
        return None
    if tr.status_code != 200:
        return None
    try:
        items = tr.json().get("tree", [])
    except ValueError:
        return None
    return {e["path"]: {"sha": e.get("sha"), "path": f"{dir_path}/{e['path']}"}
            for e in items if isinstance(e, dict) and e.get("type") == "blob" and e.get("path")}

@st.cache_data(ttl=20, show_spinner=False, max_entries=20)
def _gh_tree_legacy(dir_path):
    return _tree(dir_path)

def gh_tree(dir_path):
    idx = gh_index()
    if idx is None:
        return _gh_tree_legacy(dir_path)
    return {n: {"sha": e["sha"], "path": f"{dir_path}/{n}"} for n, e in idx["dirs"].get(str(dir_path), {}).items()}
gh_tree.clear = lambda: (_clear_all_listings(), _gh_tree_legacy.clear())

def _recent_ack_paths():
    """ACK files added in the last RECENT_ACK_WINDOW_H hours (via commits). None on error."""
    since = datetime.fromtimestamp(time.time() - RECENT_ACK_WINDOW_H * 3600, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        r = requests.get(f"{GIT_API}/commits", headers=H_JSON, timeout=20,
                         params={"sha": BRANCH, "path": "decisions/acks", "since": since, "per_page": RECENT_ACK_MAX_COMMITS})
        if r.status_code != 200:
            return None
        paths = []
        for c in r.json()[:RECENT_ACK_MAX_COMMITS]:
            d = requests.get(f"{GIT_API}/commits/{c['sha']}", headers=H_JSON, timeout=20)
            if d.status_code != 200:
                return None
            for f in d.json().get("files", []):
                fn = f.get("filename", "")
                if fn.startswith("decisions/acks/") and fn.endswith(".json") and f.get("status") != "removed" and fn not in paths:
                    paths.append(fn)
        return paths
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return None

def inbox_decision_for(vn, *, fresh=False, job_id=None):
    """Find a decision for jid/vn that is still pending (inbox file without ACK), from any
    session/device. The backend never deletes inbox files, so pending = inbox ids − ack ids;
    only those few files are read. Returns (record|None, ok).
    With fresh=True also checks ACKs accepted in the last hours, covering the window
    before decision_elvin.json is synced."""
    J = job_id or jid
    inbox = _tree("decisions/inbox") if fresh else gh_tree("decisions/inbox")
    acks = _tree("decisions/acks") if fresh else gh_tree("decisions/acks")
    if inbox is None or acks is None:
        return None, False
    for name in sorted(set(inbox) - set(acks)):
        if not name.endswith(".json"):
            continue
        d = as_dict(parse_json(blob(inbox[name]), {}))
        if d.get("job_id") != J or d.get("version") != vn or d.get("action") not in DECISION_LABELS:
            continue   # publish/v1 messages are not content decisions
        return {"decision_id": d.get("decision_id") or name[:-5], "job_id": J, "version": vn,
                "action": d.get("action"), "sent_at": _parse_ts(d.get("timestamp")), "ack_status": ""}, True
    if fresh:
        recent = _recent_ack_paths()
        if recent is None:
            return None, False
        for path in recent:
            a = as_dict(gh_json(path, {}, fresh=True))
            if (a.get("job_id") == J and a.get("version") == vn and a.get("action") in DECISION_LABELS
                    and str(a.get("status", "")).lower() in ACK_OK):
                return {"decision_id": a.get("decision_id") or path.rsplit("/", 1)[-1][:-5], "job_id": J,
                        "version": vn, "action": a.get("action"), "sent_at": time.time(), "ack_status": "accepted"}, True
    return None, True

def sync_health():
    """Real backend health from the bus. Returns dict or None if GitHub could not be read.
    pending = inbox decisions with neither an ACK file nor an applied.json entry."""
    inbox, acks = gh_tree("decisions/inbox"), gh_tree("decisions/acks")
    if inbox is None or acks is None:
        return None
    applied = as_dict(gh_json("decisions/applied.json", {}))
    ack_ids = {n[:-5] for n in acks if n.endswith(".json")}
    pending = []
    for name in sorted(inbox):
        if not name.endswith(".json"):
            continue
        did = name[:-5]
        if did in ack_ids or did in applied:
            continue
        d = as_dict(parse_json(blob(inbox[name]), {}))
        pending.append({"decision_id": d.get("decision_id") or did, "job_id": d.get("job_id"),
                        "version": d.get("version"), "action": d.get("action"),
                        "ts": _parse_ts(d.get("timestamp"))})
    pending.sort(key=lambda p: p["ts"])
    seen, dups = set(), 0
    for p in pending:
        key = (p["job_id"], p["version"], p["action"])
        dups += key in seen
        seen.add(key)
    return {"pending": pending, "duplicates": dups,
            "oldest_age_s": (time.time() - pending[0]["ts"]) if pending else 0.0,
            "heartbeat_h": hours_since(ms.get("last_heartbeat"))}

# ── Decision reconciliation ──
# 1) Recover in-flight decisions written from another session/device or before a reload.
for v in versions:
    vn = v["version"]
    k = vkey(vn)
    if v.get("veredicto_efectivo") in actionable_verdicts() and not is_decided(vn) and k not in st.session_state.inflight:
        rec, _ = inbox_decision_for(vn)
        if rec:
            st.session_state.inflight[k] = rec

# 2) Poll the exact ACK (uncached) for every in-flight decision (any job: the Agenda decides across jobs).
for k, p in list(st.session_state.inflight.items()):
    ack = as_dict(gh_json(f"decisions/acks/{p['decision_id']}.json", {}, fresh=True))
    status = str(ack.get("status", "")).lower()
    if status in ACK_OK:
        st.session_state.local_decided[k] = p.get("action")
        del st.session_state.inflight[k]
        set_notice(f"{ACTION_NAMES.get(p.get('action'), p.get('action'))} ({p.get('version')}) confirmado por el backend.", "success")
        clear_bus_cache()
    elif status in ACK_FAIL:
        del st.session_state.inflight[k]
        set_notice(f"Decisión rechazada por backend: {ack.get('reason') or 'sin motivo'}", "error")
        clear_bus_cache()
    else:
        p["ack_status"] = status

def inflight_for(vn, job_id=None):
    return st.session_state.inflight.get(vkey(vn, job_id))

def is_reviewable(vn, job_id=None):
    return (vinfo(vn, job_id).get("veredicto_efectivo") in actionable_verdicts()
            and not is_decided(vn, job_id) and not inflight_for(vn, job_id))

def is_superseded(vn, job_id=None):
    """A READY version is stale when a later version of the same job is already READY or approved."""
    vs = [v["version"] for v in job_versions(job_id or jid)]
    if vn not in vs:
        return False
    for later in vs[vs.index(vn) + 1:]:
        if decision_action(later, job_id) == "approve_final" or vinfo(later, job_id).get("veredicto_efectivo") in actionable_verdicts():
            return True
    return False

def pending_reviews():
    """[(job_id, vn)] Elvin must approve/reject: READY, undecided, not superseded by a later version."""
    out = []
    for j in jobs:
        for v in job_versions(j["job_id"]):
            if is_reviewable(v["version"], j["job_id"]) and not is_superseded(v["version"], j["job_id"]):
                out.append((j["job_id"], v["version"]))
    return out

CUR_PEND = is_reviewable(cur)
CUR_INFLIGHT = bool(inflight_for(cur))
CUR_DECISION = decision_action(cur)
JOB_HAS_INFLIGHT = bool(st.session_state.inflight)

def live_state():
    s = state.get("state", "")
    mst = ms.get("status", "") if MS_APPLIES else ""
    if CUR_INFLIGHT:
        return "Decision sent"
    if CUR_PEND:
        return "Waiting for Elvin"
    if LIVE and s == "GENERATING":
        return "Generating"
    if s in ("PUBLISHED", "DONE"):
        return "Published"
    if LIVE and mst in ("VALIDATING", "CORRECTING"):
        return "Muse QC"
    if LIVE and (mst == "SUPERVISOR_REVIEW" or s == "REVIEWING"):
        return "Supervisor reviewing"
    # The Elvin decision record is more authoritative than stale state/muse_status files.
    if CUR_DECISION == "approve_final":
        return "Approved by Elvin"
    if CUR_DECISION == "request_changes":
        return "Changes requested"
    if CUR_DECISION == "reject":
        return "Rejected by Elvin"
    if (s == "ELVIN_DECISION_REQUIRED" or mst == "BLOCKED_ON_ELVIN") and not is_decided(cur):
        return "Waiting for Elvin"
    if not LIVE:
        return "Idle"
    if mst == "WORKING":
        return "Working"
    if mst == "WAITING_ON_TOOL":
        return f"Waiting: {ms.get('waiting_on') or 'tool'}"
    return "Idle"

LIVE_LBL = live_state()
MSTEP = (ms.get("current_step") or "") if MS_APPLIES else ""


# ───────────────────────── header / nav ─────────────────────────
st.markdown(
    f"<div class='kv-top'><div class='kv-logo'><span>◆ KAIA VALE</span></div><div class='kv-job desktop-only'>{esc(jid)}</div>"
    f"<div class='kv-live'><span class='dot{'' if LIVE else ' off'}'></span><b style='color:white'>{esc(LIVE_LBL)}</b>"
    f"<span class='desktop-only'>· QA ${num(budget.get('monthly_used_usd')):.2f}</span></div></div>",
    unsafe_allow_html=True)
NAV_SLOT = st.container(key="kv_nav")   # filled by render_nav() once every renderer is defined


# ───────────────────────── sync health (real bus data) ─────────────────────────
HEALTH = sync_health()
if HEALTH is None:
    st.markdown("<div class='review warn'><b>Sync</b> · no se pudo leer el inbox/ACK en GitHub. Reintentando.</div>", unsafe_allow_html=True)
else:
    stale_pending = [p for p in HEALTH["pending"] if time.time() - p["ts"] > ACK_TIMEOUT_S]
    if stale_pending:
        items = ", ".join(f"{p['job_id']} {p['version']} ({p['action']})" for p in stale_pending[:4])
        st.markdown(
            f"<div class='review red'><b>Backend detenido</b> · {len(stale_pending)} decisión(es) sin procesar desde hace "
            f"{esc(human_age(HEALTH['oldest_age_s'] / 3600))}</div>", unsafe_allow_html=True)
    _dh = as_dict(gh_json("progress/daemon_health.json", {}))
    if _dh.get("cycle_ended"):
        _age = time.time() - _parse_ts_or(_dh.get("cycle_ended"), time.time())
        if _age > DAEMON_DOWN_S:
            st.markdown(f"<div class='review red'><b>Backend apagado</b> · sin ciclo hace {esc(human_age(_age / 3600))}</div>", unsafe_allow_html=True)
    if MUSE["down"] and st.session_state.tab != "Hoy":
        st.markdown(f"<div class='review red'><b>Muse parado</b> · hace {esc(human_age(MUSE['own_age_h']))}</div>", unsafe_allow_html=True)


# ───────────────────────── Muse yes/no blocker ─────────────────────────
ms_blocked = ms.get("status") == "BLOCKED_ON_ELVIN"
q = str(ms.get("needs_decision") or "").strip()
QID = str(ms.get("question_id") or "")
q_key = f"{q}|{QID}"
# An asset approval (or publish authorization) is only valid as a job/version decision.
# A free-form yes/no is not bound to an asset, version, supervisor verdict or sha.
q_is_asset_approval = bool(ms.get("asset")) or bool(ASSET_APPROVAL_RE.search(q))
if not ms_blocked:
    st.session_state.answered_q = None
if ms_blocked and q and q_is_asset_approval:
    st.markdown(
        f"<div class='review red'><b>Muse pide aprobar por pregunta libre</b> · apruébalo en la pieza, no aquí. {esc(q[:200])}</div>",
        unsafe_allow_html=True)
elif ms_blocked and q and st.session_state.answered_q != q_key:
    if MS_JOB and MS_JOB != jid:
        st.caption(f"Pregunta de Muse sobre el job {MS_JOB}")
    st.warning(q)
    y, n = st.columns(2)

    def _send_answer(answer):
        ok, d = gh_put_json("progress/elvin_answer.json", {"question": q, "question_id": QID or None,
                                                           "answer": answer, "timestamp": now_iso()},
                            f"elvin answer: {answer}")
        if ok:
            st.session_state.answered_q = q_key
            gh_fetch.clear()
            st.rerun()
        else:
            st.error(d)

    if y.button("SÍ, CONTINÚA", key="muse_yes", type="primary", width="stretch"):
        _send_answer("yes")
    if n.button("NO", key="muse_no", width="stretch"):
        _send_answer("no")
elif ms_blocked and q:
    st.info("Respuesta enviada · esperando que Muse la consuma…")


# ───────────────────────── decisions ─────────────────────────
def send_decision(action, note="", job_id=None, vn=None):
    J, V = job_id or jid, vn or sel
    k = vkey(V, J)
    if inflight_for(V, J):
        st.info("Ya hay una decisión esperando confirmación del backend.")
        return
    if is_decided(V, J) or not is_reviewable(V, J):
        st.warning("Esta versión ya no está disponible para decisión.")
        return
    # Fresh (uncached) checks against the bus before writing anything.
    fresh_files = _dir(f"jobs/{J}/versions/{V}")
    if fresh_files is None:
        st.error("No se pudo verificar el estado de la versión en GitHub. Reintenta.")
        return
    if "decision_elvin.json" in fresh_files:
        clear_bus_cache()
        st.warning("Esta versión ya tiene una decisión de Elvin registrada.")
        st.rerun()
    # Bind the decision to the exact asset blob Elvin is looking at.
    shown_typ, shown = asset_info(V, J)
    fresh_asset = next((fresh_files.get(f"asset.{e}") for e in ("mp4", "png", "jpg", "jpeg") if fresh_files.get(f"asset.{e}")), None)
    if not shown or not fresh_asset:
        st.error("Esta versión no tiene asset sincronizado; no se puede decidir sobre ella.")
        return
    if shown.get("sha") != fresh_asset.get("sha"):
        clear_bus_cache()
        st.warning("El asset de esta versión cambió desde que lo abriste. Revísalo de nuevo antes de decidir.")
        st.rerun()
    rec, ok = inbox_decision_for(V, fresh=True, job_id=J)
    if not ok:
        st.error("No se pudo verificar el inbox de decisiones en GitHub. Reintenta.")
        return
    if rec:
        st.session_state.inflight[k] = rec
        set_notice("Ya existe una decisión para esta versión en el inbox · esperando ACK del backend…")
        st.rerun()
    asset_file = fresh_asset.get("path", "").rsplit("/", 1)[-1]
    # The backend verifies asset_sha as SHA-256 of the asset bytes (not the git blob sha).
    try:
        asset_bytes = gh_blob(fresh_asset["path"], fresh_asset["sha"])
    except Exception:
        st.error("No se pudo descargar el asset para verificarlo. Reintenta.")
        return
    asset_sha256 = hashlib.sha256(asset_bytes).hexdigest()
    # Deterministic id: the same job/version/asset/action always maps to the same inbox file,
    # so a double tap or a stale API read hits "already exists" instead of creating a duplicate.
    did = str(uuid.uuid5(DECISION_NS, f"{J}|{V}|{fresh_asset.get('sha')}|{action}"))
    # v10: if the backend already REJECTED this exact decision (e.g. the version was not decidable yet),
    # a resend needs a new id; before, the same id hit "already exists" forever.
    for n in range(1, 21):
        prev = as_dict(gh_json(f"decisions/acks/{did}.json", {}, fresh=True))
        if str(prev.get("status", "")).lower() not in ACK_FAIL:
            break
        did = str(uuid.uuid5(DECISION_NS, f"{J}|{V}|{fresh_asset.get('sha')}|{action}|retry{n}"))
    obj = {"decision_id": did, "job_id": J, "version": V, "action": action, "timestamp": now_iso(),
           "note": note.strip(), "asset_file": asset_file, "asset_sha": asset_sha256,
           "asset_git_sha": fresh_asset.get("sha")}
    ok, d = gh_put_json(f"decisions/inbox/{did}.json", obj, f"decision {action} {J} {V}", create_only=True)
    already = not ok and d.startswith("HTTP 422")
    if already:
        # Already written (by this or another session): treat as sent, never write a second one.
        ok = True
    if ok:
        st.session_state.inflight[k] = {"decision_id": did, "job_id": J, "version": V, "action": action,
                                        "sent_at": time.time(), "ack_status": ""}
        if already:
            set_notice("Esta decisión ya estaba enviada · esperando ACK del backend…")
        else:
            st.session_state.notice = None   # the decision block already shows "Decisión enviada"
        st.session_state.change_open = False
        gh_dir.clear(); gh_tree.clear()
        if st.session_state.tab == "Studio":
            # The decided piece leaves the queue: open the next one waiting for Elvin, or say there is none.
            try:
                nxt = next(((j_, v_) for j_, _p, v_ in needs_elvin()[0] if (j_, v_) != (J, V)), None)
            except Exception:
                nxt = None
            if nxt:
                st.session_state.jid, st.session_state.sel_ver = nxt
                st.session_state.compare = False
                st.session_state.focus = False
                set_notice(f"Decisión enviada · siguiente por aprobar: {nxt[0]} {nxt[1]}.", "success")
            else:
                set_notice("Decisión enviada · no hay más piezas por aprobar.", "success")
        st.rerun()
    else:
        st.error(f"No se pudo enviar: {d}")

def stage_data():
    """Returns ([(name, done)], active_idx|None, stopped_idx|None)."""
    s = state.get("state", "")
    has = bool(versions)
    generating = LIVE and s == "GENERATING"
    v = sel or cur   # the pipeline describes the version on screen, not always the latest
    vd = verdict(v) if v else {}
    ve = vinfo(v).get("veredicto_efectivo", "") if v else ""
    dec = decision_action(v) if v else None
    pend = bool(v) and (is_reviewable(v) or bool(inflight_for(v)))
    published = s in ("PUBLISHED", "DONE")
    stages = [("Brief", has or s == "GENERATING"),
              ("Generate", has and not generating),
              ("Muse QC", bool(vd)),
              ("Supervisor", ve in ("CORREGIR", "ESCALAR", "ELVIN_DECISION_REQUIRED", "READY_FOR_ELVIN_REVIEW", "APROBADO") or dec == "approve_final"),
              ("Elvin", is_decided(v) if v else False),
              ("Publish", published)]
    if published:
        return [(n, True) for n, _ in stages], None, None
    if generating:
        return stages, 1, None
    if pend:
        return stages, 4, None
    if dec in ("reject", "request_changes"):
        return stages, None, 4
    if dec == "approve_final":
        return stages, 5, None
    if s == "ESCALATED_INTERNAL" or ve in ("CORREGIR", "ESCALAR"):
        # No espera a Elvin: el supervisor la detuvo y Muse/Elvin deben resolverlo antes.
        return stages, None, 3
    return stages, next((i for i, (_, d) in enumerate(stages) if not d), None), None

def normalize_findings(vd):
    raw = vd.get("hallazgos") or vd.get("blocking_issues") or vd.get("motivo_principal") or []
    if not isinstance(raw, list):
        raw = [raw]
    out = []
    for f in raw:
        txt = (f.get("titulo") or f.get("descripcion") or f.get("categoria") or json.dumps(f, ensure_ascii=False)) if isinstance(f, dict) else str(f)
        if txt.strip():
            out.append(txt.strip())
    return out

def _is_fail(estado):
    e = str(estado or "").strip().upper()
    return e.startswith("FAIL") or e.startswith("FALLA")

# Supervisor visual_coverage groups (Spanish keys, current bus) -> inspector rows.
# Each row: (label, [(group, subkey|None = whole group, exclude subkeys)]).
QC_ROWS = (
    ("Identity", [("identidad", None, ())]),
    ("Anatomy", [("anatomia", None, ("manos_dedos",)), ("continuidad_corporal", None, ())]),
    ("Skin", [("piel", None, ())]),
    ("Hands", [("anatomia", "manos_dedos", ())]),
    ("Clothing", [("ropa", None, ())]),
    ("Scene", [("escena", None, ())]),
)
QC_NOT_EVALUATED = {"NOT_VISIBLE", "NOT_APPLICABLE", "NO_VISIBLE", "NO_APLICA", ""}

def _qc_from_coverage(cov):
    """{label: (True|False|None, detail|None)} from visual_coverage; {} if absent."""
    out = {}
    for label, sources in QC_ROWS:
        items = []
        for group, sub, exclude in sources:
            g = cov.get(group)
            if not isinstance(g, dict):
                continue
            if sub:
                if isinstance(g.get(sub), dict):
                    items.append((sub, g[sub]))
            else:
                items += [(k, v) for k, v in g.items() if k not in exclude and isinstance(v, dict)]
        evaluated = [(k, v) for k, v in items if str(v.get("estado", "")).upper() not in QC_NOT_EVALUATED]
        if not evaluated:
            out[label] = (None, None)
            continue
        fails = [(k, v) for k, v in evaluated if _is_fail(v.get("estado"))]
        detail = "; ".join(f"{k.replace('_', ' ')}: {str(v.get('evidencia') or '').strip()}" for k, v in fails) or None
        out[label] = (not fails, detail)
    return out

def qc_status(vd):
    """{cat: (True ok | False fail | None sin veredicto, detalle|None)}.
    Current verdicts: visual_coverage with Spanish groups (identidad, anatomia, piel, ropa,
    escena, continuidad_corporal). Legacy verdicts: English keys / *_review dicts."""
    cov = as_dict(vd.get("visual_coverage"))
    if any(k in cov for k in ("identidad", "anatomia", "piel", "ropa", "escena")):
        out = _qc_from_coverage(cov)
        tv = as_dict(vd.get("technical_validation"))
        if tv.get("estado"):
            d = as_dict(tv.get("detalle")).get("resumen") if isinstance(tv.get("detalle"), dict) else tv.get("detalle")
            out["Technical"] = (not _is_fail(tv.get("estado")), str(d).strip() if _is_fail(tv.get("estado")) and d else None)
        return out
    anatomy = vd.get("anatomy_review")
    rich = {"identity": vd.get("identity_review"), "anatomy": anatomy, "skin": vd.get("skin_review")}
    out = {}
    for cat in ("identity", "anatomy", "skin", "hands"):
        cv, rv = cov.get(cat), rich.get(cat)
        # Only a real pass/fail field counts as a verdict; free-text reviews are not a ✓.
        has_data = isinstance(cv, dict) or (isinstance(rv, dict) and rv.get("estado") not in (None, ""))
        fail = False
        if isinstance(cv, dict):
            fail = any(isinstance(x, dict) and _is_fail(x.get("estado")) for x in cv.values())
        if isinstance(rv, dict) and _is_fail(rv.get("estado")):
            fail = True
        detail = None
        if cat == "hands" and isinstance(anatomy, dict):
            m = anatomy.get("manos")
            detail = str(m).strip() if m not in (None, "") else None
        out[cat] = (None if not has_data else (not fail), detail)
    return out

def render_notice():
    n = st.session_state.notice
    if not n:
        return
    if time.time() - n.get("ts", 0) > NOTICE_TTL_S:
        st.session_state.notice = None
        return
    {"success": st.success, "error": st.error}.get(n.get("level"), st.caption)(n.get("text", ""))

PILLS_KW = {"required": True} if "required" in inspect.signature(st.pills).parameters else {}


def status_badge(vn, job_id=None):
    """(label, tone) — readable status for a version."""
    act = decision_action(vn, job_id)
    if inflight_for(vn, job_id):
        return "Decision sent", "violet"
    if act:
        return DECISION_LABELS.get(act, "Decided by Elvin"), DECISION_TONE.get(act, "green")
    if invalid_decision(vn, job_id):
        return "Chat approval · not valid", "amber"
    ve = vinfo(vn, job_id).get("veredicto_efectivo") or ""
    if ve in VERDICT_LABELS:
        return VERDICT_LABELS[ve]
    return (ve.replace("_", " ").capitalize() if ve else "—"), ""

def is_suggestive(vn, job_id=None):
    """Supervisor tag (verdict.json etiquetas: ["sugerente"]): allowed content Elvin should judge himself."""
    return "sugerente" in [str(x).lower() for x in as_list(verdict(vn, job_id).get("etiquetas"))]

def badge_html(vn, job_id=None):
    label, tone = status_badge(vn, job_id)
    extra = "<span class='badge amber'>🌶 Sugerente</span>" if is_suggestive(vn, job_id) else ""
    return f"<span class='badge {tone}'>{esc(label)}</span>{extra}"

def pipeline_items_html():
    stages, active_idx, stopped_idx = stage_data()
    out = []
    for i, (name, done) in enumerate(stages):
        if i == stopped_idx:
            cls, sym = "stopped", DECISION_ICONS.get(decision_action(sel or cur), "✕")
        elif i == active_idx:
            cls, sym = "active", str(i + 1)
        elif done and (active_idx is None or i < active_idx) and (stopped_idx is None or i < stopped_idx):
            cls, sym = "done", "✓"
        else:
            cls, sym = "pending", str(i + 1)
        out.append(f"<div class='pipe-item {cls}'><span class='pi'>{esc(sym)}</span><b>{esc(name)}</b></div>")
    return "".join(out)

def inspector_html(vn, *, with_header=True, with_specs=True):
    vd = verdict(vn)
    mt = meta(vn)
    parts = []
    if with_header:
        parts.append(f"<div class='ins'><div class='ins-head'><b>{esc(vn)}</b>{badge_html(vn)}</div></div>")
    qc_rows = []
    for cat, (ok, detail) in qc_status(vd).items():
        if ok is None and detail:
            cls, sym = "na", "nota"
        else:
            cls, sym = ("na", "—") if ok is None else (("ok", "✓") if ok else ("bad", "✕"))
        qc_rows.append(f"<div class='qc'><b>{esc(cat.title())}</b><span class='{cls}'>{sym}</span></div>")
        if detail:
            qc_rows.append(f"<div class='find'>{esc(detail[:220])}</div>")
    qc_note = "" if vd else "<div class='small'>QC todavía no disponible.</div>"
    parts.append(f"<div class='ins'><div class='ins-title'>QC</div>{''.join(qc_rows)}{qc_note}</div>")
    findings = normalize_findings(vd)
    if findings:
        rows = "".join(f"<div class='find'>• {esc(t[:180])}</div>" for t in findings[:5])
        parts.append(f"<div class='ins'><div class='ins-title'>Findings</div>{rows}</div>")
    if not with_specs:
        return "".join(parts)
    prm = as_dict(mt.get("params"))
    parts.append("<div class='ins'><div class='ins-title'>Specs</div><div class='spec'>"
                 f"<div>Model<b>{esc(prm.get('model', '—'))}</b></div><div>Ratio<b>{esc(prm.get('ratio', '—'))}</b></div>"
                 f"<div>Duration<b>{esc(prm.get('duration', '—'))}</b></div><div>Registered<b>{esc(human_age(hours_since(mt.get('registered'))))}</b></div>"
                 "</div></div>")
    return "".join(parts)

def render_decision_block():
    inflight = inflight_for(sel)
    if inflight:
        age = time.time() - num(inflight.get("sent_at"), time.time())
        act = ACTION_NAMES.get(inflight.get("action"), inflight.get("action"))
        extra = f" · ACK: {esc(inflight.get('ack_status'))}" if inflight.get("ack_status") else ""
        if age > ACK_TIMEOUT_S:
            st.warning(f"{act} enviado hace {int(age // 60)} min y el backend no responde.")
        else:
            st.caption(f"{act} enviado · esperando confirmación…")
    elif is_decided(sel):
        act = decision_action(sel)
        st.markdown(f"<div class='review {DECISION_TONE.get(act, 'green')}'><b>{esc(DECISION_ICONS.get(act, '✓'))} {esc(DECISION_LABELS.get(act, 'Decided by Elvin'))}</b></div>", unsafe_allow_html=True)
    elif is_reviewable(sel):
        with st.container(key="kv_decide"):
            r1, r2, r3 = st.columns([1, 1.15, 1.35])
            if r1.button("✕ Reject", key="dec_reject", width="stretch"):
                send_decision("reject")
            if r2.button("↻ Changes", key="dec_changes", width="stretch", help="Request changes"):
                st.session_state.change_open = not st.session_state.change_open
                st.rerun()
            if r3.button("✓ Approve", key="dec_approve", type="primary", width="stretch"):
                send_decision("approve_final")
        if st.session_state.change_open:
            with st.form("changes_form"):
                note = st.text_area("Cambios solicitados", placeholder="Describe exactamente qué debe corregirse…")
                if st.form_submit_button("Enviar cambios", type="primary", width="stretch"):
                    if note.strip():
                        send_decision("request_changes", note)
                    else:
                        st.error("Escribe los cambios.")
    else:
        ve = vinfo(sel).get("veredicto_efectivo") or "sin veredicto"
        st.caption(f"Sin decisión disponible · {VERDICT_LABELS.get(ve, (ve, ''))[0]}")


# ───────────────────────── publish/v1 (protocol/PUBLISH_PROTOCOL.md) ─────────────────────────
PUB_STATUS = {"authorized": ("Autorizada", "violet"), "executing": ("Publicando…", "violet"),
              "executed": ("Publicada", "green"), "failed": ("Falló", "red"),
              "revoked": ("Revocada", "amber"), "expired": ("Vencida", "amber"),
              "needs_check": ("Comprueba si salió", "red")}
PUB_ACTIVE = {"authorized", "executing"}
OP_LABELS = {"feed_post": "Post en feed", "reel": "Reel", "story": "Story", "carousel": "Carrusel",
             "video": "Video", "post": "Post"}
try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("America/Los_Angeles")
except Exception:   # tzdata missing: fall back to UTC (shown explicitly in the UI)
    LOCAL_TZ = timezone.utc

def publish_caps():
    caps = as_dict(gh_json("protocol/capabilities.json", {}))
    targets = as_dict(gh_json("protocol/schemas/targets.json", {}))
    ok = caps.get("publish_v1") is True and targets.get("schema") == "publish/v1" and bool(targets.get("platforms"))
    return ok, caps, targets

def publish_records(vn, job_id=None):
    files = gh_dir(f"jobs/{job_id or jid}/versions/{vn}/publish") or {}
    recs = [as_dict(parse_json(blob(info), {})) for name, info in sorted(files.items()) if name.endswith(".json")]
    return [r for r in recs if r.get("authorization_id")]

def publish_pending(vn, *, fresh=False, job_id=None):
    """publish/v1 inbox messages for job/vn without ACK. Returns (list, ok)."""
    job_id = job_id or jid
    inbox = _tree("decisions/inbox") if fresh else gh_tree("decisions/inbox")
    acks = _tree("decisions/acks") if fresh else gh_tree("decisions/acks")
    if inbox is None or acks is None:
        return [], False
    out = []
    for name in sorted(set(inbox) - set(acks)):
        d = as_dict(parse_json(blob(inbox[name]), {}))
        if d.get("job_id") == job_id and d.get("version") == vn and d.get("action") in ("authorize_publish", "revoke_publish"):
            out.append(d)
    return out, True

def _to_utc_iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def send_publish_authorization(targets, platform, operation, caption, scheduled_local, job_id=None, vn=None):
    """Fresh checks against the bus, then a create-only authorize_publish in the inbox."""
    _J, _V = job_id or jid, vn or sel
    fresh_files = _dir(f"jobs/{_J}/versions/{_V}")
    if fresh_files is None:
        st.error("No se pudo verificar la versión en GitHub. Reintenta.")
        return
    appr = as_dict(parse_json(_fetch(f"jobs/{_J}/versions/{_V}/decision_elvin.json")[1], {}))
    if appr.get("decision") != "approve_final":
        st.error("Esta versión no tiene approve_final: primero aprueba el contenido.")
        return
    fresh_asset = next((fresh_files.get(f"asset.{e}") for e in ("mp4", "png", "jpg", "jpeg") if fresh_files.get(f"asset.{e}")), None)
    _, shown = asset_info(_V, _J)
    if not fresh_asset or not shown or shown.get("sha") != fresh_asset.get("sha"):
        clear_bus_cache()
        st.warning("El asset cambió o no está sincronizado. Revísalo de nuevo antes de autorizar.")
        st.rerun()
    try:
        data = gh_blob(fresh_asset["path"], fresh_asset["sha"])
    except Exception:
        st.error("No se pudo descargar el asset para verificarlo. Reintenta.")
        return
    asset_sha = hashlib.sha256(data).hexdigest()
    if appr.get("asset_sha") and str(appr["asset_sha"]).lower() != asset_sha:
        st.error("El asset actual no es el que aprobaste. No se puede autorizar.")
        return
    account = targets["platforms"][platform]["account"]
    pend, ok = publish_pending(_V, fresh=True, job_id=_J)
    if not ok:
        st.error("No se pudo verificar el inbox en GitHub. Reintenta.")
        return
    for d in pend:
        if d.get("action") == "authorize_publish" and d.get("platform") == platform and d.get("operation") == operation:
            st.info("Ya hay una autorización enviada para ese destino · esperando al backend.")
            return
    for r in publish_records(_V, _J):
        if r.get("status") in PUB_ACTIVE and r.get("platform") == platform and r.get("operation") == operation:
            st.warning("Ya existe una autorización activa para ese destino. Revócala antes de reprogramar.")
            return
    now = datetime.now(timezone.utc)
    sched_iso = _to_utc_iso(scheduled_local) if scheduled_local else None
    if scheduled_local and scheduled_local.astimezone(timezone.utc) < now:
        st.error("El horario elegido ya pasó.")
        return
    base_dt = scheduled_local.astimezone(timezone.utc) if scheduled_local else now
    ttl_h = int(num(targets.get("default_ttl_hours"), 24)) or 24
    expires_iso = _to_utc_iso(datetime.fromtimestamp(base_dt.timestamp() + ttl_h * 3600, timezone.utc))
    ns = uuid.UUID(targets["ns_publish"])
    cap_sha = hashlib.sha256(caption.encode("utf-8")).hexdigest()
    did = str(uuid.uuid5(ns, f"{_J}|{_V}|{asset_sha}|{platform}|{account}|{operation}|{sched_iso}|{cap_sha}"))
    obj = {"schema": "publish/v1", "decision_id": did, "action": "authorize_publish", "job_id": _J, "version": _V,
           "timestamp": now_iso(), "note": "", "asset_file": fresh_asset["path"].rsplit("/", 1)[-1],
           "asset_sha": asset_sha, "asset_git_sha": fresh_asset["sha"], "platform": platform, "account": account,
           "operation": operation, "caption": caption, "scheduled_at": sched_iso, "expires_at": expires_iso}
    ok, d = gh_put_json(f"decisions/inbox/{did}.json", obj, f"authorize_publish {_J} {_V} {platform}/{operation}", create_only=True)
    if ok or d.startswith("HTTP 422"):
        set_notice("Autorización de publicación enviada · esperando confirmación del backend.", "success")
        gh_dir.clear(); gh_tree.clear()
        st.rerun()
    else:
        st.error(f"No se pudo enviar: {d}")

def send_publish_revoke(auth_id, note="", job_id=None, vn=None):
    job_id = job_id or jid
    vn = vn or sel
    pend, ok = publish_pending(vn, fresh=True, job_id=job_id)
    if not ok:
        st.error("No se pudo verificar el inbox en GitHub. Reintenta.")
        return
    if any(d.get("action") == "revoke_publish" and d.get("target_authorization_id") == auth_id for d in pend):
        st.info("La revocación ya fue enviada.")
        return
    _, _, targets = publish_caps()
    did = str(uuid.uuid5(uuid.UUID(targets["ns_publish"]), f"revoke|{auth_id}"))
    obj = {"schema": "publish/v1", "decision_id": did, "action": "revoke_publish", "job_id": job_id, "version": vn,
           "target_authorization_id": auth_id, "timestamp": now_iso(), "note": note}
    ok, d = gh_put_json(f"decisions/inbox/{did}.json", obj, f"revoke_publish {job_id} {vn}", create_only=True)
    if ok or d.startswith("HTTP 422"):
        set_notice("Revocación enviada · esperando confirmación del backend.", "success")
        gh_dir.clear(); gh_tree.clear()
        st.rerun()
    else:
        st.error(f"No se pudo enviar: {d}")

def _fmt_local(iso):
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return dt.astimezone(LOCAL_TZ).strftime("%d %b %H:%M") + (" PT" if LOCAL_TZ is not timezone.utc else " UTC")
    except Exception:
        return "inmediata"

def _fmt_es(dt):
    """'Mié 14 oct · 18:00 PT' for an aware datetime (converted to local)."""
    dt = dt.astimezone(LOCAL_TZ)
    return f"{day_label(dt.date())} · {dt.strftime('%H:%M')} {'PT' if LOCAL_TZ is not timezone.utc else 'UTC'}"

def _fmt_es_iso(iso):
    try:
        return _fmt_es(datetime.fromisoformat(str(iso).replace("Z", "+00:00")))
    except Exception:
        return "inmediata (al autorizar)"

def _proposal_when(proposal, plan):
    """Local datetime proposed for publishing (publish_proposal.scheduled_for, else plan date+slot); None if absent/past."""
    raw = proposal.get("scheduled_for") or (f"{plan.get('planned_for')}T{plan.get('slot')}" if plan.get("planned_for") and plan.get("slot") else "")
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    dt = dt.astimezone(LOCAL_TZ) if dt.tzinfo else dt.replace(tzinfo=LOCAL_TZ)
    return dt if dt > datetime.now(LOCAL_TZ) else None

def _apply_publish_defaults(targets, proposal):
    """Prefill platform/format/caption/time from Muse's proposal, else the plan.
    Re-applied whenever Streamlit dropped the widget state (e.g. after visiting another tab),
    so the form never silently falls back to the first format / "Ahora"."""
    ctx = f"{jid}|{sel}"
    if st.session_state.get("pub_ctx") != ctx:
        for k in ("pub_platform", "pub_operation", "pub_caption", "pub_when", "pub_day", "pub_time", "pub_confirm"):
            st.session_state.pop(k, None)
        st.session_state.pub_ctx = ctx
    plan = job_plan(jid)
    plats = targets.get("platforms") or {}
    platform = proposal.get("platform") or plan.get("platform")
    if platform in plats and "pub_platform" not in st.session_state:
        st.session_state.pub_platform = platform
    operation = proposal.get("operation") or plan.get("operation")
    cur_plat = st.session_state.get("pub_platform", platform)
    if cur_plat in plats and operation in plats[cur_plat].get("operations", []) and "pub_operation" not in st.session_state:
        st.session_state.pub_operation = operation
    if "pub_caption" not in st.session_state:
        st.session_state.pub_caption = str(proposal.get("caption") or plan.get("caption_draft") or "")
    when = _proposal_when(proposal, plan)
    if when and "pub_when" not in st.session_state:
        st.session_state.pub_when = "Programar"
        st.session_state.pub_day = when.date()
        st.session_state.pub_time = when.time().replace(second=0, microsecond=0, tzinfo=None)

def render_publish_block():
    """Only for versions with a valid approve_final. Hidden behind capabilities.publish_v1."""
    if decision_action(sel) != "approve_final" or inflight_for(sel):
        return
    enabled, caps, targets = publish_caps()
    if not enabled:
        return
    recs = publish_records(sel)
    pend, _ = publish_pending(sel)
    rows = []
    for r in recs:
        label, tone = PUB_STATUS.get(r.get("status"), (r.get("status") or "?", ""))
        ex = as_dict(r.get("execution"))
        extra = f" · {esc(ex.get('remote_url') or ex.get('remote_id') or '')}" if r.get("status") == "executed" else ""
        extra += f" · {esc(ex.get('error') or '')}" if r.get("status") == "failed" else ""
        rows.append(f"<div class='find'><span class='badge {tone}'>{esc(label)}</span> {esc(r.get('platform'))} · "
                    f"{esc(OP_LABELS.get(r.get('operation'), r.get('operation')))} · {esc(_fmt_local(r.get('scheduled_at')))}{extra}</div>")
    for d in pend:
        what = "Autorización" if d.get("action") == "authorize_publish" else "Revocación"
        rows.append(f"<div class='find'><span class='badge violet'>{what} enviada</span> esperando al backend…</div>")
    if rows:
        st.markdown(f"<div class='ins'>{''.join(rows)}</div>", unsafe_allow_html=True)
    for r in recs:
        if r.get("status") == "authorized" and not any(d.get("target_authorization_id") == r["authorization_id"] for d in pend):
            if st.button(f"Revocar {r.get('platform')} · {OP_LABELS.get(r.get('operation'), r.get('operation'))}",
                         key=f"pub_revoke_{r['authorization_id']}", width="stretch"):
                send_publish_revoke(r["authorization_id"])
    proposal = vjson(sel, "publish_proposal.json")
    _apply_publish_defaults(targets, proposal)
    _plan = job_plan(jid)
    _pop = proposal.get("operation") or _plan.get("operation")
    _pwhen = proposal.get("scheduled_for") or (f"{_plan.get('planned_for')}T{_plan.get('slot')}" if _plan.get("planned_for") and _plan.get("slot") else "")
    _pcap = str(proposal.get("caption") or _plan.get("caption_draft") or "").strip()
    if _pwhen:
        try:
            _dt = datetime.fromisoformat(str(_pwhen).replace("Z", "+00:00"))
            _dt = _dt if _dt.tzinfo else _dt.replace(tzinfo=LOCAL_TZ)
            if _dt <= datetime.now(LOCAL_TZ):
                st.warning("La hora propuesta ya pasó: elige otra.")
        except ValueError:
            pass
    with st.expander("Autorizar publicación", expanded=not any(r.get("status") in PUB_ACTIVE for r in recs)):
        plats = list(targets["platforms"].keys())
        platform = st.selectbox("Plataforma", plats, key="pub_platform")
        ops = targets["platforms"][platform]["operations"]
        if st.session_state.get("pub_operation") not in ops:
            st.session_state.pop("pub_operation", None)
        _has_op = bool(proposal.get("operation") or _plan.get("operation"))
        operation = st.selectbox("Formato", ops, index=0 if _has_op else None, placeholder="Elige el formato",
                                 format_func=lambda o: OP_LABELS.get(o, o), key="pub_operation")
        caption = st.text_area("Caption", key="pub_caption")
        _has_when = bool(_proposal_when(proposal, _plan)) or "pub_when" in st.session_state
        when = st.radio("Cuándo", ("Ahora", "Programar"), index=None if not _has_when else 0, horizontal=True, key="pub_when")
        scheduled = None
        if when == "Programar":
            c1, c2 = st.columns(2)
            day = c1.date_input("Día", key="pub_day")
            hour = c2.time_input("Hora (PT)" if LOCAL_TZ is not timezone.utc else "Hora (UTC)", key="pub_time")
            scheduled = datetime.combine(day, hour).replace(tzinfo=LOCAL_TZ)
        confirm = st.checkbox("Confirmo, publicar una sola vez", key="pub_confirm")
        _ready = bool(operation) and when in ("Ahora", "Programar")
        if st.button("Autorizar publicación", key="pub_send", type="primary", width="stretch", disabled=not (confirm and _ready)):
            if not caption.strip() and operation not in as_list(targets.get("caption_optional_operations")):
                st.error("Escribe el caption.")
            else:
                send_publish_authorization(targets, platform, operation, caption, scheduled)


# ───────────────────────── agenda (protocol/AGENDA_PROTOCOL.md, plan/v1) ─────────────────────────
WEEKDAYS_ES = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")
MONTHS_ES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")

def today_local():
    return datetime.now(LOCAL_TZ).date()

def next_weekday(d, weekday):
    """Next date with that weekday (0=Mon … 4=Fri), today counts if it matches."""
    return d + timedelta(days=(weekday - d.weekday()) % 7)

def day_label(d, n=None):
    base = f"{WEEKDAYS_ES[d.weekday()]} {d.day} {MONTHS_ES[d.month - 1]}"
    return base if n is None else f"{base} · {n}"

def job_plan(job_id):
    """plan.json of a job, validated. {} if absent or invalid."""
    p = as_dict(gh_json(f"jobs/{job_id}/plan.json", {}))
    if p.get("schema") != "plan/v1" or p.get("job_id") not in (None, job_id):
        return {}
    try:
        p["_date"] = datetime.strptime(str(p.get("planned_for")), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return {}
    return p

def agenda_versions(job_id):
    """Versions to show for a planned job: the latest, the last one Elvin approved, any he can still
    decide (same rule as Revisar: not superseded) and any with a decision in flight. The rest only in Studio."""
    names = [v["version"] for v in job_versions(job_id)]
    if not names:
        return []
    approved = [vn for vn in names if decision_action(vn, job_id) == "approve_final"]
    keep = {names[-1], *approved[-1:]}
    keep |= {vn for vn in names if inflight_for(vn, job_id)
             or (is_reviewable(vn, job_id) and not is_superseded(vn, job_id))}
    return [vn for vn in names if vn in keep]

def agenda_index():
    """{date: [(job_id, plan)]} for all planned jobs, plus the list of unplanned jobs that have renders."""
    by_day, unplanned = {}, []
    for j in jobs:
        jid_ = j["job_id"]
        plan = job_plan(jid_)
        if plan:
            by_day.setdefault(plan["_date"], []).append((jid_, plan))
        elif as_list(j.get("versions")):
            unplanned.append(jid_)
    # pieces Muse already planned but not yet generated are not in snapshot.json: read them from jobs/
    known = {j["job_id"] for j in jobs}
    for name in gh_subdirs("jobs"):
        if name in known or name in ARCHIVED:
            continue
        plan = job_plan(name)
        if plan:
            by_day.setdefault(plan["_date"], []).append((name, plan))
    for items in by_day.values():
        items.sort(key=lambda it: (str(it[1].get("slot") or "99:99"), it[0]))
    return by_day, unplanned

def _qc_line(vn, job_id):
    rows = qc_status(verdict(vn, job_id))
    fails = [k for k, (ok, _) in rows.items() if ok is False]
    if not rows or all(ok is None for ok, _ in rows.values()):
        return "QC sin datos"
    return "QC: falla " + ", ".join(fails) if fails else "QC: todo OK"

def render_caption_line(op, cap, draft=False):
    """Caption written by Muse (final from publish_proposal, else draft from plan.json)."""
    cap = str(cap or "").strip()
    if cap:
        lbl = "Caption de Muse (borrador)" if draft else "Caption de Muse"
        st.markdown(f"<div class='find'><b>{lbl}:</b><br>{esc(cap).replace(chr(10), '<br>')}</div>", unsafe_allow_html=True)
    elif op == "story":
        st.caption("Story: sin caption (se publica limpia).")
    elif op:
        st.caption("Muse todavía no escribió el caption.")

def render_plan_card(job_id, plan):
    """Planned piece with no render yet."""
    with st.container(border=True, key=f"ag_plan_{job_id}"):
        title = plan.get("title") or job_id
        where = " · ".join(x for x in (plan.get("slot"), plan.get("platform"),
                                       OP_LABELS.get(plan.get("operation"), plan.get("operation"))) if x)
        st.markdown(f"<div class='ins-head'><b>{esc(title)}</b><span class='badge'>En producción</span></div>", unsafe_allow_html=True)
        if where:
            st.caption(where)

def render_agenda_card(job_id, plan, vn, kp="ag"):
    with st.container(border=True, key=f"{kp}_card_{job_id}_{vn}"):
        title = plan.get("title") or job_id
        where = " · ".join(x for x in (plan.get("slot"), plan.get("platform"),
                                       OP_LABELS.get(plan.get("operation"), plan.get("operation"))) if x)
        st.markdown(f"<div class='ins-head'><b>{esc(title)} · {esc(vn)}</b>{badge_html(vn, job_id)}</div>", unsafe_allow_html=True)
        if where:
            st.caption(where)
        show_asset(vn, job_id, preview=True)
        if decision_action(vn, job_id) == "approve_final":
            _act = [r for r in publish_records(vn, job_id) if r.get("status") in PUB_ACTIVE]
            if _act:
                _r = _act[0]
                st.markdown(f"<div class='find'><span class='badge violet'>Autorizada</span> {esc(OP_LABELS.get(_r.get('operation'), _r.get('operation')))} · "
                            f"{esc(_fmt_es_iso(_r.get('scheduled_at')) if _r.get('scheduled_at') else 'inmediata')}</div>", unsafe_allow_html=True)
            elif publish_caps()[0]:
                st.markdown("<div class='find'><span class='badge amber'>Sin autorizar</span></div>", unsafe_allow_html=True)
        k = f"{job_id}_{vn}"
        if inflight_for(vn, job_id):
            st.caption("Decisión enviada · esperando confirmación…")
        elif is_reviewable(vn, job_id):
            if st.button("✓ Aprobar", key=f"{kp}_approve_{k}", type="primary", width="stretch"):
                send_decision("approve_final", job_id=job_id, vn=vn)
            c1, c2 = st.columns(2)
            if c1.button("✕ Rechazar", key=f"{kp}_reject_{k}", width="stretch"):
                send_decision("reject", job_id=job_id, vn=vn)
            if c2.button("↻ Cambios", key=f"{kp}_changes_{k}", width="stretch"):
                st.session_state[f"{kp}_chg_open_{k}"] = not st.session_state.get(f"{kp}_chg_open_{k}", False)
                st.rerun()
            if st.session_state.get(f"{kp}_chg_open_{k}"):
                with st.form(f"{kp}_chg_form_{k}"):
                    note = st.text_area("Cambios", placeholder="Qué debe corregirse…", label_visibility="collapsed",
                                        key=f"{kp}_chg_note_{k}")
                    if st.form_submit_button("Enviar cambios", type="primary", width="stretch"):
                        if note.strip():
                            st.session_state[f"{kp}_chg_open_{k}"] = False
                            send_decision("request_changes", note, job_id=job_id, vn=vn)
                        else:
                            st.error("Escribe los cambios.")
        if st.button("Abrir", key=f"{kp}_open_{k}", width="stretch"):
            st.session_state.jid = job_id
            st.session_state.sel_ver = vn
            st.session_state.tab = "Studio"
            st.session_state.compare = False
            st.session_state.focus = False
            st.rerun()

def _pub_summary(job_id, vn, plan):
    """(format label, when label, caption preview) from Muse's proposal, else the plan."""
    prop = vjson(vn, "publish_proposal.json", job_id)
    op = prop.get("operation") or plan.get("operation")
    when = prop.get("scheduled_for") or (f"{plan.get('planned_for')}T{plan.get('slot')}" if plan.get("planned_for") else "")
    try:
        dt = datetime.fromisoformat(str(when))
        when_lbl = f"{day_label(dt.date())} {dt.strftime('%H:%M')}"
    except ValueError:
        when_lbl = "sin hora"
    cap = str(prop.get("caption") or "").strip()
    if not cap and plan.get("caption_draft"):
        cap = "(borrador) " + str(plan.get("caption_draft")).strip()
    cap_lbl = (cap[:90] + ("…" if len(cap) > 90 else "")) if cap else ("sin caption (Story)" if op == "story" else "sin caption propuesto")
    return OP_LABELS.get(op, op or "formato sin definir"), when_lbl, cap_lbl, bool(prop)

_MEMO = {}   # per-run memo (the script re-executes on every interaction, so this resets itself)

def needs_elvin():
    """(to_review, to_authorize, approved_unplanned).
    to_review: READY, undecided, not superseded. to_authorize: approved + planned (plan.json or Muse proposal),
    publishing enabled, never authorized/published. approved_unplanned: approved without any publishing plan."""
    if "needs" in _MEMO:
        return _MEMO["needs"]
    enabled, _, _ = publish_caps()
    review, authorize, unplanned = [], [], []
    pend = set(pending_reviews())
    sent = {k for k, ds in _inbox_pub_pending().items() if any(d.get("action") == "authorize_publish" for d in ds)}
    for j in jobs:
        jid_ = j["job_id"]
        plan = job_plan(jid_)
        published = bool(gh_json(f"jobs/{jid_}/published.json", {}))
        for v in job_versions(jid_):
            vn = v["version"]
            if (jid_, vn) in pend:
                review.append((jid_, plan, vn))
            elif enabled and not published and decision_action(vn, jid_) == "approve_final" and not inflight_for(vn, jid_):
                if (jid_, vn) in sent or any(r.get("status") in PUB_ACTIVE | {"executed"} for r in publish_records(vn, jid_)):
                    continue
                if plan or vjson(vn, "publish_proposal.json", jid_):
                    authorize.append((jid_, plan, vn))
                else:
                    unplanned.append((jid_, plan, vn))
    key = lambda it: (str(it[1].get("planned_for") or "9999"), str(it[1].get("slot") or "99:99"), it[0])
    _MEMO["needs"] = (sorted(review, key=key), sorted(authorize, key=key), unplanned)
    return _MEMO["needs"]

def _go_studio(j, vn):
    st.session_state.jid = j
    st.session_state.sel_ver = vn
    st.session_state.tab = "Studio"
    st.session_state.compare = False
    st.session_state.focus = False
    st.rerun()

def render_auth_card(parent, j, p, vn, kp="na"):
    """Approved piece waiting for publish authorization, authorizable right here:
    format, day and time (PT) come prefilled from Muse's proposal (else the plan)."""
    enabled, _, targets = publish_caps()
    prop = vjson(vn, "publish_proposal.json", j)
    plats = list((targets.get("platforms") or {}).keys())
    platform = next((x for x in (prop.get("platform"), p.get("platform")) if x in plats), plats[0] if plats else None)
    ops = (targets.get("platforms") or {}).get(platform, {}).get("operations", []) if platform else []
    op0 = next((x for x in (prop.get("operation"), p.get("operation")) if x in ops), None)
    when0 = _proposal_when(prop, p)
    cap0 = str(prop.get("caption") or p.get("caption_draft") or "").strip()
    k = f"{kp}_{j}_{vn}"
    with parent.container(border=True, key=f"{kp}_auth_{j}_{vn}"):
        c1, c2 = st.columns([1, 2.4])
        with c1:
            typ, info = asset_info(vn, j)
            data = thumb(info) if info and typ == "image" else None
            if data is not None:
                st.image(data, width="stretch")
            else:
                st.caption("video" if typ == "video" else "sin vista previa")
        with c2:
            st.markdown(f"<div class='ins-head'><b>{esc(p.get('title') or j)} · {esc(vn)}</b>"
                        f"<span class='badge amber'>Falta autorizar</span></div>", unsafe_allow_html=True)
            if not (prop or p):
                st.caption("Sin plan ni propuesta de Muse: elige formato y hora.")
            op = st.selectbox("Formato", ops, index=ops.index(op0) if op0 in ops else None, placeholder="Elige el formato",
                              format_func=lambda o: OP_LABELS.get(o, o), key=f"{k}_op")
            mode = st.radio("Cuándo", ("Programar", "Ahora"), index=0 if when0 else None, horizontal=True, key=f"{k}_mode")
            sched = None
            if mode == "Programar":
                d1, d2 = st.columns(2)
                dflt = when0 or (datetime.now(LOCAL_TZ) + timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
                day = d1.date_input("Día", value=dflt.date(), key=f"{k}_day", format="DD/MM/YYYY")
                hour = d2.time_input("Hora (PT)", value=dflt.time().replace(second=0, microsecond=0, tzinfo=None), key=f"{k}_time")
                sched = datetime.combine(day, hour).replace(tzinfo=LOCAL_TZ)
            if op != "story":
                cap = st.text_area("Caption (incluye hashtags)", value=cap0, key=f"{k}_cap", height=110)
            else:
                cap = ""
                st.caption("Story: se publica sin caption.")
            ready = bool(enabled and op and platform and (mode == "Ahora" or (mode == "Programar" and sched)))
            when_lbl = _fmt_es(sched) if sched else "ahora mismo"
            label = f"Autorizar · {OP_LABELS.get(op, op)} · {when_lbl}" if ready else "Elige formato y cuándo"
            if st.button(label, key=f"{k}_go", type="primary", width="stretch", disabled=not ready):
                if op != "story" and not cap.strip() and op not in as_list(targets.get("caption_optional_operations")):
                    st.error("Escribe el caption.")
                else:
                    send_publish_authorization(targets, platform, op, cap, sched, job_id=j, vn=vn)
            if st.button("Ver en Studio", key=f"{k}_studio", width="stretch"):
                _go_studio(j, vn)

def render_needs_elvin():
    review, authorize, unplanned = needs_elvin()
    if not review and not authorize:
        st.success("✓ Nada espera por ti ahora mismo. Muse sigue produciendo.")
    else:
        with st.container(key="ag_needs"):
            st.markdown(f"<div class='pipe-title'>Necesita tu aprobación · {len(review)} por aprobar · "
                        f"{len(authorize)} por autorizar publicación</div>", unsafe_allow_html=True)
            if review:
                _grid = st.container(key="ag_review_grid")
                for j, p, vn in review:
                    with _grid.container(key=f"na_item_{j}_{vn}"):
                        if p.get("planned_for"):
                            st.caption(f"Para {day_label(p['_date'])}")
                        render_agenda_card(j, p, vn, kp="na")
            else:
                st.success("✓ No hay más piezas por aprobar.")
            if authorize:
                st.caption("Aprobadas: falta autorizar su publicación (hora, formato y caption).")
            _auth_grid = st.container(key="ag_auth_grid")
            for j, p, vn in authorize:
                render_auth_card(_auth_grid, j, p, vn, kp="na")
    _sent = [(k, d) for k, ds in _inbox_pub_pending().items() for d in ds if d.get("action") == "authorize_publish"]
    if _sent:
        st.markdown(f"<div class='pipe-title'>Enviadas · esperando confirmación del backend · {len(_sent)}</div>", unsafe_allow_html=True)
        for (j_, vn_), d in _sent:
            st.markdown(f"<div class='find'><b>{esc(job_plan(j_).get('title') or j_)} · {esc(vn_)}</b> · "
                        f"{esc(OP_LABELS.get(d.get('operation'), d.get('operation')))} · {esc(_fmt_es_iso(d.get('scheduled_at')))}</div>",
                        unsafe_allow_html=True)
    if unplanned:
        with st.expander(f"Aprobadas sin plan de publicación · {len(unplanned)}"):
            st.caption("No tienen fecha ni formato. Muse debe planificarlas o marcarlas como ya publicadas; "
                       "hasta entonces no se piden autorizar.")
            for j, p, vn in unplanned:
                c1, c2 = st.container(key=f"na_unpl_row_{j}_{vn}").columns([3, 1.3])
                c1.markdown(f"<div class='find'><b>{esc(j)} · {esc(vn)}</b></div>", unsafe_allow_html=True)
                if c2.button("Ver", key=f"na_unpl_{j}_{vn}", width="stretch"):
                    _go_studio(j, vn)

def _inbox_pub_pending():
    """publish/v1 inbox messages without ACK, all jobs: {(job, vn): [decision, ...]}."""
    inbox, acks = gh_tree("decisions/inbox"), gh_tree("decisions/acks")
    out = {}
    if inbox is None or acks is None:
        return out
    for name in sorted(set(inbox) - set(acks)):
        d = as_dict(parse_json(blob(inbox[name]), {}))
        if d.get("action") in ("authorize_publish", "revoke_publish"):
            out.setdefault((d.get("job_id"), d.get("version")), []).append(d)
    return out

def render_pub_row_card(j, p, vn, r, waiting, kp="pb"):
    """One authorization record as a card (authorized/executing, with revoke) or a compact history row."""
    label, tone = PUB_STATUS.get(r.get("status"), (r.get("status") or "?", ""))
    active = r.get("status") in PUB_ACTIVE
    ex = as_dict(r.get("execution"))
    op = OP_LABELS.get(r.get("operation"), r.get("operation"))
    when = _fmt_es_iso(r["scheduled_at"]) if r.get("scheduled_at") else "inmediata"
    cap = str(r.get("caption") or "").strip()
    cap_html = esc(cap).replace(chr(10), "<br>") if cap else ("sin caption (Story limpia)" if r.get("operation") == "story" else "sin caption")
    extra = ""
    if r.get("status") == "executed":
        extra = f"<br>Publicada: {esc(ex.get('remote_url') or ex.get('remote_id') or '')}"
    elif r.get("status") == "failed":
        extra = f"<br>Error: {esc(ex.get('error') or '')}"
    elif active and r.get("expires_at"):
        extra = f"<br><span class='small'>Vence {esc(_fmt_es_iso(r['expires_at']))}</span>"
    with st.container(border=True, key=f"{kp}_{r['authorization_id']}"):
        if active:
            c1, c2 = st.columns([1, 2.6])
            with c1:
                typ, info = asset_info(vn, j)
                data = thumb(info) if info and typ == "image" else None
                if data is not None:
                    st.image(data, width="stretch")
                else:
                    st.caption("video" if typ == "video" else "sin vista previa")
            body = c2
        else:
            body = st.container()
        with body:
            st.markdown(f"<div class='ins-head'><b>{esc(p.get('title') or j)} · {esc(vn)}</b><span class='badge {tone}'>{esc(label)}</span></div>"
                        f"<div class='find'><b>{esc(op)}</b> en {esc(r.get('platform'))} · <b>{esc(when)}</b><br>{cap_html}{extra}</div>",
                        unsafe_allow_html=True)
            if active:
                if any(d.get("action") == "revoke_publish" and d.get("target_authorization_id") == r["authorization_id"] for d in waiting):
                    st.caption("Revocación enviada · esperando al backend…")
                elif r.get("status") == "authorized":
                    if st.button("Revocar autorización", key=f"{kp}_rv_{r['authorization_id']}", width="stretch"):
                        send_publish_revoke(r["authorization_id"], job_id=j, vn=vn)
            if st.button("Abrir en Studio", key=f"{kp}_st_{r['authorization_id']}", width="stretch"):
                _go_studio(j, vn)

def render_publicaciones():
    """Single place: what is authorized, what is not, and what already went out."""
    enabled, _, _ = publish_caps()
    render_notice()
    if not enabled:
        st.info("La autorización de publicación se activa cuando el backend de Muse soporte publish/v1.")
        return
    waiting = _inbox_pub_pending()
    review, authorize, unplanned = needs_elvin()
    active, history, sent = [], [], []
    for j in jobs:
        jid_ = j["job_id"]
        plan = job_plan(jid_)
        for v in job_versions(jid_):
            vn = v["version"]
            recs = publish_records(vn, jid_)
            for r in recs:
                (active if r.get("status") in PUB_ACTIVE else history).append((jid_, plan, vn, r))
            if not any(r.get("status") in PUB_ACTIVE for r in recs):
                for d in waiting.get((jid_, vn), []):
                    if d.get("action") == "authorize_publish":
                        sent.append((jid_, plan, vn, d))
    _t = lambda it: str(it[3].get("scheduled_at") or "0")
    active.sort(key=_t)
    history.sort(key=lambda it: str((it[3].get("history") or [{}])[-1].get("at") or ""), reverse=True)
    st.markdown(f"<div class='pipe-title'>Autorizadas · {len(active)}</div>", unsafe_allow_html=True)
    if not active:
        st.info("Ninguna publicación autorizada ahora mismo.")
    with st.container(key="pb_grid_active"):
        for j, p, vn, r in active:
            render_pub_row_card(j, p, vn, r, waiting.get((j, vn), []), kp="pba")
    if sent:
        st.markdown(f"<div class='pipe-title'>Enviadas · esperando al backend · {len(sent)}</div>", unsafe_allow_html=True)
        for j, p, vn, d in sent:
            st.markdown(f"<div class='find'><b>{esc(p.get('title') or j)} · {esc(vn)}</b> · "
                        f"{esc(OP_LABELS.get(d.get('operation'), d.get('operation')))} · {esc(_fmt_es_iso(d.get('scheduled_at')))}</div>",
                        unsafe_allow_html=True)
    st.markdown(f"<div class='pipe-title'>Sin autorizar · aprobadas · {len(authorize)}</div>", unsafe_allow_html=True)
    if not authorize:
        st.success("✓ No hay piezas aprobadas pendientes de autorizar.")
    with st.container(key="pb_grid_auth"):
        for j, p, vn in authorize:
            render_auth_card(st.container(), j, p, vn, kp="pb")
    st.markdown(f"<div class='pipe-title'>Sin aprobar · {len(review)}</div>", unsafe_allow_html=True)
    if review:
        st.caption(", ".join(f"{(p.get('title') or j)} {vn}" for j, p, vn in review))
        if st.button("Ir a Agenda para aprobarlas", key="pb_to_agenda", width="stretch"):
            st.session_state.tab = "Agenda"
            st.rerun()
    else:
        st.caption("Nada por aprobar.")
    if history:
        with st.expander(f"Historial · publicadas, revocadas, vencidas · {len(history)}"):
            for j, p, vn, r in history:
                render_pub_row_card(j, p, vn, r, [], kp="pbh")

def render_revisar():
    render_notice()
    render_needs_elvin()

def render_agenda():
    if True:
        by_day, unplanned = agenda_index()
        today = today_local()
        if "ag_day" not in st.session_state:
            st.session_state.ag_day = today
        with st.container(key="ag_quick"):
            q1, q2, q3 = st.columns([1, 1, 1.3])
        q4 = st.container()
        if q1.button("Hoy", key="ag_today", width="stretch"):
            st.session_state.ag_day = today
        if q2.button("Mañana", key="ag_tomorrow", width="stretch"):
            st.session_state.ag_day = today + timedelta(days=1)
        if q3.button("Próx. viernes", key="ag_friday", width="stretch"):
            st.session_state.ag_day = next_weekday(today + timedelta(days=1), 4)
        picked = q4.date_input("Día", value=st.session_state.ag_day, key=f"ag_date_{st.session_state.ag_day}",
                               label_visibility="collapsed", format="DD/MM/YYYY")
        if picked != st.session_state.ag_day:
            st.session_state.ag_day = picked
            st.rerun()
        day = st.session_state.ag_day
        monday = day - timedelta(days=day.weekday())
        week = [monday + timedelta(days=i) for i in range(7)]
        labels = {day_label(d, len(by_day.get(d, []))): d for d in week}
        chosen = st.pills("Semana", list(labels), default=day_label(day, len(by_day.get(day, []))),
                          key=f"ag_week_{day}", label_visibility="collapsed")
        if chosen and labels.get(chosen) != day:
            st.session_state.ag_day = labels[chosen]
            st.rerun()

        items = by_day.get(day, [])
        pending = sum(1 for j, _ in items for vn in agenda_versions(j) if is_reviewable(vn, j))
        approved = sum(1 for j, _ in items for vn in agenda_versions(j) if decision_action(vn, j) == "approve_final")
        st.markdown(f"<div class='pipe-title'>{esc(day_label(day))} · {len(items)} propuesta(s) · "
                    f"{pending} por decidir · {approved} aprobada(s)</div>", unsafe_allow_html=True)
        render_notice()
        if not items:
            st.info("No hay propuestas planificadas para este día.")
        cards = [(j, p, vn) for j, p in items for vn in (agenda_versions(j) or [None])]
        with st.container(key="ag_grid"):
            for j, p, vn in cards:
                if vn:
                    render_agenda_card(j, p, vn)
                else:
                    render_plan_card(j, p)
        if unplanned:
            with st.expander(f"Sin fecha en la agenda · {len(unplanned)} job(s)"):
                st.caption("Estos jobs no tienen plan.json; Muse debe asignarles fecha para que aparezcan en un día.")
                st.write(", ".join(unplanned))


def render_queue():
    st.caption(f"{jid} · {LIVE_LBL} · actualizado {human_age(AGE)}")
    events = gh_json(f"jobs/{jid}/events.json", {})
    lines = as_list(events.get("lines")) if isinstance(events, dict) else []
    if lines:
        st.code("\n".join(str(x) for x in lines[-80:]), language=None, wrap_lines=True)
    else:
        rows = []
        for v in versions:
            m = meta(v["version"])
            rows.append({"version": v["version"], "status": status_badge(v["version"])[0],
                         "registered": f"hace {human_age(hours_since(m.get('registered')))}" if m.get("registered") else "—", "model": as_dict(m.get("params")).get("model")})
        st.dataframe(rows, width="stretch", hide_index=True)

def render_model():
    metrics = as_dict(gh_json("learning/metrics.json", {}))
    rules_l = as_list(gh_json("learning/rules.json", []))
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Muse ↔ QA", f"{num(metrics.get('acuerdo_pct')):g}%")
    c2.metric("QA cost", f"${num(metrics.get('costo_supervisor_total_usd')):.4f}")
    c3.metric("Elvin caught", int(num(metrics.get("human_caught_miss"))))
    fp = num(metrics.get("falsos_positivos_muse")) + num(metrics.get("falsos_positivos_supervisor"))
    c4.metric("False positives", int(fp))
    st.caption(f"Phase: {metrics.get('fase', '—')} · Reviews: {metrics.get('revisiones_totales', 0)} · Learned rules: {metrics.get('reglas_aprendidas', 0)}")
    active = [r for r in rules_l if isinstance(r, dict) and r.get("activa")]
    if not active:
        st.caption("Sin reglas activas sincronizadas.")
    for r in active:
        st.markdown(f"**{r.get('id', '—')}** — {r.get('regla', '')}")

def archive_job(job_id, flag):
    obj = {"schema": "archive/v1", "archived": bool(flag), "by": "elvin", "via": "dashboard", "reason": "", "at": now_iso()}
    ok, d = gh_put_json(f"jobs/{job_id}/archived.json", obj, f"{'archive' if flag else 'restore'} {job_id}")
    if ok:
        clear_bus_cache()
        set_notice(f"{job_id} {'archivado' if flag else 'restaurado'}.", "success")
        st.rerun()
    else:
        st.error(f"No se pudo guardar: {d}")

def render_sistema():
    render_notice()
    tdir = gh_dir("tasks/status") or {}
    tasks = [as_dict(parse_json(blob(i), {})) for n, i in tdir.items() if n.endswith(".json")]
    tasks = sorted([x for x in tasks if x.get("task_id")], key=lambda x: str(x.get("updated") or ""), reverse=True)[:6]
    st.markdown("<div class='sec'>Tareas de Muse</div>", unsafe_allow_html=True)
    for x in tasks:
        st.markdown(f"<div class='rt'>{esc(x.get('task_id'))}</div><div class='rs'>{esc(x.get('status'))}</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='sec'>Descartadas · {len(ARCHIVED)}</div>", unsafe_allow_html=True)
    if not ARCHIVED:
        st.caption("Ninguna")
    for j in sorted(ARCHIVED):
        c1, c2 = st.container(key=f"sys_arch_row_{j}").columns([4, 1.4])
        c1.markdown(f"<div class='rt'>{esc(j)}</div>", unsafe_allow_html=True)
        if c2.button("Restaurar", key=f"sys_rest_{j}", width="stretch"):
            archive_job(j, False)
    loose = [j["job_id"] for j in jobs if not job_plan(j["job_id"]) and j["job_id"] != "—"]
    if loose:
        st.markdown(f"<div class='sec'>Sin plan · {len(loose)}</div>", unsafe_allow_html=True)
    for j in loose:
        c1, c2 = st.container(key=f"sys_loose_{j}").columns([4, 1.4])
        c1.markdown(f"<div class='rt'>{esc(j)}</div>", unsafe_allow_html=True)
        if c2.button("Descartar", key=f"sys_arch_{j}", width="stretch"):
            archive_job(j, True)
    with st.expander(f"Cola del job · {jid}"):
        render_queue()
    with st.expander("Modelo y reglas aprendidas"):
        render_model()
    st.caption(f"QA ${num(budget.get('monthly_used_usd')):.2f} este mes")

def _next_task_id(slug):
    names = [n for n in (gh_dir("tasks") or {}) if n.endswith(".json") and n[:4].isdigit()]
    num_ = max((int(n[:4]) for n in names), default=0) + 1
    return f"{num_:04d}-{slug}"

def send_resume_task(changes):
    """Elvin asks Muse to resume (mailbox/v1). Elvin's click is the approval (approved_by_elvin_at)."""
    tid = _next_task_id("retomar-trabajo")
    lines = [f"# Tarea {tid[:4]} — Retomar el trabajo interrumpido (pedido desde el Control Center)", "",
             f"Última actividad propia de Muse: {MUSE['last_event'][:300] or '—'}", "",
             "Hacer, en este orden:",
             "1. Retoma la tarea interrumpida desde su último paso completo (no repitas generaciones ya registradas).",
             "2. Atiende las piezas con cambios pedidos por Elvin: usa `orchestrator.elvin_change_request(job_id)` y aplica su nota "
             "como corrección obligatoria de la siguiente versión:"]
    lines += [f"   - {j}" for j in changes] or ["   - (ninguna)"]
    lines += ["3. En esperas largas (MiniMax, Krea, supervisor) usa `with progress.keepalive(...)` para que el Control Center vea que sigues vivo.",
              "4. Al terminar: `reports/<id>.md` con lo hecho y status `done`.",
              "Reglas permanentes: nada pagado sin autorización, no publicar sin approve_final + authorize_publish, no borrar historial."]
    ok1, d1 = gh_put_json(f"tasks/{tid}.md", "\n".join(lines), f"task {tid}", create_only=True, raw=True)
    if not ok1:
        st.error(f"No se pudo crear la tarea: {d1}")
        return
    ok2, d2 = gh_put_json(f"tasks/{tid}.json", {"schema": "mailbox/v1", "task_id": tid,
                          "title": "Retomar el trabajo interrumpido", "instructions": f"tasks/{tid}.md",
                          "approved_by_elvin_at": now_iso(), "created": now_iso(), "author": "dashboard"},
                          f"task {tid}", create_only=True)
    if ok2:
        clear_bus_cache()
        set_notice(f"Tarea {tid} enviada a Muse. Debe pasar a 'received' en ≤ 2 min.", "success")
        st.rerun()
    else:
        st.error(f"No se pudo crear la tarea: {d2}")

def _discard(j):
    """Hide a piece everywhere (archived.json). Reversible from Sistema → Descartadas → Restaurar."""
    archive_job(j, True)

def _thumb_col(col, vn, j):
    typ, info = asset_info(vn, j)
    data = thumb(info) if info and typ == "image" else None
    if data is not None:
        col.image(data)
    else:
        col.markdown("<div class='rs'>▶ video</div>" if typ == "video" else "<div class='rs'>—</div>", unsafe_allow_html=True)

def _piece_when(j, vn, p):
    op, when, _c, _prop = _pub_summary(j, vn, p)
    return f"{op} · {when}"

def render_hoy():
    """v10.1 home — quiet: three status chips, then only pieces that need you (photo + name + one button)."""
    render_notice()
    dh = as_dict(gh_json("progress/daemon_health.json", {}))
    d_age = (time.time() - _parse_ts_or(dh.get("cycle_ended"), 0)) if dh.get("cycle_ended") else None
    pend = len(HEALTH["pending"]) if HEALTH else None
    if MUSE["down"]:
        muse = ("red", f"Muse parado · {human_age(MUSE['own_age_h'])}")
    elif MUSE["status"] in MUSE_ACTIVE:
        muse = ("", f"Muse trabajando")
    else:
        muse = ("amber", "Muse sin tarea")
    if d_age is None or d_age > DAEMON_DOWN_S:
        dae = ("red", "Daemon apagado")
    else:
        dae = ("", "Daemon ok")
    dec = ("amber", f"{pend} sin confirmar") if pend else ("", "Decisiones al día")
    st.markdown("<div class='chips'>" + "".join(f"<span class='chip {c}'><i></i>{esc(x)}</span>" for c, x in (muse, dae, dec)) + "</div>",
                unsafe_allow_html=True)

    def _still_waiting(j):
        # job.state can lag behind (Muse reconciles it later): waiting only if the LATEST version is still the one with changes requested
        vs = job_versions(j["job_id"])
        return bool(vs) and vs[-1].get("veredicto_efectivo") == "CHANGES_REQUESTED"
    changes = sorted(((j["job_id"], j.get("updated")) for j in jobs if j.get("state") == "CHANGES_REQUESTED" and _still_waiting(j)),
                     key=lambda x: str(x[1] or ""))
    if MUSE["down"] and st.button("Pedir a Muse que retome", key="hoy_resume", type="primary", width="stretch"):
        send_resume_task([j for j, _ in changes])

    review, authorize, _unpl = needs_elvin()
    st.markdown(f"<div class='sec'>Te toca · {len(review) + len(authorize)}</div>", unsafe_allow_html=True)
    if ms.get("status") == "BLOCKED_ON_ELVIN" and ms.get("needs_decision"):
        st.warning(str(ms.get("needs_decision"))[:200])
    if not review and not authorize:
        st.caption("Nada pendiente ✓")
    for j, p, vn in review:
        with st.container(key=f"hoy_row_{j}_{vn}"):
            c1, c2, c3, c4 = st.columns([1, 3.2, 1.6, 1.4])
            _thumb_col(c1, vn, j)
            c2.markdown(f"<div class='rt'>{esc(p.get('title') or j)} · {esc(vn)}</div><div class='rs'>por aprobar</div>", unsafe_allow_html=True)
            if c3.button("Revisar", key=f"hoy_go_{j}_{vn}", type="primary", width="stretch"):
                _go_studio(j, vn)
            if c4.button("Descartar", key=f"hoy_dx_{j}_{vn}", width="stretch"):
                _discard(j)
    for j, p, vn in authorize:
        with st.container(key=f"hoy_row_auth_{j}_{vn}"):
            c1, c2, c3 = st.columns([1, 4.8, 1.4])
            _thumb_col(c1, vn, j)
            c2.markdown(f"<div class='rt'>{esc(p.get('title') or j)} · {esc(vn)}</div><div class='rs'>falta autorizar · {esc(_piece_when(j, vn, p))}</div>",
                        unsafe_allow_html=True)
            if c3.button("Descartar", key=f"hoy_dxa_{j}_{vn}", width="stretch"):
                _discard(j)
        with st.expander("Autorizar", expanded=False):
            render_auth_card(st.container(), j, p, vn, kp="hoy")

    stuck = [(j["job_id"], v["version"]) for j in jobs for v in as_list(j.get("versions"))
             if isinstance(v, dict) and v.get("veredicto_efectivo") == "READY_PENDING_PUSH"]
    checks = [(j["job_id"], v["version"], r) for j in jobs for v in job_versions(j["job_id"])
              for r in publish_records(v["version"], j["job_id"]) if r.get("status") == "needs_check"]
    if changes or stuck or checks:
        st.markdown(f"<div class='sec'>Esperando a Muse · {len(changes) + len(stuck)}</div>", unsafe_allow_html=True)
    for j, upd in changes:
        c1, c2 = st.columns([5.6, 1.4])
        c1.markdown(f"<div class='rt'>{esc(j)}</div><div class='rs'>cambios pedidos hace {esc(human_age(hours_since(upd)))}</div>", unsafe_allow_html=True)
        if c2.button("Descartar", key=f"hoy_dxc_{j}", width="stretch"):
            _discard(j)
    for j, vn in stuck:
        st.markdown(f"<div class='rt'>{esc(j)} · {esc(vn)}</div><div class='rs'>subiendo al bus</div>", unsafe_allow_html=True)
    for j, vn, r in checks:
        st.error(f"{j} · {vn}: la publicación no cerró. Comprueba en Instagram si salió.")

    upcoming = sorted(((j["job_id"], v["version"], r) for j in jobs for v in job_versions(j["job_id"])
                       for r in publish_records(v["version"], j["job_id"]) if r.get("status") == "authorized"),
                      key=lambda x: str(x[2].get("scheduled_at") or ""))
    if upcoming:
        st.markdown(f"<div class='sec'>Se publica · {len(upcoming)}</div>", unsafe_allow_html=True)
    for j, vn, r in upcoming[:6]:
        when = _fmt_es_iso(r["scheduled_at"]) if r.get("scheduled_at") else "ahora"
        late = r.get("scheduled_at") and hours_since(r["scheduled_at"]) * 60 > 5
        st.markdown(f"<div class='rt'>{esc(when)} · {esc(OP_LABELS.get(r.get('operation'), r.get('operation')))}</div>"
                    f"<div class='rs'>{esc(j)}{' · <b style=color:#fb7185>no salió a su hora</b>' if late else ''}</div>", unsafe_allow_html=True)

def render_nav():
    with NAV_SLOT:
        nav = st.columns([.7, .8, .9, .8, 3, .6])
        _nr, _na, _ = needs_elvin()
        _n_review = len(_nr) + len(_na)
        for i, name in enumerate(("Hoy", "Agenda", "Publicaciones", "Sistema")):
            label = f"Hoy {_n_review}" if name == "Hoy" and _n_review else ("Publicar" if name == "Publicaciones" else name)
            if nav[i].button(label, key=f"nav_{name}", type="primary" if st.session_state.tab in (name, "Studio" if name == "Hoy" else "") else "secondary", width="stretch"):
                st.session_state.tab = name
                st.session_state.compare = False
                st.session_state.focus = False
                st.rerun()
        chosen = (nav[4].selectbox("Job", job_ids, index=job_ids.index(jid), label_visibility="collapsed")
                  if st.session_state.tab == "Studio" else jid)
        if nav[5].button("Salir", key="logout", width="stretch"):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.session_state["cookie_clear"] = True
            st.rerun()
    if chosen != jid:
        # In-flight decisions are kept (keyed by job|version) so switching jobs never re-enables decided controls.
        st.session_state.jid = chosen
        st.session_state.sel_ver = None
        st.session_state.compare = False
        st.session_state.focus = False
        st.session_state.change_open = False
        st.session_state.notice = None
        st.rerun()

render_nav()

# ───────────────────────── tabs ─────────────────────────
TAB = st.session_state.tab
if TAB == "Studio":
    if not versions:
        st.info("Este job todavía no tiene renders.")
    elif st.session_state.focus:
        with st.container(key="kv_focus"):
            if st.button("← Volver", key="focus_back"):
                st.session_state.focus = False
                st.rerun()
            show_asset(sel)
    else:
        if st.session_state.inspector:
            canvas, insp = st.columns([7, 2.4], gap="small")
        else:
            canvas = st.container()
            insp = None

        with canvas:
            _b1, _b2 = st.columns([4, 1.2])
            if _b1.button("← Hoy", key="studio_back"):
                st.session_state.tab = "Hoy"
                st.rerun()
            if _b2.button("Descartar", key="studio_discard", width="stretch"):
                _discard(jid)
            st.markdown(f"<div class='canvas-label'><span><b>{esc(job_plan(jid).get('title') or jid)} · {esc(sel)}</b></span>{badge_html(sel)}</div>", unsafe_allow_html=True)
            if st.session_state.compare and len(version_ids) >= 2:
                idx = version_ids.index(sel)
                other = version_ids[idx - 1] if idx > 0 else version_ids[1]
                pair = sorted([sel, other], key=version_ids.index)
                left, right = st.columns(2)
                for col, vn in zip((left, right), pair):
                    with col:
                        st.caption(f"{vn}{' · seleccionada' if vn == sel else ''}")
                        show_asset(vn)
            else:
                show_asset(sel)

            with st.expander("Detalles de QC"):
                st.markdown(inspector_html(sel, with_header=False, with_specs=False), unsafe_allow_html=True)

            render_decision_block()
            render_publish_block()

            with st.container(key="kv_tools"):
                opts = list(reversed(version_ids))
                tcols = st.columns([1, 1, 1, 4.5] if len(opts) > 1 else [1, 1, 5.5])
                if len(opts) > 1:
                    if tcols[0].button("Compare" if not st.session_state.compare else "Close", key="tool_compare", width="stretch"):
                        st.session_state.compare = not st.session_state.compare
                        st.rerun()
                    fs_col, tog_col = tcols[1], tcols[2]
                else:
                    fs_col, tog_col = tcols[0], tcols[1]
                if fs_col.button("⛶ Full", key="tool_full", width="stretch"):
                    st.session_state.focus = True
                    st.rerun()
                with tog_col.container(key="tog_insp"):
                    if st.button("Detalles ▸" if st.session_state.inspector else "◂ Detalles", key="tool_insp", width="stretch"):
                        st.session_state.inspector = not st.session_state.inspector
                        st.rerun()
            if len(opts) > 1:
                picked = st.pills("Versiones", opts, default=sel, label_visibility="collapsed", **PILLS_KW)
                if picked and picked != sel:
                    st.session_state.sel_ver = picked
                    st.session_state.compare = False
                    st.session_state.change_open = False
                    st.rerun()

            render_notice()

        if insp is not None:
            with insp:
                with st.container(key="kv_insp"):
                    st.markdown(f"<div class='pipe-title'>Inspector</div>{inspector_html(sel)}", unsafe_allow_html=True)

elif TAB == "Hoy":
    render_hoy()

elif TAB == "Agenda":
    render_agenda()

elif TAB == "Publicaciones":
    render_publicaciones()

elif TAB == "Revisar":
    render_revisar()

elif TAB == "Queue":
    render_queue()

elif TAB == "Model":
    render_model()

elif TAB == "Sistema":
    render_sistema()

st.markdown(f"<div class='kv-foot'>Mission Control {APP_VERSION}</div>", unsafe_allow_html=True)
