"""Kaia Vale Control Center — AI Operations UI (rediseño v3 2026-10-12).

Estética inspirada en apps de generación IA (PrimeIA/Higgsfield):
visual-primero, galería de versiones, barra de decisión fija, navegación
móvil nativa, responsive PC/móvil.

SOLO frontend/UX. No toca reviewer-loop, sincronización, decisiones,
seguridad ni lógica existente.

Secretos (Streamlit Cloud -> Settings -> Secrets, NUNCA en el código):
  DASHBOARD_PASSWORD, GITHUB_TOKEN, SYNC_REPO
"""
import base64
import json
import time
import uuid
from datetime import datetime

import requests
import streamlit as st

st.set_page_config(page_title="Kaia Vale · Ops Center", layout="wide",
                   initial_sidebar_state="collapsed")

# ---------------- secretos ----------------
try:
    PASSWORD = st.secrets["DASHBOARD_PASSWORD"]
    TOKEN = st.secrets["GITHUB_TOKEN"]
    REPO = st.secrets["SYNC_REPO"]
except Exception:
    st.error("Faltan secretos: configura DASHBOARD_PASSWORD, GITHUB_TOKEN y SYNC_REPO en Settings → Secrets.")
    st.stop()

API = f"https://api.github.com/repos/{REPO}/contents"
H = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github.raw"}

# ---------------- estado de navegación ----------------
if "tab" not in st.session_state:
    st.session_state.tab = "home"
if "sel_ver" not in st.session_state:
    st.session_state.sel_ver = None
TAB = st.session_state.tab
if TAB not in ("home", "gallery", "activity", "learning"):
    TAB = "home"
    st.session_state.tab = "home"

