"""KAIA VALE — Mission Control v6.6.
Approval-path hardening over v6.5. GitHub bus and inbox + ACK protocol unchanged;
decision records only gain additive fields (asset_file, asset_sha).
- Asset approvals only through job/version decisions: Muse's yes/no channel can no
  longer approve an asset that is not registered as a version.
- Decisions are bound to the exact asset blob (sha) and are idempotent (uuid5 id +
  create-only write), so double taps / stale API reads cannot create duplicates.
- Sync health banner: unprocessed inbox decisions and Muse heartbeat age are shown
  from real bus data, so a stopped backend is visible instead of looking "Idle".
- Default job = one waiting for Elvin, else the most recently updated.
"""
import base64, hmac, html, inspect, json, re, time, uuid
from datetime import datetime, timezone
from urllib.parse import quote
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

APP_VERSION = "v6.6"
DECISION_NS = uuid.UUID("6f1c2d3e-9a4b-4c5d-8e7f-0a1b2c3d4e5f")   # fixed namespace for idempotent decision ids
HEARTBEAT_STALE_H = 2          # Muse heartbeat older than this = no live activity
# Questions that try to approve/authorize an asset or a publication must go through job/version decisions.
ASSET_APPROVAL_RE = re.compile(r"aprob|apru[eé]b|autoriz|publica|regener", re.I)
REFRESH_MS = 30_000
PENDING_REFRESH_MS = 5_000
ACK_TIMEOUT_S = 600            # warn if the backend has not ACKed after 10 min
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
                  "ESCALAR": ("Escalated", "red"), "APROBADO": ("QA approved", "green")}
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
H_RAW = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github.raw"}
H_JSON = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"}

