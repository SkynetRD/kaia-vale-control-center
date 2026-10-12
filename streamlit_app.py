"""Kaia Vale Control Center — AI Operations UI (rediseño 2026-10-12).

SOLO frontend/UX. No toca reviewer-loop, sincronización, decisiones,
seguridad ni lógica existente: usa los mismos datos y endpoints.

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

# ---------------- navegación (botones + session_state: los links <a href> recargaban
# la página y borraban la sesión -> mandaban al login) ----------------
if "tab" not in st.session_state:
    st.session_state.tab = "home"
TAB = st.session_state.tab
if TAB not in ("home", "asset", "activity", "learning"):
    TAB = "home"
    st.session_state.tab = "home"

# ---------------- CSS: dark premium ----------------
st.markdown("""<style>
:root{
  --bg:#0a0d12; --surface:#10151d; --surface2:#161c26;
  --border:rgba(255,255,255,.08); --text:#e9ecf3; --muted:#8b94a7;
  --accent:#d8a94e; --accent-dim:rgba(216,169,78,.14);
  --green:#4ade80; --red:#f87171; --amber:#fbbf24; --blue:#6aa8ff;
}
html,body,[data-testid="stAppViewContainer"]{background:var(--bg);color:var(--text);}
[data-testid="stHeader"],#MainMenu,footer{visibility:hidden;display:none;}
.block-container{padding-top:1rem;padding-bottom:6.5rem;max-width:1200px;}
h1,h2,h3{color:var(--text)!important;letter-spacing:-.01em;}
.stCaption,small{color:var(--muted)!important;}

/* cards */
.kv-card{background:var(--surface);border:1px solid var(--border);border-radius:14px;
  padding:16px 18px;margin-bottom:14px;}
.kv-card h4{margin:0 0 6px;font-size:.82rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);}
.kv-big{font-size:1.9rem;font-weight:700;line-height:1.1;}
.kv-muted{color:var(--muted);font-size:.85rem;}

/* badges */
.badge{display:inline-block;padding:4px 12px;border-radius:999px;font-size:.75rem;font-weight:600;
  letter-spacing:.04em;border:1px solid var(--border);}
.b-green{background:rgba(74,222,128,.12);color:var(--green);border-color:rgba(74,222,128,.3);}
.b-red{background:rgba(248,113,113,.12);color:var(--red);border-color:rgba(248,113,113,.3);}
.b-amber{background:rgba(251,191,36,.12);color:var(--amber);border-color:rgba(251,191,36,.3);}
.b-blue{background:rgba(106,168,255,.12);color:var(--blue);border-color:rgba(106,168,255,.3);}
.b-gray{background:rgba(139,148,167,.12);color:var(--muted);}
.b-gold{background:var(--accent-dim);color:var(--accent);border-color:rgba(216,169,78,.35);}

/* pipeline */
.pipe{display:flex;align-items:center;gap:0;margin:14px 0;overflow-x:auto;padding:6px 2px;}
.pnode{flex:0 0 auto;text-align:center;padding:10px 14px;border:1px solid var(--border);
  border-radius:12px;background:var(--surface);min-width:104px;position:relative;}
.pnode .t{font-size:.72rem;font-weight:700;letter-spacing:.06em;}
.pnode .s{font-size:.66rem;color:var(--muted);margin-top:2px;}
.pnode.active{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent),0 0 18px rgba(216,169,78,.25);}
.pnode.active .t{color:var(--accent);}
.pnode.done{border-color:rgba(74,222,128,.4);}
.pnode.done .t{color:var(--green);}
.plink{flex:0 0 26px;height:2px;background:var(--border);position:relative;}
.plink.on{background:var(--accent);}
.pulse{width:7px;height:7px;border-radius:50%;background:var(--accent);display:inline-block;margin-right:6px;
  animation:pulse 1.6s ease-in-out infinite;}
@keyframes pulse{0%,100%{opacity:.35;transform:scale(.9);}50%{opacity:1;transform:scale(1.15);}}

/* version timeline */
.vtl{display:flex;gap:8px;overflow-x:auto;padding:8px 2px;margin-bottom:6px;}
.vchip{flex:0 0 auto;padding:9px 16px;border-radius:12px;border:1px solid var(--border);
  background:var(--surface);color:var(--text);text-decoration:none;font-weight:600;font-size:.85rem;}
.vchip small{display:block;font-weight:400;color:var(--muted);font-size:.68rem;}
.vchip.sel{border-color:var(--accent);background:var(--accent-dim);color:var(--accent);}
a.vchip:hover{border-color:var(--accent);}

/* decision banner */
.decide-banner{background:linear-gradient(135deg,rgba(216,169,78,.16),rgba(216,169,78,.05));
  border:1px solid rgba(216,169,78,.5);border-radius:16px;padding:22px;margin-bottom:18px;text-align:center;}
.decide-banner h2{margin:0 0 6px;font-size:1.35rem;letter-spacing:.02em;}
.decide-btns .stButton>button{min-height:56px;font-weight:700;font-size:1rem;border-radius:12px;}