# ---------------- CSS: app shell estilo IA ----------------
st.markdown("""<style>
:root{
  --bg:#07090d; --surface:#0e131b; --surface2:#141b26; --surface3:#1a2230;
  --border:rgba(255,255,255,.07); --border2:rgba(255,255,255,.12);
  --text:#eef1f7; --muted:#8b94a7; --faint:#5b6373;
  --accent:#d8a94e; --accent2:#f0c76a;
  --green:#4ade80; --red:#f87171; --amber:#fbbf24; --blue:#6aa8ff; --violet:#a78bfa;
  --r:16px; --r-sm:12px;
}
html,body,[data-testid="stAppViewContainer"]{background:var(--bg);color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,sans-serif;}
[data-testid="stHeader"],#MainMenu,footer{visibility:hidden;display:none;}
.block-container{padding-top:.6rem;padding-bottom:8rem;max-width:1280px;}
h1,h2,h3{color:var(--text)!important;letter-spacing:-.02em;}
.stCaption,small{color:var(--muted)!important;}
*:focus-visible{outline:2px solid var(--accent);outline-offset:2px;}

/* ===== top bar ===== */
.topbar{position:sticky;top:0;z-index:900;display:flex;align-items:center;gap:10px;
  padding:10px 4px;margin:-.6rem -1rem .8rem;
  background:rgba(7,9,13,.88);backdrop-filter:blur(14px);
  border-bottom:1px solid var(--border);}
.topbar .logo{font-weight:800;font-size:1rem;letter-spacing:.06em;
  background:linear-gradient(120deg,var(--accent2),var(--accent));
  -webkit-background-clip:text;background-clip:text;color:transparent;white-space:nowrap;}
.topbar .spacer{flex:1;}

/* ===== pills & badges ===== */
.pill{display:inline-flex;align-items:center;gap:7px;padding:6px 13px;border-radius:999px;
  font-size:.76rem;font-weight:700;letter-spacing:.05em;border:1px solid var(--border2);
  background:var(--surface2);white-space:nowrap;}
.pill .dot{width:8px;height:8px;border-radius:50%;background:currentColor;}
.p-green{color:var(--green);border-color:rgba(74,222,128,.35);background:rgba(74,222,128,.1);}
.p-amber{color:var(--amber);border-color:rgba(251,191,36,.35);background:rgba(251,191,36,.1);}
.p-red{color:var(--red);border-color:rgba(248,113,113,.35);background:rgba(248,113,113,.1);}
.p-blue{color:var(--blue);border-color:rgba(106,168,255,.35);background:rgba(106,168,255,.1);}
.p-gold{color:var(--accent);border-color:rgba(216,169,78,.4);background:rgba(216,169,78,.12);}
.p-gray{color:var(--muted);}
.p-violet{color:var(--violet);border-color:rgba(167,139,250,.35);background:rgba(167,139,250,.1);}
.pulse-dot{animation:pdot 1.6s ease-in-out infinite;}
@keyframes pdot{0%,100%{opacity:.4;transform:scale(.85);}50%{opacity:1;transform:scale(1.1);}}

/* ===== hero ===== */
.hero{position:relative;overflow:hidden;border-radius:20px;padding:22px;
  background:linear-gradient(135deg,#151c28 0%,#0e1420 55%,#141019 100%);
  border:1px solid var(--border2);margin-bottom:14px;}
.hero:before{content:"";position:absolute;inset:0;pointer-events:none;
  background:radial-gradient(600px 200px at 85% -20%,rgba(216,169,78,.16),transparent 60%);}
.hero h2{margin:0 0 4px;font-size:1.5rem;}
.hero .sub{color:var(--muted);font-size:.88rem;margin-bottom:12px;}

/* ===== cards ===== */
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);
  padding:16px;margin-bottom:12px;}
.card h4{margin:0 0 10px;font-size:.76rem;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);}
.card.tappable{cursor:pointer;transition:transform .15s ease,border-color .15s ease;}
.card.tappable:hover{border-color:var(--accent);transform:translateY(-1px);}
.kv-big{font-size:1.7rem;font-weight:800;letter-spacing:-.02em;line-height:1.15;}
.kv-muted{color:var(--muted);font-size:.84rem;}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px;}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;}
@media(max-width:640px){.grid3{grid-template-columns:1fr 1fr;}.kv-big{font-size:1.4rem;}}

/* ===== pipeline stepper ===== */
.stepper{display:flex;align-items:center;gap:0;overflow-x:auto;padding:8px 2px;margin:4px 0;}
.snode{flex:0 0 auto;min-width:96px;text-align:center;padding:10px 8px;border-radius:14px;
  background:var(--surface2);border:1px solid var(--border);position:relative;}
.snode .t{font-size:.7rem;font-weight:800;letter-spacing:.07em;}
.snode .s{font-size:.64rem;color:var(--muted);margin-top:3px;}
.snode.on{border-color:var(--accent);background:rgba(216,169,78,.1);}
.snode.on .t{color:var(--accent);}
.snode.done{border-color:rgba(74,222,128,.35);}
.snode.done .t{color:var(--green);}
.slink{flex:0 0 22px;height:2px;background:var(--border);}
.slink.on{background:var(--accent);}

/* ===== gallery ===== */
[data-testid="stImage"] img{border-radius:14px;}
.gal-head{display:flex;align-items:baseline;gap:10px;margin:2px 0 12px;}
.gcap{display:flex;align-items:center;gap:8px;margin:6px 0 2px;}
.gcap .gver{font-weight:800;font-size:.9rem;}

/* ===== detail hero image ===== */
.dhero{border-radius:18px;overflow:hidden;border:1px solid var(--border2);margin-bottom:12px;
  background:var(--surface2);}
.dhero img{width:100%;display:block;max-height:62vh;object-fit:contain;background:#000;}
.spec{display:grid;grid-template-columns:1fr 1fr;gap:10px 14px;}
.spec .k{font-size:.68rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);}
.spec .v{font-weight:700;font-size:.92rem;margin-top:2px;}

/* ===== timeline ===== */
.tl{position:relative;padding-left:20px;}
.tl:before{content:"";position:absolute;left:6px;top:8px;bottom:8px;width:2px;background:var(--border);}
.tl-ev{position:relative;padding:8px 0 8px 6px;}
.tl-ev:before{content:"";position:absolute;left:-18px;top:14px;width:9px;height:9px;border-radius:50%;
  background:var(--surface3);border:2px solid var(--muted);}
.tl-ev.g:before{border-color:var(--green);} .tl-ev.a:before{border-color:var(--amber);}
.tl-ev.r:before{border-color:var(--red);} .tl-ev.b:before{border-color:var(--blue);}
.tl-time{font-size:.7rem;color:var(--faint);font-variant-numeric:tabular-nums;}
.tl-txt{font-size:.88rem;}

/* ===== bottom nav (mobile) / top nav (desktop) ===== */
.mnav{display:none;}
@media(max-width:767px){
  .mnav{display:flex;position:fixed;bottom:0;left:0;right:0;z-index:950;
    background:rgba(10,13,19,.96);backdrop-filter:blur(14px);
    border-top:1px solid var(--border2);
    padding:6px 4px calc(8px + env(safe-area-inset-bottom));}
  .mnav button{flex:1;background:none;border:none;color:var(--muted);font-size:.62rem;font-weight:700;
    display:flex;flex-direction:column;align-items:center;gap:3px;padding:8px 0;border-radius:10px;}
  .mnav button .ic{font-size:1.25rem;line-height:1;}
  .mnav button.on{color:var(--accent);}
  .dnav{display:none;}
}
@media(min-width:768px){
  .dnav{display:flex;gap:6px;margin-bottom:14px;}
  .dnav button{background:var(--surface2);border:1px solid var(--border);color:var(--muted);
    border-radius:999px;padding:9px 20px;font-weight:700;font-size:.85rem;}
  .dnav button.on{background:rgba(216,169,78,.14);color:var(--accent);border-color:rgba(216,169,78,.5);}
}

/* ===== tarjeta de decisión ===== */
.decide-card{background:linear-gradient(135deg,rgba(216,169,78,.14),rgba(216,169,78,.04));
  border:1px solid rgba(216,169,78,.5);border-radius:18px;padding:18px;margin:14px 0;
  text-align:center;}
.decide-card .ttl{font-weight:800;font-size:1.05rem;letter-spacing:.05em;color:var(--accent);}

/* ===== buttons ===== */
.stButton>button{background:var(--surface3);color:var(--text);border:1px solid var(--border2);
  border-radius:14px;min-height:52px;font-weight:700;font-size:.95rem;width:100%;
  transition:transform .1s ease,border-color .15s ease;}
.stButton>button:hover{border-color:var(--accent);color:var(--accent);}
.stButton>button:active{transform:scale(.98);}
.stButton>button[kind="primary"]{background:linear-gradient(135deg,var(--accent2),var(--accent));
  color:#14100a;border:none;}
.stButton>button[kind="primary"]:hover{filter:brightness(1.08);color:#14100a;}
.btn-green>button{background:rgba(74,222,128,.14)!important;color:var(--green)!important;
  border-color:rgba(74,222,128,.4)!important;}
.btn-red>button{background:rgba(248,113,113,.1)!important;color:var(--red)!important;
  border-color:rgba(248,113,113,.35)!important;}
.stTextInput>div>div>input,.stTextArea textarea{background:var(--surface2);color:var(--text);
  border:1px solid var(--border2);border-radius:12px;font-size:.95rem;}
.stExpander{border:1px solid var(--border);border-radius:14px;background:var(--surface);}
.stExpander summary{color:var(--text);font-weight:600;}
[data-testid="stMetric"]{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:14px;}
code{color:var(--accent)!important;font-size:.8em;}

/* gallery buttons invisibles (cards clicables) */
.gbtn>button{background:none!important;border:none!important;min-height:0!important;
  padding:0!important;width:100%;}
.gbtn>button:hover{border:none!important;}

/* login */
.login-wrap{max-width:380px;margin:10vh auto;padding:34px 30px;background:var(--surface);
  border:1px solid var(--border2);border-radius:22px;text-align:center;}
.login-wrap h1{font-size:1.35rem;margin-bottom:4px;
  background:linear-gradient(120deg,var(--accent2),var(--accent));
  -webkit-background-clip:text;background-clip:text;color:transparent;}
</style>""", unsafe_allow_html=True)