DEFAULTS = {"auth": False, "login_attempts": 0, "login_locked_until": 0.0,
            "tab": "Studio", "sel_ver": None, "compare": False, "focus": False, "inspector": True,
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
/* review / decision */
.review{margin-bottom:8px;border:1px solid rgba(139,92,246,.55);background:linear-gradient(90deg,rgba(139,92,246,.1),rgba(34,211,238,.04));border-radius:12px;padding:9px 12px;color:#ddd9ff;font-size:.8rem}
.review.green{border-color:rgba(52,211,153,.5);background:rgba(52,211,153,.07);color:#c9f8e2}
.review.red{border-color:rgba(251,113,133,.5);background:rgba(251,113,133,.07);color:#ffd1d9}
.review.amber,.review.warn{border-color:rgba(251,191,36,.55);background:rgba(251,191,36,.06);color:#ffe9b0}
/* inspector */
.ins{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:10px;margin-top:8px}.ins:first-child{margin-top:0}
.ins-head{display:flex;justify-content:space-between;align-items:center;gap:8px;font-size:.9rem}
.qc{display:flex;justify-content:space-between;padding:7px 8px;background:#171923;border-radius:8px;margin:5px 0;font-size:.78rem}.ok{color:var(--green)}.bad{color:var(--red)}.na{color:var(--muted)}
.find{font-size:.76rem;line-height:1.42;color:#c5cada;padding:6px 0;border-bottom:1px solid #202432}.find:last-child{border-bottom:0}
.spec{display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:.72rem;color:var(--muted)}.spec b{display:block;color:var(--text);margin-top:2px}
.livebar{display:flex;align-items:center;gap:9px;height:34px;padding:0 12px;background:#0e1017;border:1px solid var(--line);border-radius:11px;color:var(--muted);font-size:.78rem;overflow:hidden;white-space:nowrap}.livebar b{color:var(--text)}
.livebar span:last-child{overflow:hidden;text-overflow:ellipsis}
.small{font-size:.72rem;color:var(--muted)}
.kv-foot{font-size:.66rem;color:#4a5062;text-align:right;margin-top:4px}
.mobile-only{display:none}
@media(max-width:760px){
.block-container,[data-testid="stMainBlockContainer"]{padding:.35rem .6rem 5rem!important}
.desktop-only,.st-key-kv_pipe,.st-key-kv_insp,.st-key-tog_insp{display:none!important}
.mobile-only{display:block}.pipe-mini.mobile-only{display:flex}div.mobile-only{padding-bottom:10px}
.pipe-mini .pipe-item:not(.active):not(.stopped) b{display:none}
.kv-logo{font-size:.8rem}.kv-top{height:36px}
/* nav: tabs + Salir in one row, job selector full width below */
.st-key-kv_nav [data-testid="stHorizontalBlock"]{flex-wrap:wrap!important;gap:.4rem!important}
.st-key-kv_nav [data-testid="stColumn"]{flex:1 1 0!important;min-width:0!important;width:auto!important}
.st-key-kv_nav [data-testid="stColumn"]:nth-child(4){order:5;flex:1 1 100%!important}
.st-key-kv_nav button{min-height:34px!important;padding:0 6px!important}
/* decision + tools rows never stack */
.st-key-kv_decide [data-testid="stHorizontalBlock"],.st-key-kv_tools [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;gap:.4rem!important}
.st-key-kv_decide [data-testid="stColumn"],.st-key-kv_tools [data-testid="stColumn"]{flex:1 1 0!important;min-width:0!important;width:auto!important}
.st-key-kv_decide button{padding:0 4px!important;font-size:.8rem!important}
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

@st.cache_data(ttl=20, show_spinner=False, max_entries=500)
def gh_fetch(path):
    """Small, rapidly-changing control files (20 s cache)."""
    return _fetch(path)

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

@st.cache_data(ttl=20, show_spinner=False, max_entries=300)
def gh_dir(path):
    """Directory listing {name: {sha, path, size}}; {} if missing; None on error."""
    return _dir(path)

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

def gh_put_json(path, obj, msg, *, create_only=False):
    content = base64.b64encode(json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")).decode()
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
            st.rerun()
        else:
            st.session_state.login_attempts += 1
            if st.session_state.login_attempts >= MAX_LOGIN_ATTEMPTS:
                st.session_state.login_attempts = 0
                st.session_state.login_locked_until = time.time() + LOGIN_LOCKOUT_S
                st.error(f"Password incorrecto. Bloqueado {LOGIN_LOCKOUT_S} s.")
            else:
                st.error("Password incorrecto.")
    st.stop()

# Non-blocking, browser-side refresh (no sleep()).
st_autorefresh(interval=REFRESH_MS, limit=None, key="mission_control_refresh")


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
    return any(isinstance(v, dict) and v.get("veredicto_efectivo") == "READY_FOR_ELVIN_REVIEW" and not v.get("decidido")
               for v in as_list(j.get("versions")))

jobs = sorted(jobs, key=_job_sort_key)
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

AGE = hours_since(state.get("updated"))
LIVE = AGE < .25
cur_info = next((v for v in versions if v["version"] == cur), {})

def vinfo(vn):
    return next((v for v in versions if v["version"] == vn), {})

def vkey(vn, job_id=None):
    return f"{job_id or jid}|{vn}"

def vfiles(vn):
    if not vn:
        return {}
    return gh_dir(f"jobs/{jid}/versions/{vn}") or {}

def vjson(vn, name):
    return as_dict(parse_json(blob(vfiles(vn).get(name)), {}))

def verdict(vn): return vjson(vn, "verdict.json")
def meta(vn): return vjson(vn, "meta.json")

def asset_info(vn):
    files = vfiles(vn)
    for typ, ext in (("video", "mp4"), ("image", "png"), ("image", "jpg"), ("image", "jpeg")):
        f = files.get(f"asset.{ext}")
        if f:
            return typ, f
    return None, None

def show_asset(vn):
    typ, info = asset_info(vn)
    data = blob(info, small=False) if info else None
    if typ and data is None:
        st.warning("No se pudo descargar el asset. Reintentando en el próximo refresco.")
    elif typ == "image":
        st.image(data, width="stretch")
    elif typ == "video":
        st.video(data)
    else:
        st.info("Asset todavía no sincronizado.")

def decision_action(vn):
    if not vn:
        return None
    local = st.session_state.local_decided.get(vkey(vn))
    if local:
        return local
    d = vjson(vn, "decision_elvin.json")
    return d.get("decision") or d.get("action")

def is_decided(vn):
    return bool(vinfo(vn).get("decidido")) or bool(decision_action(vn))

def _parse_ts(iso):
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()
    except Exception:
        return time.time()

GIT_API = f"https://api.github.com/repos/{REPO}"

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
def gh_tree(dir_path):
    return _tree(dir_path)

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

def inbox_decision_for(vn, *, fresh=False):
    """Find a decision for jid/vn that is still pending (inbox file without ACK), from any
    session/device. The backend never deletes inbox files, so pending = inbox ids − ack ids;
    only those few files are read. Returns (record|None, ok).
    With fresh=True also checks ACKs accepted in the last hours, covering the window
    before decision_elvin.json is synced."""
    inbox = _tree("decisions/inbox") if fresh else gh_tree("decisions/inbox")
    acks = _tree("decisions/acks") if fresh else gh_tree("decisions/acks")
    if inbox is None or acks is None:
        return None, False
    for name in sorted(set(inbox) - set(acks)):
        if not name.endswith(".json"):
            continue
        d = as_dict(parse_json(blob(inbox[name]), {}))
        if d.get("job_id") != jid or d.get("version") != vn:
            continue
        return {"decision_id": d.get("decision_id") or name[:-5], "job_id": jid, "version": vn,
                "action": d.get("action"), "sent_at": _parse_ts(d.get("timestamp")), "ack_status": ""}, True
    if fresh:
        recent = _recent_ack_paths()
        if recent is None:
            return None, False
        for path in recent:
            a = as_dict(gh_json(path, {}, fresh=True))
            if a.get("job_id") == jid and a.get("version") == vn and str(a.get("status", "")).lower() in ACK_OK:
                return {"decision_id": a.get("decision_id") or path.rsplit("/", 1)[-1][:-5], "job_id": jid,
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
    if v.get("veredicto_efectivo") == "READY_FOR_ELVIN_REVIEW" and not is_decided(vn) and k not in st.session_state.inflight:
        rec, _ = inbox_decision_for(vn)
        if rec:
            st.session_state.inflight[k] = rec

# 2) Poll the exact ACK (uncached) for every in-flight decision of this job.
for k, p in list(st.session_state.inflight.items()):
    if p.get("job_id") != jid:
        continue
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

def inflight_for(vn):
    return st.session_state.inflight.get(vkey(vn))

def is_reviewable(vn):
    return (vinfo(vn).get("veredicto_efectivo") == "READY_FOR_ELVIN_REVIEW"
            and not is_decided(vn) and not inflight_for(vn))

CUR_PEND = is_reviewable(cur)
CUR_INFLIGHT = bool(inflight_for(cur))
CUR_DECISION = decision_action(cur)
JOB_HAS_INFLIGHT = any(p.get("job_id") == jid for p in st.session_state.inflight.values())

if JOB_HAS_INFLIGHT:
    st_autorefresh(interval=PENDING_REFRESH_MS, limit=None, key="pending_decision_refresh")

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
with st.container(key="kv_nav"):
    nav = st.columns([.72, .72, .72, 5.2, .6])
    for i, name in enumerate(("Studio", "Queue", "Model")):
        if nav[i].button(name, key=f"nav_{name}", type="primary" if st.session_state.tab == name else "secondary", width="stretch"):
            st.session_state.tab = name
            st.session_state.compare = False
            st.session_state.focus = False
            st.rerun()
    chosen = nav[3].selectbox("Job", job_ids, index=job_ids.index(jid), label_visibility="collapsed")
    if nav[4].button("Salir", key="logout", width="stretch"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
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


# ───────────────────────── sync health (real bus data) ─────────────────────────
HEALTH = sync_health()
if HEALTH is None:
    st.markdown("<div class='review warn'><b>Sync</b> · no se pudo leer el inbox/ACK en GitHub. Reintentando.</div>", unsafe_allow_html=True)
else:
    stale_pending = [p for p in HEALTH["pending"] if time.time() - p["ts"] > ACK_TIMEOUT_S]
    if stale_pending:
        items = ", ".join(f"{p['job_id']} {p['version']} ({p['action']})" for p in stale_pending[:4])
        dup = f" · {HEALTH['duplicates']} duplicada(s)" if HEALTH["duplicates"] else ""
        st.markdown(
            f"<div class='review red'><b>Backend detenido</b> · {len(stale_pending)} decisión(es) sin procesar, "
            f"la más antigua hace {esc(human_age(HEALTH['oldest_age_s'] / 3600))}{esc(dup)}: {esc(items)}. "
            f"Muse/sync daemon no está consumiendo el inbox; nada de esto está aplicado todavía.</div>",
            unsafe_allow_html=True)
    hb = HEALTH["heartbeat_h"]
    if hb > HEARTBEAT_STALE_H:
        st.caption(f"Sin actividad registrada de Muse · último heartbeat hace {human_age(hb)}"
                   + (f" · última tarea: {ms.get('current_task')}" if ms.get("current_task") else ""))


# ───────────────────────── Muse yes/no blocker ─────────────────────────
ms_blocked = ms.get("status") == "BLOCKED_ON_ELVIN"
q = str(ms.get("needs_decision") or "").strip()
q_key = f"{q}|{ms.get('question_id', '')}"
# An asset approval (or publish authorization) is only valid as a job/version decision.
# A free-form yes/no is not bound to an asset, version, supervisor verdict or sha.
q_is_asset_approval = bool(ms.get("asset")) or bool(ASSET_APPROVAL_RE.search(q))
if not ms_blocked:
    st.session_state.answered_q = None
if ms_blocked and q and q_is_asset_approval:
    st.markdown(
        "<div class='review red'><b>Aprobación fuera del flujo bloqueada</b> · Muse pide aprobar un asset por "
        "pregunta libre, sin job/versión ni veredicto del supervisor. Debe registrarlo en jobs/ y pasar por el "
        f"supervisor; la decisión se toma aquí sobre la versión. Pregunta: {esc(q[:300])}</div>",
        unsafe_allow_html=True)
elif ms_blocked and q and st.session_state.answered_q != q_key:
    if MS_JOB and MS_JOB != jid:
        st.caption(f"Pregunta de Muse sobre el job {MS_JOB}")
    st.warning(q)
    y, n = st.columns(2)

    def _send_answer(answer):
        ok, d = gh_put_json("progress/elvin_answer.json", {"question": q, "answer": answer, "timestamp": now_iso()},
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
def send_decision(action, note=""):
    k = vkey(sel)
    if inflight_for(sel):
        st.info("Ya hay una decisión esperando confirmación del backend.")
        return
    if is_decided(sel) or not is_reviewable(sel):
        st.warning("Esta versión ya no está disponible para decisión.")
        return
    # Fresh (uncached) checks against the bus before writing anything.
    fresh_files = _dir(f"jobs/{jid}/versions/{sel}")
    if fresh_files is None:
        st.error("No se pudo verificar el estado de la versión en GitHub. Reintenta.")
        return
    if "decision_elvin.json" in fresh_files:
        clear_bus_cache()
        st.warning("Esta versión ya tiene una decisión de Elvin registrada.")
        st.rerun()
    # Bind the decision to the exact asset blob Elvin is looking at.
    shown_typ, shown = asset_info(sel)
    fresh_asset = next((fresh_files.get(f"asset.{e}") for e in ("mp4", "png", "jpg", "jpeg") if fresh_files.get(f"asset.{e}")), None)
    if not shown or not fresh_asset:
        st.error("Esta versión no tiene asset sincronizado; no se puede decidir sobre ella.")
        return
    if shown.get("sha") != fresh_asset.get("sha"):
        clear_bus_cache()
        st.warning("El asset de esta versión cambió desde que lo abriste. Revísalo de nuevo antes de decidir.")
        st.rerun()
    rec, ok = inbox_decision_for(sel, fresh=True)
    if not ok:
        st.error("No se pudo verificar el inbox de decisiones en GitHub. Reintenta.")
        return
    if rec:
        st.session_state.inflight[k] = rec
        set_notice("Ya existe una decisión para esta versión en el inbox · esperando ACK del backend…")
        st.rerun()
    asset_file = fresh_asset.get("path", "").rsplit("/", 1)[-1]
    # Deterministic id: the same job/version/asset/action always maps to the same inbox file,
    # so a double tap or a stale API read hits "already exists" instead of creating a duplicate.
    did = str(uuid.uuid5(DECISION_NS, f"{jid}|{sel}|{fresh_asset.get('sha')}|{action}"))
    obj = {"decision_id": did, "job_id": jid, "version": sel, "action": action, "timestamp": now_iso(),
           "note": note.strip(), "asset_file": asset_file, "asset_sha": fresh_asset.get("sha")}
    ok, d = gh_put_json(f"decisions/inbox/{did}.json", obj, f"decision {action} {jid} {sel}", create_only=True)
    already = not ok and d.startswith("HTTP 422")
    if already:
        # Already written (by this or another session): treat as sent, never write a second one.
        ok = True
    if ok:
        st.session_state.inflight[k] = {"decision_id": did, "job_id": jid, "version": sel, "action": action,
                                        "sent_at": time.time(), "ack_status": ""}
        if already:
            set_notice("Esta decisión ya estaba enviada · esperando ACK del backend…")
        else:
            st.session_state.notice = None   # the decision block already shows "Decisión enviada"
        st.session_state.change_open = False
        gh_dir.clear(); gh_tree.clear()
        st.rerun()
    else:
        st.error(f"No se pudo enviar: {d}")

def stage_data():
    """Returns ([(name, done)], active_idx|None, stopped_idx|None)."""
    s = state.get("state", "")
    has = bool(versions)
    generating = LIVE and s == "GENERATING"
    vd = verdict(cur) if cur else {}
    ve = cur_info.get("veredicto_efectivo", "")
    published = s in ("PUBLISHED", "DONE")
    stages = [("Brief", has or s == "GENERATING"),
              ("Generate", has and not generating),
              ("Muse QC", bool(vd)),
              ("Supervisor", ve in ("CORREGIR", "ESCALAR", "READY_FOR_ELVIN_REVIEW", "APROBADO")),
              ("Elvin", is_decided(cur)),
              ("Publish", published)]
    if published:
        return [(n, True) for n, _ in stages], None, None
    if generating:
        return stages, 1, None
    if CUR_PEND or CUR_INFLIGHT:
        return stages, 4, None
    if CUR_DECISION in ("reject", "request_changes"):
        return stages, None, 4
    if CUR_DECISION == "approve_final":
        return stages, 5, None
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

def qc_status(vd):
    """{cat: (True ok | False fail | None sin veredicto, detalle|None)}.
    Hands: the current bus has no hands pass/fail; anatomy_review.manos is a free-text
    finding, so it is shown as text. visual_coverage is kept only for legacy verdicts."""
    cov = as_dict(vd.get("visual_coverage"))
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


def status_badge(vn):
    """(label, tone) — readable status for a version."""
    act = decision_action(vn)
    if inflight_for(vn):
        return "Decision sent", "violet"
    if act:
        return DECISION_LABELS.get(act, "Decided by Elvin"), DECISION_TONE.get(act, "green")
    ve = vinfo(vn).get("veredicto_efectivo") or ""
    if ve in VERDICT_LABELS:
        return VERDICT_LABELS[ve]
    return (ve.replace("_", " ").capitalize() if ve else "—"), ""

def badge_html(vn):
    label, tone = status_badge(vn)
    return f"<span class='badge {tone}'>{esc(label)}</span>"

def pipeline_items_html():
    stages, active_idx, stopped_idx = stage_data()
    out = []
    for i, (name, done) in enumerate(stages):
        if i == stopped_idx:
            cls, sym = "stopped", DECISION_ICONS.get(CUR_DECISION, "✕")
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
            st.markdown(f"<div class='review warn'><b>Sin confirmación del backend</b> · {esc(act)} enviado hace {int(age // 60)} min{extra}. Revisa el sync daemon. Controles bloqueados para no duplicar.</div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div class='review'><b>Decisión enviada · {esc(act)}</b> · esperando confirmación del backend{extra}.</div>", unsafe_allow_html=True)
    elif is_decided(sel):
        act = decision_action(sel)
        st.markdown(f"<div class='review {DECISION_TONE.get(act, 'green')}'><b>{esc(DECISION_ICONS.get(act, '✓'))} {esc(DECISION_LABELS.get(act, 'Decided by Elvin'))}</b> · decisión registrada para {esc(sel)}.</div>", unsafe_allow_html=True)
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
            pipe, canvas, insp = st.columns([1.05, 6.8, 1.85], gap="small")
        else:
            pipe, canvas = st.columns([1.05, 8.65], gap="small")
            insp = None

        with pipe:
            with st.container(key="kv_pipe"):
                st.markdown(f"<div class='pipe-title'>Pipeline</div>{pipeline_items_html()}", unsafe_allow_html=True)
                with st.expander("Estado del job"):
                    st.caption(state.get("detail") or "Sin detalle")
                    st.caption(f"Actualizado: {human_age(AGE)}")

        with canvas:
            st.markdown(f"<div class='pipe-mini mobile-only'>{pipeline_items_html()}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='canvas-label'><span>LIVE CANVAS · <b>{esc(sel)}</b></span>{badge_html(sel)}</div>", unsafe_allow_html=True)
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

            # Mobile: QC before deciding (desktop shows it in the inspector column).
            st.markdown(f"<div class='mobile-only'>{inspector_html(sel, with_header=False, with_specs=False)}</div>", unsafe_allow_html=True)

            render_decision_block()

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
                    if st.button("Inspector ▸" if st.session_state.inspector else "◂ Inspector", key="tool_insp", width="stretch"):
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
            step = (MSTEP or state.get("detail") or "")[:120]
            st.markdown(f"<div class='livebar'><span class='dot{'' if LIVE else ' off'}'></span><b>{esc(LIVE_LBL)}</b><span>{esc(step)}</span></div>", unsafe_allow_html=True)

        if insp is not None:
            with insp:
                with st.container(key="kv_insp"):
                    st.markdown(f"<div class='pipe-title'>Inspector</div>{inspector_html(sel)}", unsafe_allow_html=True)

elif TAB == "Queue":
    st.subheader("Queue")
    st.caption(f"{jid} · {LIVE_LBL} · actualizado {human_age(AGE)}")
    render_notice()
    events = gh_json(f"jobs/{jid}/events.json", {})
    lines = as_list(events.get("lines")) if isinstance(events, dict) else []
    if lines:
        st.code("\n".join(str(x) for x in lines[-80:]))
    else:
        rows = []
        for v in versions:
            m = meta(v["version"])
            rows.append({"version": v["version"], "status": status_badge(v["version"])[0],
                         "registered": f"hace {human_age(hours_since(m.get('registered')))}" if m.get("registered") else "—", "model": as_dict(m.get("params")).get("model")})
        st.dataframe(rows, width="stretch", hide_index=True)

elif TAB == "Model":
    metrics = as_dict(gh_json("learning/metrics.json", {}))
    rules_l = as_list(gh_json("learning/rules.json", []))
    st.subheader("Model / Analytics")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Muse ↔ QA", f"{num(metrics.get('acuerdo_pct')):g}%")
    c2.metric("QA cost", f"${num(metrics.get('costo_supervisor_total_usd')):.4f}")
    c3.metric("Elvin caught", int(num(metrics.get("human_caught_miss"))))
    fp = num(metrics.get("falsos_positivos_muse")) + num(metrics.get("falsos_positivos_supervisor"))
    c4.metric("False positives", int(fp))
    st.caption(f"Phase: {metrics.get('fase', '—')} · Reviews: {metrics.get('revisiones_totales', 0)} · Learned rules: {metrics.get('reglas_aprendidas', 0)}")
    with st.expander("Reglas aprendidas"):
        active = [r for r in rules_l if isinstance(r, dict) and r.get("activa")]
        if not active:
            st.caption("Sin reglas activas sincronizadas.")
        for r in active:
            st.markdown(f"**{r.get('id', '—')}** — {r.get('regla', '')}")

st.markdown(f"<div class='kv-foot'>Mission Control {APP_VERSION}</div>", unsafe_allow_html=True)