/* nav por botones (no recarga -> no cierra sesión) */
.nav-anchor + div[data-testid="stVerticalBlock"]{margin-bottom:14px;}
.nav-anchor + div[data-testid="stVerticalBlock"] button{
  background:var(--surface);border:1px solid var(--border);color:var(--muted);
  border-radius:999px;min-height:44px;font-weight:600;}
.nav-anchor + div[data-testid="stVerticalBlock"] button:hover{border-color:var(--accent);color:var(--accent);}
.nav-anchor + div[data-testid="stVerticalBlock"] button[kind="primary"]{
  background:var(--accent-dim);color:var(--accent);border-color:rgba(216,169,78,.5);}
@media (max-width:767px){
  .nav-anchor + div[data-testid="stVerticalBlock"]{
    position:fixed;bottom:0;left:0;right:0;z-index:999;margin-bottom:0;
    background:rgba(16,21,29,.96);backdrop-filter:blur(12px);
    border-top:1px solid var(--border);
    padding:8px 8px calc(10px + env(safe-area-inset-bottom));}
  .nav-anchor + div[data-testid="stVerticalBlock"] button{border-radius:12px;min-height:52px;}
  .block-container{padding-bottom:7.5rem;}
  .kv-big{font-size:1.5rem;}
}

/* activity steps */
.step{display:flex;gap:12px;align-items:flex-start;padding:10px 0;border-bottom:1px solid var(--border);}
.step:last-child{border-bottom:none;}
.sdot{flex:0 0 26px;height:26px;border-radius:50%;display:flex;align-items:center;justify-content:center;
  font-size:.8rem;border:1px solid var(--border);background:var(--surface2);color:var(--muted);}
.step.done .sdot{border-color:var(--green);color:var(--green);}
.step.active .sdot{border-color:var(--accent);color:var(--accent);}
.step .st-t{font-weight:600;font-size:.92rem;}
.step .st-s{font-size:.78rem;color:var(--muted);}

/* timeline */
.tl{position:relative;padding-left:18px;}
.tl:before{content:"";position:absolute;left:5px;top:6px;bottom:6px;width:2px;background:var(--border);}
.tl-ev{position:relative;padding:7px 0 7px 8px;}
.tl-ev:before{content:"";position:absolute;left:-17px;top:13px;width:8px;height:8px;border-radius:50%;
  background:var(--surface2);border:2px solid var(--muted);}
.tl-ev.g:before{border-color:var(--green);} .tl-ev.a:before{border-color:var(--amber);}
.tl-ev.r:before{border-color:var(--red);} .tl-ev.b:before{border-color:var(--blue);}
.tl-time{font-size:.72rem;color:var(--muted);font-variant-numeric:tabular-nums;}
.tl-txt{font-size:.88rem;}

/* chart bars */
.bars{display:flex;align-items:flex-end;gap:5px;height:110px;padding-top:8px;}
.bar{flex:1;background:linear-gradient(180deg,var(--accent),rgba(216,169,78,.35));border-radius:4px 4px 2px 2px;
  min-height:4px;position:relative;}
.bar:hover{filter:brightness(1.25);}
.bar span{position:absolute;bottom:-20px;left:50%;transform:translateX(-50%);font-size:.6rem;color:var(--muted);}

/* login */
.login-wrap{max-width:380px;margin:12vh auto;padding:32px;background:var(--surface);
  border:1px solid var(--border);border-radius:18px;text-align:center;}
.login-wrap h1{font-size:1.3rem;margin-bottom:4px;}

/* streamlit overrides */
.stButton>button{background:var(--surface2);color:var(--text);border:1px solid var(--border);
  border-radius:12px;min-height:48px;font-weight:600;width:100%;}