# ---------------- github helpers ----------------
@st.cache_data(ttl=20)
def gh_raw(path: str) -> bytes | None:
    r = requests.get(f"{API}/{path}?ref=main", headers=H, timeout=20)
    return r.content if r.status_code == 200 else None


@st.cache_data(ttl=20)
def gh_status(path: str) -> int:
    try:
        r = requests.get(f"{API}/{path}?ref=main", headers=H, timeout=20)
        return r.status_code
    except Exception:
        return -1


def gh_json(path: str):
    b = gh_raw(path)
    return json.loads(b.decode()) if b else None


def gh_put_json(path: str, obj: dict, msg: str) -> tuple[bool, str]:
    """Escribe JSON al repo. Devuelve (ok, detalle con HTTP real)."""
    content = base64.b64encode(json.dumps(obj, ensure_ascii=False, indent=1).encode()).decode()
    body = {"message": msg, "content": content}
    try:
        existing = gh_json_raw(path)
        if existing and existing.get("sha"):
            body["sha"] = existing["sha"]
    except Exception:
        pass
    try:
        r = requests.put(f"{API}/{path}", headers={**H, "Accept": "application/vnd.github+json"},
                         json=body, timeout=20)
    except Exception as e:
        return (False, f"sin conexión: {e.__class__.__name__}")
    if r.status_code in (200, 201):
        return (True, f"HTTP {r.status_code}")
    try:
        detail = r.json().get("message", "")[:160]
    except Exception:
        detail = r.text[:160]
    hint = {401: "token inválido o expirado — revisar GITHUB_TOKEN en Secrets",
            403: "token sin permiso de escritura — necesita 'Contents: write'",
            404: "repo o ruta no encontrada — revisar SYNC_REPO"}.get(r.status_code, "")
    return (False, f"GitHub HTTP {r.status_code}: {detail} {hint}".strip())


def gh_json_raw(path: str):
    r = requests.get(f"{API}/{path}", headers=H, timeout=20)
    return r.json() if r.status_code == 200 else None


# ---------------- auth gate ----------------
if "auth" not in st.session_state:
    st.session_state.auth = False
if not st.session_state.auth:
    st.markdown('<div class="login-wrap"><h1>◈ KAIA VALE</h1>'
                '<p class="kv-muted">Operations Control Center</p>', unsafe_allow_html=True)
    with st.form("login"):
        pw = st.text_input("Password", type="password", label_visibility="collapsed",
                           placeholder="Password")
        submitted = st.form_submit_button("Entrar")
    st.markdown('</div>', unsafe_allow_html=True)
    if submitted:
        if pw == PASSWORD:
            st.session_state.auth = True
            st.rerun()
        else:
            st.error("Password incorrecto.")
    st.stop()

# ---------------- datos ----------------
snap = gh_json("snapshot.json") or {"jobs": []}
agent = gh_json("agent.json") or {}
budget = gh_json("budget.json") or {}
jobs = snap.get("jobs", [])
if not jobs:
    st.markdown('<div class="card">Sin jobs sincronizados todavía.</div>', unsafe_allow_html=True)
    code = gh_status("snapshot.json")
    st.warning(f"Diagnóstico GitHub API: HTTP {code} — 401=token inválido o sin acceso al repo, "
               f"404=SYNC_REPO mal escrito o repo sin contenido, -1=sin conexión.")
    st.stop()

job_ids = [j["job_id"] for j in jobs]
jid = job_ids[0] if len(job_ids) == 1 else st.selectbox("Job", job_ids)
job = next(j for j in jobs if j["job_id"] == jid)
versions = job.get("versions", [])
cur = versions[-1]["version"] if versions else None
state = gh_json(f"jobs/{jid}/state.json") or {}
metrics = gh_json("learning/metrics.json") or {}
phase = gh_json("learning/phase.json") or {}
rules_l = gh_json("learning/rules.json") or []
disag = gh_json("learning/disagreements.json") or []
ms = gh_json("progress/muse_status.json") or {}


def _decision_pending() -> bool:
    curinfo = next((x for x in versions if x["version"] == cur), {})
    return (curinfo.get("veredicto_efectivo") == "READY_FOR_ELVIN_REVIEW"
            and not curinfo.get("decidido"))


def hours_since(iso) -> float:
    try:
        from datetime import timezone
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except Exception:
        return 999.0


def hace_str(h: float) -> str:
    if h >= 999:
        return "fecha desconocida"
    if h < 1:
        m = int(h * 60)
        return f"hace {m} min" if m > 0 else "ahora mismo"
    if h < 24:
        return f"hace {int(h)} h"
    return f"hace {int(h / 24)} d"


def fmt_ts(iso):
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return dt.strftime("%H:%M")
    except Exception:
        return "—"


STATE_AGE_H = hours_since(state.get("updated"))
IS_LIVE = STATE_AGE_H < 0.25


def global_status():
    s = state.get("state", "")
    if s == "APPROVED":
        return ("APPROVED", "p-green", True)
    if _decision_pending() or s == "ELVIN_DECISION_REQUIRED":
        return ("WAITING FOR ELVIN", "p-amber", True)
    if not IS_LIVE:
        return ("IDLE", "p-gray", False)
    if s in ("GENERATING", "CORRECTING"):
        return ("PRODUCING", "p-green", True)
    if s in ("REVIEWING", "VALIDATING", "ESCALATED_INTERNAL"):
        return ("REVIEWING", "p-blue", True)
    return ("IDLE", "p-gray", False)


def send_decision(action: str, note: str) -> None:
    did = str(uuid.uuid4())
    dec = {"decision_id": did, "job_id": jid, "version": cur,
           "action": action, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "note": note.strip()}
    ok, detail = gh_put_json(f"decisions/inbox/{did}.json", dec, f"decision {action} {jid} {cur}")
    if ok:
        st.success("✅ Decisión enviada. El ACK aparecerá aquí en ~1 min.")
        st.caption(f"ID: `{did}`")
    else:
        st.error(f"No se pudo enviar. {detail}")


def media_for(vn):
    vinfo = next((x for x in versions if x["version"] == vn), {})
    mp4 = gh_raw(f"jobs/{jid}/versions/{vn}/asset.mp4")
    if mp4:
        return ("video", mp4)
    png = gh_raw(f"jobs/{jid}/versions/{vn}/asset.png")
    return ("image", png) if png else (None, None)


def verdict_meta(v):
    m = {"READY_FOR_ELVIN_REVIEW": ("READY", "p-gold"),
         "CORREGIR": ("CORREGIR", "p-red"), "ESCALAR": ("ESCALAR", "p-amber"),
         "APROBADO": ("APROBADO", "p-green"), "ESCALATED_INTERNAL": ("EN REVISIÓN", "p-blue")}
    return m.get(v, (v or "—", "p-gray"))


def build_events():
    evs = []
    for v in versions:
        m = gh_json(f"jobs/{jid}/versions/{v['version']}/meta.json") or {}
        if m.get("registered"):
            evs.append((m["registered"], "g", f"◈ {v['version']} registrada"))
    for d in disag:
        if d.get("job_id") == jid and d.get("ts"):
            cl = d.get("clase", "")
            txt = {"missed_by_muse": f"Supervisor CORREGIR {d.get('version')}",
                   "acuerdo": f"Supervisor PASS {d.get('version')}",
                   "supervisor_false_positive": f"Supervisor marcó · Muse discrepa {d.get('version')}",
                   "human_caught_miss": f"Elvin detectó fallo en {d.get('version')}",
                   "human_calibration_positive": f"Elvin aprobó {d.get('version')}",
                   "user_overrule": f"Elvin decidió sobre {d.get('version')}"}.get(cl, f"{cl} {d.get('version')}")
            kc = "r" if cl in ("missed_by_muse", "human_caught_miss") else ("g" if cl == "acuerdo" else "a")
            evs.append((d["ts"], kc, txt))
    try:
        listing = requests.get(f"{API}/decisions/inbox?ref=main", headers=H, timeout=20).json()
        if isinstance(listing, list):
            for f in listing:
                d = gh_json(f"decisions/inbox/{f['name']}")
                if d and d.get("timestamp") and d.get("job_id") == jid:
                    evs.append((d["timestamp"], "a", f"Elvin: {d.get('action')} {d.get('version')}"))
    except Exception:
        pass
    evs.sort(key=lambda x: x[0])
    return evs


pending = _decision_pending()
glabel, gpill, gactive = global_status()

# ---------------- top bar ----------------
st.markdown(f"""<div class="topbar">
  <div class="logo">◈ KAIA VALE</div>
  <div class="spacer"></div>
  <span class="pill {gpill}"><span class="dot{' pulse-dot' if gactive else ''}"></span>{glabel}</span>
  </div>""", unsafe_allow_html=True)