.stButton>button:hover{border-color:var(--accent);color:var(--accent);}
.stButton>button[kind="primary"]{background:var(--accent);color:#0a0d12;border:none;}
.stButton>button[kind="primary"]:hover{filter:brightness(1.1);color:#0a0d12;}
.stTextInput>div>div>input,.stTextArea textarea{background:var(--surface2);color:var(--text);
  border:1px solid var(--border);border-radius:10px;}
.stExpander{border:1px solid var(--border);border-radius:12px;background:var(--surface);}
.stExpander summary{color:var(--text);}
[data-testid="stMetric"]{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:12px;}
code{color:var(--accent)!important;}
</style>""", unsafe_allow_html=True)

# ---------------- github helpers (sin cambios) ----------------
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


def gh_put_json(path: str, obj: dict, msg: str) -> bool:
    content = base64.b64encode(json.dumps(obj, ensure_ascii=False, indent=1).encode()).decode()
    r = requests.put(f"{API}/{path}", headers={**H, "Accept": "application/vnd.github+json"},
                     json={"message": msg, "content": content}, timeout=20)
    return r.status_code in (200, 201)


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
    st.markdown('<div class="kv-card">Sin jobs sincronizados todavía.</div>', unsafe_allow_html=True)
    code = gh_status("snapshot.json")
    st.warning(f"Diagnóstico GitHub API: HTTP {code} — 401=token inválido o sin acceso al repo, "
               f"404=SYNC_REPO mal escrito o repo sin contenido, -1=sin conexión.")
    st.stop()

job_ids = [j["job_id"] for j in jobs]
if len(job_ids) == 1:
    jid = job_ids[0]
else:
    jid = st.selectbox("Job", job_ids)
job = next(j for j in jobs if j["job_id"] == jid)
versions = job.get("versions", [])
cur = versions[-1]["version"] if versions else None
if "ver" not in st.session_state or not any(v["version"] == st.session_state.ver for v in versions):
    st.session_state.ver = cur
sel_v = st.session_state.ver
curinfo = next((x for x in versions if x["version"] == cur), {}) if cur else {}
state = gh_json(f"jobs/{jid}/state.json") or {}
metrics = gh_json("learning/metrics.json") or {}
phase = gh_json("learning/phase.json") or {}
rules_l = gh_json("learning/rules.json") or []
disag = gh_json("learning/disagreements.json") or []


def _decision_pending() -> bool:
    return (curinfo.get("veredicto_efectivo") == "READY_FOR_ELVIN_REVIEW"
            and not curinfo.get("decidido"))


def hours_since(iso) -> float:
    """Horas desde un timestamp ISO. 999 si no se puede calcular."""
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


# Actividad REAL: solo se considera "en curso" si el estado se actualizó hace <15 min.
# Nada de indicadores pulsantes con datos de hace horas.
STATE_AGE_H = hours_since(state.get("updated"))
IS_LIVE = STATE_AGE_H < 0.25


def global_status():
    """(label, badge_class). Solo estados reales del job; la actividad 'en curso'
    exige estado fresco (<15 min). Sin inferencias de texto."""
    s = state.get("state", "")
    if s == "APPROVED":
        return ("APPROVED ✓", "b-green")
    if _decision_pending() or s == "ELVIN_DECISION_REQUIRED":
        return ("WAITING FOR ELVIN", "b-amber")
    if not IS_LIVE:
        return ("IDLE", "b-gray")
    if s in ("GENERATING", "CORRECTING"):
        return ("PRODUCING", "b-green")
    if s in ("REVIEWING", "VALIDATING", "ESCALATED_INTERNAL"):
        return ("REVIEWING", "b-blue")
    return ("IDLE", "b-gray")


def send_decision(action: str, note: str) -> None:
    did = str(uuid.uuid4())
    dec = {"decision_id": did, "job_id": jid, "version": cur,
           "action": action, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "note": note.strip()}
    if gh_put_json(f"decisions/inbox/{did}.json", dec, f"decision {action} {jid} {cur}"):
        st.success("Decisión enviada. Esperando ACK del reviewer-loop…")
        for _ in range(20):
            time.sleep(6)
            ack = gh_json(f"decisions/acks/{did}.json")
            gh_raw.clear()
            if ack:
                if ack["status"] == "accepted":
                    st.success(f"✅ Aceptada: {ack['reason']}")
                else:
                    st.error(f"❌ Rechazada: {ack['reason']}")
                with st.expander("Detalles del ACK"):
                    st.json(ack)
                break
        else:
            st.warning("Sin ACK todavía. Revisa en unos segundos.")
    else:
        st.error("No se pudo escribir la decisión en el repo.")


def media_for(vn):
    vinfo = next((x for x in versions if x["version"] == vn), {})
    mp4 = gh_raw(f"jobs/{jid}/versions/{vn}/asset.mp4")
    if mp4:
        return ("video", mp4)
    png = gh_raw(f"jobs/{jid}/versions/{vn}/asset.png")
    return ("image", png) if png else (None, None)


def verdict_badge(v):
    m = {"READY_FOR_ELVIN_REVIEW": ("READY", "b-gold"),
         "CORREGIR": ("CORREGIR", "b-red"), "ESCALAR": ("ESCALAR", "b-amber"),
         "APROBADO": ("APROBADO", "b-green"), "ESCALATED_INTERNAL": ("EN REVISIÓN", "b-blue")}
    return m.get(v, (v or "—", "b-gray"))


def fmt_ts(iso):
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return dt.strftime("%H:%M")
    except Exception:
        return "—"


# ---------------- navegación ----------------
NAV = [("home", "⌂", "Home"), ("asset", "◈", "Asset"),
       ("activity", "≋", "Activity"), ("learning", "✦", "Learning")]
st.markdown('<div class="nav-anchor"></div>', unsafe_allow_html=True)
with st.container():
    ncol = st.columns(4)
    for i, (t, ic, label) in enumerate(NAV):
        if ncol[i].button(f"{ic} {label}", key=f"nav_{t}",
                          type="primary" if TAB == t else "secondary",
                          use_container_width=True):
            st.session_state.tab = t
            st.rerun()

pending = _decision_pending()
glabel, gbadge = global_status()

# Banner de decisión visible en todas las pestañas
if pending:
    st.markdown(f"""<div class="decide-banner">
      <h2>◈ YOUR REVIEW IS REQUIRED</h2>
      <div class="kv-muted">{jid} · <b style="color:var(--text)">{cur}</b> está lista para tu decisión</div>
      </div>""", unsafe_allow_html=True)

def build_events():
    """Eventos reales del job, ordenados. Sin invenciones."""
    evs = []
    for v in versions:
        m = gh_json(f"jobs/{jid}/versions/{v['version']}/meta.json") or {}
        if m.get("registered"):
            evs.append((m["registered"], "g",
                        f"Muse registered {v['version']}", v["version"]))
    for d in disag:
        if d.get("job_id") == jid and d.get("ts"):
            cl = d.get("clase", "")
            txt = {"missed_by_muse": f"Supervisor review {d.get('version')} — CORREGIR",
                   "acuerdo": f"Supervisor review {d.get('version')} — PASS",
                   "supervisor_false_positive": f"Supervisor flagged {d.get('version')} — overruled",
                   "human_caught_miss": f"Elvin caught miss in {d.get('version')}",
                   "human_calibration_positive": f"Elvin approved {d.get('version')}",
                   "user_overrule": f"Elvin overruled {d.get('version')}"}.get(cl, f"{cl} {d.get('version')}")
            kc = "r" if cl in ("missed_by_muse", "human_caught_miss") else ("g" if cl == "acuerdo" else "a")
            evs.append((d["ts"], kc, txt, ""))
    try:
        listing = requests.get(f"{API}/decisions/inbox?ref=main", headers=H, timeout=20).json()
        if isinstance(listing, list):
            for f in listing:
                d = gh_json(f"decisions/inbox/{f['name']}")
                if d and d.get("timestamp") and d.get("job_id") == jid:
                    evs.append((d["timestamp"], "a",
                                f"Elvin: {d.get('action')} {d.get('version')}", ""))
    except Exception:
        pass
    evs.sort(key=lambda x: x[0])
    return evs


# ================= HOME / COMMAND CENTER =================
if TAB == "home":
    st.markdown(f"""<div class="kv-card">
      <h4>Kaia Vale · Global Status</h4>
      <div class="kv-big">◈ KAIA VALE</div>
      <div style="margin-top:8px"><span class="badge {gbadge}">{glabel}</span>
      <span class="kv-muted" style="margin-left:10px">{jid}</span></div>
      </div>""", unsafe_allow_html=True)

    # ---- MUSE STATUS (Progress/Heartbeat Protocol 2026-10-12) ----
    ms = gh_json("progress/muse_status.json") or {}
    mstatus = ms.get("status", "—")
    mtask = ms.get("current_task") or "—"
    mstep = ms.get("current_step") or "—"
    mwait = ms.get("waiting_on") or "—"
    mstarted = ms.get("started_at") or ""
    mh = hours_since(ms.get("last_heartbeat")) if ms.get("last_heartbeat") else 999.0
    # Stale detection: activo pero sin heartbeat >10 min -> POSSIBLY STALLED
    stale = mstatus not in ("COMPLETED", "FAILED", "—") and mh * 60 > 10
    sbadge = "b-red" if stale else {"WORKING": "b-green", "WAITING_ON_TOOL": "b-amber",
                                    "BLOCKED": "b-red", "COMPLETED": "b-gray",
                                    "FAILED": "b-red"}.get(mstatus, "b-gray")
    slabel = "POSSIBLY STALLED" if stale else mstatus
    st.markdown(f"""<div class="kv-card"><h4>🤖 Muse status</h4>
      <div style="margin-bottom:8px"><span class="badge {sbadge}">{slabel}</span>
      <span class="kv-muted" style="margin-left:10px">último heartbeat {hace_str(mh)}</span></div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px 16px">
      <div><div class="kv-muted" style="font-size:.72rem">CURRENT TASK</div>
        <div style="font-weight:600">{mtask[:60]}</div></div>
      <div><div class="kv-muted" style="font-size:.72rem">CURRENT STEP</div>
        <div style="font-weight:600">{mstep[:60]}</div></div>
      <div><div class="kv-muted" style="font-size:.72rem">WAITING ON</div>
        <div style="font-weight:600">{mwait}</div></div>
      <div><div class="kv-muted" style="font-size:.72rem">STARTED AT</div>
        <div style="font-weight:600">{fmt_ts(mstarted) if mstarted else "—"}</div></div>
      </div></div>""", unsafe_allow_html=True)
    hist = ms.get("history") or []
    if hist:
        with st.expander(f"📜 Historial de actividad ({len(hist)})"):
            for ev in reversed(hist[-10:]):
                st.markdown(f"• `{fmt_ts(ev.get('ts'))}` — {ev.get('event', '')[:120]}")
    if stale:
        st.caption("⚠️ Sin heartbeat reciente. La tarea podría estar congelada "
                   "(no se cancela automáticamente).")
    # Banner prioritario: bloqueado esperando decisión de Elvin
    if mstatus == "BLOCKED_ON_ELVIN" and ms.get("needs_decision"):
        st.markdown(f"""<div class="kv-card" style="border:2px solid #f59e0b">
          <h4>🟡 NECESITO TU DECISIÓN</h4>
          <div style="font-weight:600">{ms.get("needs_decision")[:300]}</div>
          <div class="kv-muted">Muse está detenido esperando tu respuesta. No avanza hasta que decidas.</div>
          </div>""", unsafe_allow_html=True)

    # Pipeline MUSE → GENERATION → QC → SUPERVISOR → CORRECTION → READY
    nodes = ["MUSE", "GENERATION", "QC", "SUPERVISOR", "CORRECTION", "READY"]
    active_idx = {"PRODUCING": 1, "REVIEWING": 3, "WAITING FOR ELVIN": 5}.get(glabel, -1)
    all_done = glabel.startswith("APPROVED")
    # si la última acción fue corrección, iluminar CORRECTION en PRODUCING
    last_v = curinfo.get("veredicto_efectivo", "")
    if glabel == "PRODUCING" and last_v == "CORREGIR":
        active_idx = 4
    subs = {0: "agent", 1: "krea 2", 2: "local", 3: "gpt-5", 4: "krea 2", 5: "elvin"}
    pipe = '<div class="pipe">'
    for i, n in enumerate(nodes):
        cls = "active" if i == active_idx else ("done" if (0 <= active_idx and i < active_idx) or all_done else "")
        dot = '<span class="pulse"></span>' if i == active_idx else ""
        pipe += (f'<div class="pnode {cls}"><div class="t">{dot}{n}</div>'
                 f'<div class="s">{subs[i]}</div></div>')
        if i < len(nodes) - 1:
            pipe += f'<div class="plink {"on" if 0 <= active_idx and i < active_idx else ""}"></div>'
    pipe += "</div>"
    st.markdown(f'<div class="kv-card"><h4>Pipeline</h4>{pipe}'
                f'<div class="kv-muted">Última actividad del job: {hace_str(STATE_AGE_H)} · '
                f'sincronización ~60s</div></div>', unsafe_allow_html=True)

    # Actividad reciente: SOLO eventos reales con timestamp. Si no hay nada
    # en curso, se dice explícitamente. Nada de pasos inventados.
    evs_home = build_events()
    st.markdown('<div class="kv-card"><h4>Recent activity</h4><div class="tl">', unsafe_allow_html=True)
    for ts, kc, txt, _ in evs_home[-4:]:
        st.markdown(f'<div class="tl-ev {kc}"><span class="tl-time">{fmt_ts(ts)}</span> '
                    f'<span class="tl-txt">{txt}</span></div>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
    if IS_LIVE and glabel in ("PRODUCING", "REVIEWING"):
        st.markdown('<div style="margin:-6px 0 14px"><span class="badge b-green">'
                    '<span class="pulse"></span>EN CURSO AHORA</span></div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="kv-muted" style="margin:-6px 0 14px">Sin actividad en curso. '
                    f'Último evento {hace_str(STATE_AGE_H)}.</div>', unsafe_allow_html=True)

    # Panel de decisión
    if pending:
        st.markdown('<div class="kv-card"><h4>Decision mode</h4>', unsafe_allow_html=True)
        vinfo = next((x for x in versions if x["version"] == cur), {})
        lbl, _ = verdict_badge(vinfo.get("veredicto_efectivo"))
        vd = gh_json(f"jobs/{jid}/versions/{cur}/verdict.json") or {}
        halls = vd.get("hallazgos", [])
        with st.container():
            mtype, mdata = media_for(cur)
            if mdata and mtype == "image":
                st.image(mdata, use_container_width=True)
            elif mdata:
                st.video(mdata)
        if halls:
            st.markdown("**Resumen:**")
            for h in halls[:4]:
                st.markdown(f"• {h.get('descripcion', '')[:140]}")
        else:
            st.markdown("Sin hallazgos bloqueantes. Lista para publicar.")
        st.markdown('<div class="decide-btns">', unsafe_allow_html=True)
        note = st.text_input("Instrucciones (solo para pedir cambios)", key=f"hm_note_{jid}_{cur}")
        b1, b2, b3 = st.columns(3)
        if b1.button("APPROVE FINAL", key=f"hm_ap_{jid}_{cur}", type="primary"):
            send_decision("approve_final", "")
        if b2.button("REQUEST CHANGES", key=f"hm_rc_{jid}_{cur}"):
            if not note.strip():
                st.error("Escribe las instrucciones para pedir cambios.")
            else:
                send_decision("request_changes", note)
        if b3.button("REJECT", key=f"hm_rj_{jid}_{cur}"):
            send_decision("reject", "")
        st.markdown("</div></div>", unsafe_allow_html=True)
    elif state.get("state") == "ELVIN_DECISION_REQUIRED":
        st.error("⛔ Requiere tu decisión: el sistema no pudo resolverlo con el canon ni las reglas. Revisa el veredicto en la pestaña Asset.")

    # Stats rápidas
    c1, c2 = st.columns(2)
    with c1:
        caps = budget.get("caps_usd", {})
        used = budget.get("monthly_used_usd", 0)
        st.markdown(f'<div class="kv-card"><h4>Supervisor budget</h4>'
                    f'<div class="kv-big">${used:.4f}</div>'
                    f'<div class="kv-muted">de ${caps.get("monthly", "?")} mensual</div></div>',
                    unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div class="kv-card"><h4>Cosmo</h4>'
                    f'<div class="kv-big" style="font-size:1.2rem">{agent.get("status", "—")}</div>'
                    f'<div class="kv-muted">agente local</div></div>', unsafe_allow_html=True)

# ================= ASSET =================
elif TAB == "asset":
    # Timeline de versiones (botones: los links recargaban y cerraban sesión)
    st.markdown('<div class="kv-card"><h4>Version timeline</h4>', unsafe_allow_html=True)
    vcols = st.columns(len(versions)) if versions else []
    for i, v in enumerate(versions):
        vn = v["version"]
        if vcols[i].button(vn, key=f"vsel_{jid}_{vn}",
                           type="primary" if vn == sel_v else "secondary",
                           use_container_width=True):
            st.session_state.ver = vn
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

    vinfo = next((x for x in versions if x["version"] == sel_v), {})
    meta = gh_json(f"jobs/{jid}/versions/{sel_v}/meta.json") or {}
    vd = gh_json(f"jobs/{jid}/versions/{sel_v}/verdict.json") or {}
    dec = gh_json(f"jobs/{jid}/versions/{sel_v}/decision.json") or {}
    audit = gh_json(f"jobs/{jid}/versions/{sel_v}/audit.json") or {}
    # Si Elvin ya decidió sobre esta versión, mostrar el resultado real
    dec_elvin = gh_json(f"jobs/{jid}/versions/{sel_v}/decision_elvin.json") if vinfo.get("decidido") else None
    if dec_elvin:
        lbl = {"approve_final": "APROBADA ✓", "reject": "RECHAZADA",
               "request_changes": "CAMBIOS PEDIDOS"}.get(dec_elvin.get("decision"), "DECIDIDA")
        lbadge = {"approve_final": "b-green", "reject": "b-red",
                  "request_changes": "b-amber"}.get(dec_elvin.get("decision"), "b-gray")
    else:
        lbl, lbadge = verdict_badge(vinfo.get("veredicto_efectivo"))

    st.markdown(f"""<div class="kv-card" style="text-align:center">
      <span class="badge {lbadge}" style="font-size:.9rem;padding:6px 18px">{sel_v} · {lbl}</span>
      </div>""", unsafe_allow_html=True)
    mtype, mdata = media_for(sel_v)
    if mdata and mtype == "image":
        st.image(mdata, use_container_width=True)
    elif mdata:
        st.video(mdata)
    else:
        st.info("Asset aún no sincronizado.")

    # Metadata
    params = meta.get("params", {})
    conf = vd.get("confianza", "—")
    cost = dec.get("costo_usd_estimado", "—")
    res = (audit.get("asset_original", {}) or {}).get("resolucion", "—")
    halls = vd.get("hallazgos", [])
    cov = vd.get("visual_coverage") or {}
    npass = sum(1 for c in cov.values() if isinstance(c, dict)
                for v2 in c.values() if isinstance(v2, dict) and v2.get("estado") == "PASS")
    nfail = sum(1 for c in cov.values() if isinstance(c, dict)
                for v2 in c.values() if isinstance(v2, dict) and v2.get("estado") == "FAIL")
    rows = [("Versión", sel_v), ("Estado", lbl), ("Modelo", params.get("model", "—")),
            ("Resolución", res), ("Confidence", conf),
            ("Costo", f"${cost:.4f}" if isinstance(cost, (int, float)) else cost),
            ("Registrada", fmt_ts(meta.get("registered"))),
            ("Defectos", str(len(halls))),
            ("Visual Coverage", f"{npass} PASS · {nfail} FAIL" if cov else "—")]
    grid = '<div class="kv-card"><h4>Detalles</h4><div style="display:grid;grid-template-columns:1fr 1fr;gap:8px 16px">'
    for k, v_ in rows:
        grid += f'<div><div class="kv-muted" style="font-size:.72rem">{k}</div><div style="font-weight:600">{v_}</div></div>'
    grid += "</div></div>"
    st.markdown(grid, unsafe_allow_html=True)

    # Qué estaba mal → qué se corrigió → quién lo detectó
    if halls:
        st.markdown('<div class="kv-card"><h4>Hallazgos</h4>', unsafe_allow_html=True)
        for h in halls:
            sev = h.get("severidad", "")
            st.markdown(f"• **{h.get('categoria','')}** ({sev}): {h.get('descripcion','')[:220]}")
        st.markdown("</div>", unsafe_allow_html=True)
    # quién lo detectó (del log de aprendizaje)
    rel = [d for d in disag if d.get("job_id") == jid and d.get("version") == sel_v]
    if rel:
        st.markdown('<div class="kv-card"><h4>Quién lo detectó</h4>', unsafe_allow_html=True)
        for d in rel:
            quien = {"missed_by_muse": "Supervisor lo detectó",
                     "supervisor_false_positive": "Supervisor marcó · Muse discrepa",
                     "human_caught_miss": "Elvin lo detectó",
                     "human_calibration_positive": "Elvin lo aprobó",
                     "acuerdo": "Muse y Supervisor de acuerdo"}.get(d.get("clase"), d.get("clase"))
            st.markdown(f"• {quien}")
            if d.get("nota"):
                st.caption(str(d["nota"])[:220])
        st.markdown("</div>", unsafe_allow_html=True)
    if meta.get("nota"):
        st.caption(f"📝 {meta['nota'][:300]}")

    # Visual Coverage resumido
    if cov:
        st.markdown('<div class="kv-card"><h4>Visual Coverage</h4>', unsafe_allow_html=True)
        for cat, items in cov.items():
            if not isinstance(items, dict):
                continue
            fails = [k for k, v2 in items.items()
                     if isinstance(v2, dict) and v2.get("estado") == "FAIL"]
            icon = "❌" if fails else "✅"
            with st.expander(f"{icon} {cat} ({len(items)} ítems)"):
                for k, v2 in items.items():
                    if not isinstance(v2, dict):
                        continue
                    est = v2.get("estado", "?")
                    ic = {"PASS": "✅", "FAIL": "❌", "NOT_VISIBLE": "👁", "NOT_APPLICABLE": "➖"}.get(est, "❓")
                    st.markdown(f"{ic} **{k}** — {est}")
                    if v2.get("evidencia"):
                        st.caption(f"↳ {v2['evidencia'][:160]}")
        st.markdown("</div>", unsafe_allow_html=True)

    # Video QC (post-mortem 2026-10-12: los videos bypassaban el loop)
    tr = vd.get("temporal_review") or {}
    tech_v = gh_json(f"jobs/{jid}/technical_validation_video.json") or {}
    if tr or tech_v:
        st.markdown('<div class="kv-card"><h4>🎬 Video QC</h4>', unsafe_allow_html=True)
        # Validación técnica
        if tech_v:
            fails_t = [k for k, c in tech_v.items()
                       if isinstance(c, dict) and c.get("estado") == "FAIL"]
            icon_t = "❌" if fails_t else "✅"
            with st.expander(f"{icon_t} Technical validation "
                             f"({'FAIL: ' + ', '.join(fails_t) if fails_t else 'PASS'})"):
                for k, c in tech_v.items():
                    if not isinstance(c, dict):
                        continue
                    est = c.get("estado", "?")
                    ic = {"PASS": "✅", "FAIL": "❌"}.get(est, "❓")
                    st.markdown(f"{ic} **{k}** — {est}")
                    if c.get("detalle"):
                        st.caption(f"↳ {c['detalle'][:180]}")
                st.caption("TECHNICAL_FPS es dato técnico, no prueba de fluidez percibida.")
        # Temporal review por categoría
        if tr:
            with st.expander("⏱ Temporal review"):
                for cat, c in tr.items():
                    if not isinstance(c, dict):
                        continue
                    est = c.get("estado", "?")
                    ic = {"PASS": "✅", "FAIL": "❌",
                          "NOT_VERIFIABLE": "⚠️", "NOT_APPLICABLE": "➖"}.get(est, "❓")
                    st.markdown(f"{ic} **{cat}** — {est}")
                    if c.get("evidencia"):
                        st.caption(f"📎 Evidencia: {c['evidencia'][:180]}")
                    if c.get("notas"):
                        st.caption(f"📝 {c['notas'][:220]}")
                st.caption("NOT_VERIFIABLE bloquea READY_FOR_ELVIN_REVIEW (fail-closed).")
        st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("View technical details"):
        st.json({"meta": meta, "verdict_resumen": {k: vd.get(k) for k in
                ("veredicto", "confianza", "motivo_principal")},
                "decision": dec, "audit": {k: audit.get(k) for k in
                ("asset_original", "generado")} if audit else None})

# ================= ACTIVITY =================
elif TAB == "activity":
    st.markdown('<div class="kv-card"><h4>Estado actual</h4>', unsafe_allow_html=True)
    st.markdown(f'<div style="margin-bottom:8px"><span class="badge {gbadge}">{glabel}</span></div>',
                unsafe_allow_html=True)
    if IS_LIVE and glabel in ("PRODUCING", "REVIEWING"):
        st.markdown('<span class="badge b-green"><span class="pulse"></span>EN CURSO AHORA</span>',
                    unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="kv-muted">Sin actividad en curso. '
                    f'Última actualización del job {hace_str(STATE_AGE_H)}.</div>',
                    unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    # Timeline de eventos (construida de datos reales)
    evs = build_events()
    st.markdown('<div class="kv-card"><h4>Activity timeline</h4><div class="tl">', unsafe_allow_html=True)
    for ts, kc, txt, _ in evs[-25:]:
        st.markdown(f'<div class="tl-ev {kc}"><span class="tl-time">{fmt_ts(ts)}</span> '
                    f'<span class="tl-txt">{txt}</span></div>', unsafe_allow_html=True)
    st.markdown("</div></div>", unsafe_allow_html=True)

    ev = gh_json(f"jobs/{jid}/events.json") or {"lines": []}
    with st.expander("Raw technical log"):
        st.code("\n".join(ev.get("lines", [])[-40:]))

# ================= LEARNING =================
elif TAB == "learning":
    fase = metrics.get("fase", phase.get("fase", "?"))
    st.markdown(f"""<div class="kv-card"><h4>Learning Center</h4>
      <div class="kv-big">◈ {fase}</div>
      <div class="kv-muted">{"Supervisión total — el supervisor revisa todo." if fase=="FASE_1" else ""}</div>
      </div>""", unsafe_allow_html=True)

    def card(title, big, sub=""):
        st.markdown(f'<div class="kv-card"><h4>{title}</h4><div class="kv-big">{big}</div>'
                    f'<div class="kv-muted">{sub}</div></div>', unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        card("Muse ↔ Supervisor agreement", f"{metrics.get('acuerdo_pct', '?')}%", "revisiones con veredicto coincidente")
        card("Clean streak", str(metrics.get("jobs_consecutivos_sin_desacuerdo", 0)), "revisiones sin desacuerdo")
        card("Learned rules", str(metrics.get("reglas_aprendidas", 0)), "reglas operacionales activas")
        card("Supervisor cost", f"${metrics.get('costo_supervisor_total_usd', 0):.4f}", "total acumulado")
    with c2:
        hcm = metrics.get("human_caught_miss", 0)
        card("Human Caught Miss", str(hcm), "Elvin detectó · Muse+Supervisor omitieron")
        fp = metrics.get("falsos_positivos_muse", 0) + metrics.get("falsos_positivos_supervisor", 0)
        card("False positives", str(fp), "Muse + Supervisor")
        card("Calls avoided", str(metrics.get("llamadas_evitadas", 0)), "revisiones que Muse resolvió solo")
        card("Revisiones", str(metrics.get("revisiones_totales", 0)), "total registradas")

    if hcm:
        st.markdown(f"""<div class="kv-card" style="border-color:rgba(248,113,113,.4)">
          <h4 style="color:var(--red)">⚠ Human Caught Miss — bloquea salida de FASE_1</h4>""",
                    unsafe_allow_html=True)
        for d in metrics.get("human_caught_miss_detalle", []):
            st.markdown(f"• **{d['job_id']} {d['version']}**: {', '.join(d['hallazgos'][:2])}")
        st.markdown("</div>", unsafe_allow_html=True)

    # Evolución del aprendizaje: acuerdo acumulado en el tiempo
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
                f'<div class="bar" style="height:{max(p,4)}%" title="{p}%"><span>{i+1}</span></div>'
                for i, p in enumerate(pts[-20:]))
            st.markdown(f'<div class="kv-card"><h4>Learning evolution — acuerdo acumulado</h4>'
                        f'<div class="bars">{bars}</div>'
                        f'<div class="kv-muted" style="margin-top:26px">¿Muse está mejorando? '
                        f'Tendencia del % de acuerdo tras cada revisión.</div></div>',
                        unsafe_allow_html=True)

    # Quién lo detectó
    n_sup = sum(1 for d in disag if d.get("clase") == "missed_by_muse")
    n_elv = sum(1 for d in disag if d.get("clase") == "human_caught_miss")
    n_muse = metrics.get("llamadas_evitadas", 0)
    st.markdown('<div class="kv-card"><h4>Quién lo detectó</h4>', unsafe_allow_html=True)
    cc1, cc2, cc3 = st.columns(3)
    cc1.markdown(f'<div class="kv-big" style="color:var(--green)">{n_muse}</div><div class="kv-muted">Muse caught it</div>', unsafe_allow_html=True)
    cc2.markdown(f'<div class="kv-big" style="color:var(--blue)">{n_sup}</div><div class="kv-muted">Supervisor caught it</div>', unsafe_allow_html=True)
    cc3.markdown(f'<div class="kv-big" style="color:var(--amber)">{n_elv}</div><div class="kv-muted">Elvin caught it</div>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("Learned rules"):
        for r in rules_l:
            if r.get("activa"):
                st.markdown(f"**{r['id']}** — {r['regla'][:200]}")
    with st.expander("Desacuerdos recientes"):
        for d in reversed(disag[-8:]):
            st.markdown(f"**{d['job_id']} {d['version']}** · {d.get('clase')}")

# ---------------- auto-refresh ----------------
st.caption("Actualización automática cada ~30s.")
time.sleep(30)
st.rerun()