# Banner BLOCKED_ON_ELVIN (siempre visible arriba)
_ms = ms
if _ms.get("status") == "BLOCKED_ON_ELVIN" and _ms.get("needs_decision"):
    _q = _ms.get("needs_decision", "")
    st.markdown(f"""<div class="card" style="border-color:rgba(251,191,36,.5);margin-bottom:0">
      <h4 style="color:var(--amber)">⚠ Muse necesita tu decisión</h4>
      <div style="font-weight:700">{_q[:280]}</div></div>""", unsafe_allow_html=True)
    _ap = _ms.get("asset")
    if _ap:
        _ad = gh_raw(_ap)
        if _ad:
            st.image(_ad, use_container_width=True)
    _b1, _b2 = st.columns(2)
    if _b1.button("✅ SÍ", key="elvin_yes", type="primary", use_container_width=True):
        _ans = {"question": _q, "answer": "yes",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        _ok, _d = gh_put_json("progress/elvin_answer.json", _ans, "elvin answer: yes")
        st.success("✅ Enviada: SÍ.") if _ok else st.error(f"No se pudo enviar. {_d}")
    if _b2.button("❌ NO", key="elvin_no", use_container_width=True):
        _ans = {"question": _q, "answer": "no",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        _ok, _d = gh_put_json("progress/elvin_answer.json", _ans, "elvin answer: no")
        st.success("Enviada: NO.") if _ok else st.error(f"No se pudo enviar. {_d}")

# ---------------- navegación ----------------
NAV = [("home", "⌂", "Home"), ("gallery", "▦", "Galería"),
       ("activity", "≋", "Actividad"), ("learning", "✦", "Aprendizaje")]
# desktop
st.markdown('<div class="dnav">', unsafe_allow_html=True)
_dc = st.columns(4)
for i, (t, ic, label) in enumerate(NAV):
    if _dc[i].button(f"{ic} {label}", key=f"dnav_{t}", use_container_width=True,
                      type="primary" if TAB == t else "secondary"):
        st.session_state.tab = t
        st.session_state.sel_ver = None
        st.rerun()
st.markdown('</div>', unsafe_allow_html=True)
# mobile: bottom nav con botones streamlit
st.markdown('<div class="mnav">', unsafe_allow_html=True)
_mc = st.columns(4)
for i, (t, ic, label) in enumerate(NAV):
    lbl = f"{ic}\n{label}"
    if _mc[i].button(lbl, key=f"mnav_{t}", use_container_width=True,
                      type="primary" if TAB == t else "secondary"):
        st.session_state.tab = t
        st.session_state.sel_ver = None
        st.rerun()
st.markdown('</div>', unsafe_allow_html=True)

# ================= HOME =================
if TAB == "home":
    st.markdown(f"""<div class="hero">
      <h2>{jid}</h2>
      <div class="sub">Última actividad {hace_str(STATE_AGE_H)} · sync ~60s</div>
      <span class="pill {gpill}"><span class="dot{' pulse-dot' if gactive else ''}"></span>{glabel}</span>
      </div>""", unsafe_allow_html=True)

    # Muse status compacto
    mstatus = ms.get("status", "—")
    mh = hours_since(ms.get("last_heartbeat")) if ms.get("last_heartbeat") else 999.0
    stale = mstatus not in ("COMPLETED", "FAILED", "—") and mh * 60 > 10
    mpill = "p-red" if stale else {"WORKING": "p-green", "WAITING_ON_TOOL": "p-amber",
        "BLOCKED": "p-red", "COMPLETED": "p-gray", "FAILED": "p-red"}.get(mstatus, "p-gray")
    st.markdown(f"""<div class="card"><h4>🤖 Muse</h4>
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
      <span class="pill {mpill}">{'STALLED?' if stale else mstatus}</span>
      <span class="kv-muted">heartbeat {hace_str(mh)}</span></div>
      <div class="kv-muted">{(ms.get('current_step') or '—')[:100]}</div></div>""",
                unsafe_allow_html=True)

    # Pipeline stepper
    nodes = [("MUSE", "agent"), ("GEN", "krea 2"), ("QC", "local"),
             ("SUP", "gpt"), ("FIX", "krea 2"), ("READY", "elvin")]
    active_idx = {"PRODUCING": 1, "REVIEWING": 3, "WAITING FOR ELVIN": 5}.get(glabel, -1)
    curinfo = next((x for x in versions if x["version"] == cur), {})
    if glabel == "PRODUCING" and curinfo.get("veredicto_efectivo") == "CORREGIR":
        active_idx = 4
    all_done = glabel.startswith("APPROVED")
    sp = '<div class="card"><h4>Pipeline</h4><div class="stepper">'
    for i, (n, s) in enumerate(nodes):
        cls = "on" if i == active_idx else ("done" if (0 <= active_idx and i < active_idx) or all_done else "")
        sp += f'<div class="snode {cls}"><div class="t">{n}</div><div class="s">{s}</div></div>'
        if i < len(nodes) - 1:
            sp += f'<div class="slink {"on" if 0 <= active_idx and i < active_idx else ""}"></div>'
    st.markdown(sp + "</div></div>", unsafe_allow_html=True)

    # Stats rápidas
    caps = budget.get("caps_usd", {})
    used = budget.get("monthly_used_usd", 0)
    st.markdown(f"""<div class="grid3">
      <div class="card"><h4>Supervisor</h4><div class="kv-big">${used:.4f}</div>
        <div class="kv-muted">de ${caps.get("monthly", "?")}</div></div>
      <div class="card"><h4>Versiones</h4><div class="kv-big">{len(versions)}</div>
        <div class="kv-muted">en este job</div></div>
      <div class="card"><h4>Acuerdo</h4><div class="kv-big">{metrics.get("acuerdo_pct", "?")}%</div>
        <div class="kv-muted">Muse ↔ Supervisor</div></div>
      </div>""", unsafe_allow_html=True)

    # Actividad reciente
    evs = build_events()
    tl = '<div class="card"><h4>Actividad reciente</h4><div class="tl">'
    for ts, kc, txt in evs[-4:]:
        tl += (f'<div class="tl-ev {kc}"><span class="tl-time">{fmt_ts(ts)}</span> '
               f'<span class="tl-txt">{txt}</span></div>')
    tl += "</div></div>"
    st.markdown(tl, unsafe_allow_html=True)
    if pending:
        st.markdown('<div class="decide-card"><div class="ttl">◈ TU DECISIÓN</div>'
                    f'<div class="kv-muted" style="margin-bottom:10px">{cur} está lista</div></div>',
                    unsafe_allow_html=True)
        # asset + resumen compacto
        mtype, mdata = media_for(cur)
        if mdata and mtype == "image":
            st.image(mdata, use_container_width=True)
        elif mdata:
            st.video(mdata)
        vd_cur = gh_json(f"jobs/{jid}/versions/{cur}/verdict.json") or {}
        halls_cur = vd_cur.get("hallazgos", [])
        if halls_cur:
            for h in halls_cur[:3]:
                st.markdown(f"• **{h.get('categoria','')}**: {h.get('descripcion','')[:120]}")
        else:
            st.markdown("<div class='kv-muted'>Sin hallazgos bloqueantes. Lista para publicar.</div>",
                        unsafe_allow_html=True)
        with st.expander("✏️ Instrucciones (solo si pides cambios)"):
            st.text_input("Instrucciones", key=f"dc_note_{jid}_{cur}",
                          label_visibility="collapsed", placeholder="Describe los cambios…")
        b1, b2, b3 = st.columns(3)
        if b1.button("✅ APROBAR", key=f"dc_ap_{jid}_{cur}", type="primary", use_container_width=True):
            send_decision("approve_final", "")
        if b2.button("🔄 CAMBIOS", key=f"dc_rc_{jid}_{cur}", use_container_width=True):
            nn = st.session_state.get(f"dc_note_{jid}_{cur}", "")
            if not nn.strip():
                st.error("Escribe las instrucciones primero.")
            else:
                send_decision("request_changes", nn)
        if b3.button("❌ RECHAZAR", key=f"dc_rj_{jid}_{cur}", use_container_width=True):
            send_decision("reject", "")
    elif state.get("state") == "ELVIN_DECISION_REQUIRED":
        st.error("⛔ Requiere tu decisión: el sistema no pudo resolverlo. Revisa la pestaña Galería.")

# ================= GALLERY =================
elif TAB == "gallery":
    sel = st.session_state.sel_ver
    if sel and any(v["version"] == sel for v in versions):
        # ---- vista detalle ----
        if st.button("← Galería", key="back_gal"):
            st.session_state.sel_ver = None
            st.rerun()
        vinfo = next(x for x in versions if x["version"] == sel)
        meta = gh_json(f"jobs/{jid}/versions/{sel}/meta.json") or {}
        vd = gh_json(f"jobs/{jid}/versions/{sel}/verdict.json") or {}
        dec = gh_json(f"jobs/{jid}/versions/{sel}/decision.json") or {}
        audit = gh_json(f"jobs/{jid}/versions/{sel}/audit.json") or {}
        dec_elvin = gh_json(f"jobs/{jid}/versions/{sel}/decision_elvin.json") if vinfo.get("decidido") else None
        if dec_elvin:
            lbl = {"approve_final": "APROBADA", "reject": "RECHAZADA",
                   "request_changes": "CAMBIOS PEDIDOS"}.get(dec_elvin.get("decision"), "DECIDIDA")
            lbadge = {"approve_final": "p-green", "reject": "p-red",
                      "request_changes": "p-amber"}.get(dec_elvin.get("decision"), "p-gray")
        else:
            lbl, lbadge = verdict_meta(vinfo.get("veredicto_efectivo"))
        mtype, mdata = media_for(sel)
        st.markdown(f"""<div style="display:flex;align-items:center;gap:10px;margin:4px 0 12px">
          <div class="kv-big" style="font-size:1.3rem">{sel}</div>
          <span class="pill {lbadge}">{lbl}</span></div>""", unsafe_allow_html=True)
        if mdata and mtype == "image":
            st.image(mdata, use_container_width=True)
        elif mdata:
            st.video(mdata)
        else:
            st.info("Asset aún no sincronizado.")
        params = meta.get("params", {})
        halls = vd.get("hallazgos", [])
        cov = vd.get("visual_coverage") or {}
        npass = sum(1 for c in cov.values() if isinstance(c, dict)
                    for v2 in c.values() if isinstance(v2, dict) and v2.get("estado") == "PASS")
        nfail = sum(1 for c in cov.values() if isinstance(c, dict)
                    for v2 in c.values() if isinstance(v2, dict) and v2.get("estado") == "FAIL")
        cost = dec.get("costo_usd_estimado", "—")
        st.markdown(f"""<div class="card"><h4>Detalles</h4><div class="spec">
          <div><div class="k">Modelo</div><div class="v">{params.get("model", "—")}</div></div>
          <div><div class="k">Resolución</div><div class="v">{(audit.get("asset_original", {}) or {}).get("resolucion", "—")}</div></div>
          <div><div class="k">Confidence</div><div class="v">{vd.get("confianza", "—")}</div></div>
          <div><div class="k">Costo</div><div class="v">{f"${cost:.4f}" if isinstance(cost, (int, float)) else cost}</div></div>
          <div><div class="k">Defectos</div><div class="v">{len(halls)}</div></div>
          <div><div class="k">Coverage</div><div class="v">{f"{npass}✓ {nfail}✗" if cov else "—"}</div></div>
          </div></div>""", unsafe_allow_html=True)
        if halls:
            hh = '<div class="card"><h4>Hallazgos</h4>'
            for h in halls:
                hh += f"<div style='margin-bottom:8px'>• <b>{h.get('categoria','')}</b> <span class='kv-muted'>({h.get('severidad','')})</span><br><span class='kv-muted'>{h.get('descripcion','')[:200]}</span></div>"
            st.markdown(hh + "</div>", unsafe_allow_html=True)
        rel = [d for d in disag if d.get("job_id") == jid and d.get("version") == sel]
        if rel:
            wh = '<div class="card"><h4>Quién lo detectó</h4>'
            qmap = {"missed_by_muse": "Supervisor lo detectó", "supervisor_false_positive": "Supervisor marcó · Muse discrepa",
                    "human_caught_miss": "Elvin lo detectó", "human_calibration_positive": "Elvin lo aprobó",
                    "acuerdo": "Muse y Supervisor de acuerdo"}
            for d in rel:
                wh += f"<div>• {qmap.get(d.get('clase'), d.get('clase'))}</div>"
                if d.get("nota"):
                    wh += f"<div class='kv-muted' style='font-size:.8rem'>{str(d['nota'])[:180]}</div>"
            st.markdown(wh + "</div>", unsafe_allow_html=True)
        if cov:
            with st.expander("Visual Coverage"):
                for cat, items in cov.items():
                    if not isinstance(items, dict):
                        continue
                    fails = [k for k, v2 in items.items()
                             if isinstance(v2, dict) and v2.get("estado") == "FAIL"]
                    st.markdown(f"**{'❌' if fails else '✅'} {cat}**")
                    for k, v2 in items.items():
                        if isinstance(v2, dict):
                            st.caption(f"{'✅' if v2.get('estado')=='PASS' else '❌' if v2.get('estado')=='FAIL' else '▫'} {k}")
        tr = vd.get("temporal_review") or {}
        if tr:
            with st.expander("🎬 Video QC"):
                for cat, c in tr.items():
                    if isinstance(c, dict):
                        ic = {"PASS": "✅", "FAIL": "❌", "NOT_VERIFIABLE": "⚠️"}.get(c.get("estado"), "▫")
                        st.markdown(f"{ic} **{cat}** — {c.get('estado')}")
    else:
        # ---- grid de galería ----
        st.markdown(f"""<div class="gal-head">
          <div class="kv-big" style="font-size:1.25rem">Galería</div>
          <div class="kv-muted">{len(versions)} versiones · toca Ver para detalle</div></div>""",
                    unsafe_allow_html=True)
        cols = st.columns(2)
        for i, v in enumerate(reversed(versions)):
            vn = v["version"]
            lbl, lbadge = verdict_meta(v.get("veredicto_efectivo"))
            mtype, mdata = media_for(vn)
            with cols[i % 2]:
                if mdata and mtype == "image":
                    st.image(mdata, use_container_width=True)
                elif mdata:
                    st.markdown('<div class="card" style="text-align:center;padding:30px 10px">🎬<br><span class="kv-muted">video</span></div>', unsafe_allow_html=True)
                else:
                    st.markdown('<div class="card" style="text-align:center;padding:30px 10px"><span class="kv-muted">⏳ sin sincronizar</span></div>', unsafe_allow_html=True)
                st.markdown(f"""<div class="gcap"><span class="gver">{vn}</span>
                  <span class="pill {lbadge}" style="font-size:.66rem;padding:3px 9px">{lbl}</span></div>""",
                            unsafe_allow_html=True)
                if st.button("Ver detalle →", key=f"gopen_{vn}", use_container_width=True):
                    st.session_state.sel_ver = vn
                    st.rerun()
                st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

# ================= ACTIVITY =================
elif TAB == "activity":
    st.markdown(f"""<div class="card"><h4>Estado</h4>
      <span class="pill {gpill}"><span class="dot{' pulse-dot' if gactive else ''}"></span>{glabel}</span>
      <div class="kv-muted" style="margin-top:8px">Última actualización {hace_str(STATE_AGE_H)}</div></div>""",
                unsafe_allow_html=True)
    evs = build_events()
    tl = '<div class="card"><h4>Timeline</h4><div class="tl">'
    for ts, kc, txt in evs[-25:]:
        tl += (f'<div class="tl-ev {kc}"><span class="tl-time">{fmt_ts(ts)}</span> '
               f'<span class="tl-txt">{txt}</span></div>')
    st.markdown(tl + "</div></div>", unsafe_allow_html=True)
    ev = gh_json(f"jobs/{jid}/events.json") or {"lines": []}
    with st.expander("Log técnico"):
        st.code("\n".join(ev.get("lines", [])[-40:]))

# ================= LEARNING =================
elif TAB == "learning":
    fase = metrics.get("fase", phase.get("fase", "?"))
    st.markdown(f"""<div class="hero"><h2>{fase}</h2>
      <div class="sub">{"Supervisión total — el supervisor revisa todo." if fase == "FASE_1" else ""}</div></div>""",
                unsafe_allow_html=True)
    hcm = metrics.get("human_caught_miss", 0)
    fp = metrics.get("falsos_positivos_muse", 0) + metrics.get("falsos_positivos_supervisor", 0)
    st.markdown(f"""<div class="grid2">
      <div class="card"><h4>Acuerdo</h4><div class="kv-big">{metrics.get("acuerdo_pct", "?")}%</div>
        <div class="kv-muted">Muse ↔ Supervisor</div></div>
      <div class="card"><h4>Revisiones</h4><div class="kv-big">{metrics.get("revisiones_totales", 0)}</div>
        <div class="kv-muted">total registradas</div></div>
      <div class="card"><h4>Reglas</h4><div class="kv-big">{metrics.get("reglas_aprendidas", 0)}</div>
        <div class="kv-muted">aprendidas</div></div>
      <div class="card"><h4>Costo</h4><div class="kv-big">${metrics.get("costo_supervisor_total_usd", 0):.4f}</div>
        <div class="kv-muted">supervisor total</div></div>
      <div class="card" style="{"border-color:rgba(248,113,113,.4)" if hcm else ""}"><h4>Elvin caught</h4>
        <div class="kv-big" style="color:{"var(--red)" if hcm else "inherit"}">{hcm}</div>
        <div class="kv-muted">bloquea salida de FASE_1</div></div>
      <div class="card"><h4>Falsos +</h4><div class="kv-big">{fp}</div>
        <div class="kv-muted">Muse + Supervisor</div></div>
      </div>""", unsafe_allow_html=True)
    if disag:
        seq = sorted([d for d in disag if d.get("clase") in
                      ("acuerdo", "missed_by_muse", "supervisor_false_positive")],
                     key=lambda x: x.get("ts", ""))
        if seq:
            tot = agr = 0
            pts = []
            for d in seq:
                tot += 1
                if d["clase"] == "acuerdo":
                    agr += 1
                pts.append(round(100 * agr / tot))
            bars = "".join(
                f'<div style="flex:1;background:linear-gradient(180deg,var(--accent),rgba(216,169,78,.3));'
                f'border-radius:4px 4px 2px 2px;min-height:4px;height:{max(p,4)}%"></div>'
                for p in pts[-20:])
            st.markdown(f"""<div class="card"><h4>Evolución — acuerdo acumulado</h4>
              <div style="display:flex;align-items:flex-end;gap:5px;height:110px">{bars}</div>
              <div class="kv-muted" style="margin-top:8px">¿Muse está mejorando?</div></div>""",
                        unsafe_allow_html=True)
    n_sup = sum(1 for d in disag if d.get("clase") == "missed_by_muse")
    n_elv = sum(1 for d in disag if d.get("clase") == "human_caught_miss")
    n_muse = metrics.get("llamadas_evitadas", 0)
    st.markdown(f"""<div class="card"><h4>Quién lo detectó</h4><div class="grid3">
      <div><div class="kv-big" style="color:var(--green);font-size:1.4rem">{n_muse}</div><div class="kv-muted">Muse</div></div>
      <div><div class="kv-big" style="color:var(--blue);font-size:1.4rem">{n_sup}</div><div class="kv-muted">Supervisor</div></div>
      <div><div class="kv-big" style="color:var(--amber);font-size:1.4rem">{n_elv}</div><div class="kv-muted">Elvin</div></div>
      </div></div>""", unsafe_allow_html=True)
    with st.expander("Reglas aprendidas"):
        for r in rules_l:
            if r.get("activa"):
                st.markdown(f"**{r['id']}** — {r['regla'][:200]}")

# ---------------- decisión (tarjeta prominente al final del Home) ----------------
# Se renderiza dentro del tab Home cuando hay decisión pendiente.
# (Un overlay "sticky" real no es fiable en Streamlit: los divs no se anidan
# entre bloques. Esta tarjeta usa el CSS .decide-card y es 100% funcional.)

# ---------------- auto-refresh ----------------
st.caption("Actualización automática cada ~30s.")
time.sleep(30)
st.rerun()
