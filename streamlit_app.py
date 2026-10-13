"""Kaia Vale Control Center — v4 "Neon Studio" (2026-10-12).

Rediseño creativo inspirado en apps de generación IA (Higgsfield/PrimeIA):
- Identidad neón: violeta eléctrico + cian sobre negro profundo
- Héroe cinematográfico: el render actual como protagonista (base64, overlay)
- Filmstrip horizontal con scroll-snap (thumbnails base64 en un solo bloque)
- Anillo de progreso CSS para métricas, glassmorphism, glow
- Lenguaje de "AI studio": Renders, Queue, Verdict, Model stats

SOLO frontend/UX. Sin cambios en reviewer-loop, sync, decisiones ni seguridad.
Secretos: DASHBOARD_PASSWORD, GITHUB_TOKEN, SYNC_REPO (Streamlit Secrets).
"""
import base64
import io
import json
import time
import uuid
from datetime import datetime

import requests
import streamlit as st

st.set_page_config(page_title="Kaia Vale · Studio", layout="wide",
                   initial_sidebar_state="collapsed")

try:
    PASSWORD = st.secrets["DASHBOARD_PASSWORD"]
    TOKEN = st.secrets["GITHUB_TOKEN"]
    REPO = st.secrets["SYNC_REPO"]
except Exception:
    st.error("Faltan secretos: DASHBOARD_PASSWORD, GITHUB_TOKEN, SYNC_REPO en Settings → Secrets.")
    st.stop()

API = f"https://api.github.com/repos/{REPO}/contents"
H = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github.raw"}

if "tab" not in st.session_state:
    st.session_state.tab = "studio"
if "sel_ver" not in st.session_state:
    st.session_state.sel_ver = None
TAB = st.session_state.tab
if TAB not in ("studio", "renders", "queue", "model"):
    TAB = "studio"
    st.session_state.tab = "studio"

# ---------------- CSS: Neon Studio ----------------
st.markdown("""<style>
:root{
  --bg:#050508; --surface:rgba(20,22,34,.72); --surface2:rgba(28,32,48,.72);
  --border:rgba(139,92,246,.16); --border2:rgba(139,92,246,.32);
  --text:#f2f3fa; --muted:#9aa0b8; --faint:#5d6379;
  --violet:#8b5cf6; --violet2:#c4b5fd; --cyan:#22d3ee; --cyan2:#a5f3fc;
  --green:#4ade80; --red:#f87171; --amber:#fbbf24; --blue:#6aa8ff;
  --grad:linear-gradient(120deg,#8b5cf6,#22d3ee);
}
html,body,[data-testid="stAppViewContainer"]{background:var(--bg);color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,sans-serif;}
[data-testid="stHeader"],#MainMenu,footer{visibility:hidden;display:none;}
.block-container{padding-top:.4rem;padding-bottom:9rem;max-width:1280px;}
h1,h2,h3{color:var(--text)!important;letter-spacing:-.02em;}
.stCaption,small{color:var(--muted)!important;}

/* fondo ambiental */
[data-testid="stAppViewContainer"]:before{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;
  background:
    radial-gradient(700px 340px at 12% -4%,rgba(139,92,246,.14),transparent 60%),
    radial-gradient(640px 320px at 88% 6%,rgba(34,211,238,.1),transparent 60%),
    radial-gradient(900px 500px at 50% 110%,rgba(139,92,246,.08),transparent 60%);}

/* ===== top bar ===== */
.topbar{position:sticky;top:0;z-index:900;display:flex;align-items:center;gap:10px;
  padding:10px 2px;margin:-.4rem -1rem .9rem;
  background:rgba(5,5,8,.82);backdrop-filter:blur(16px);
  border-bottom:1px solid var(--border);}
.topbar .logo{font-weight:900;font-size:1.02rem;letter-spacing:.08em;
  background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent;}
.topbar .spacer{flex:1;}
.orb{display:inline-flex;align-items:center;gap:8px;padding:7px 14px;border-radius:999px;
  font-size:.74rem;font-weight:800;letter-spacing:.06em;
  background:var(--surface2);border:1px solid var(--border2);backdrop-filter:blur(8px);}
.orb .d{width:9px;height:9px;border-radius:50%;}
.orb.g{color:var(--green);} .orb.g .d{background:var(--green);box-shadow:0 0 12px var(--green);animation:bl 1.8s infinite;}
.orb.a{color:var(--amber);} .orb.a .d{background:var(--amber);box-shadow:0 0 12px var(--amber);animation:bl 1.8s infinite;}
.orb.b{color:var(--cyan);} .orb.b .d{background:var(--cyan);box-shadow:0 0 12px var(--cyan);animation:bl 1.8s infinite;}
.orb.gr{color:var(--muted);} .orb.gr .d{background:var(--muted);}
.orb.r{color:var(--red);} .orb.r .d{background:var(--red);box-shadow:0 0 12px var(--red);}
@keyframes bl{0%,100%{opacity:.55;transform:scale(.88);}50%{opacity:1;transform:scale(1.12);}}

/* ===== héroe cinematográfico ===== */
.hero{position:relative;border-radius:22px;overflow:hidden;margin-bottom:14px;
  border:1px solid var(--border2);background:#0a0a12;
  box-shadow:0 24px 70px -18px rgba(139,92,246,.35);}
.hero img{display:block;width:100%;max-height:58vh;object-fit:cover;object-position:center 22%;}
.hero .shade{position:absolute;inset:0;
  background:linear-gradient(180deg,rgba(5,5,8,.25) 0%,transparent 32%,transparent 52%,rgba(5,5,8,.92) 100%);}
.hero .cap{position:absolute;left:0;right:0;bottom:0;padding:18px;}
.hero .cap .v{font-size:1.5rem;font-weight:900;letter-spacing:-.02em;}
.hero .cap .row{display:flex;align-items:center;gap:10px;margin-top:8px;flex-wrap:wrap;}
.vbadge{display:inline-flex;align-items:center;padding:6px 14px;border-radius:999px;
  font-size:.74rem;font-weight:800;letter-spacing:.06em;backdrop-filter:blur(8px);
  border:1px solid var(--border2);background:rgba(10,10,18,.55);}
.vbadge.gold{color:#f0c76a;border-color:rgba(240,199,106,.5);}
.vbadge.green{color:var(--green);border-color:rgba(74,222,128,.5);}
.vbadge.red{color:var(--red);border-color:rgba(248,113,113,.5);}
.vbadge.blue{color:var(--cyan);border-color:rgba(34,211,238,.5);}
.vbadge.gray{color:var(--muted);}
.hero .meta-line{color:var(--muted);font-size:.8rem;margin-top:6px;}

/* ===== filmstrip ===== */
.fstrip{display:flex;gap:10px;overflow-x:auto;padding:4px 2px 12px;
  scroll-snap-type:x mandatory;-webkit-overflow-scrolling:touch;}
.fstrip::-webkit-scrollbar{height:6px;}
.fstrip::-webkit-scrollbar-thumb{background:var(--border2);border-radius:3px;}
.fitem{flex:0 0 auto;scroll-snap-align:start;width:118px;cursor:pointer;}
.fitem img{width:118px;height:158px;object-fit:cover;border-radius:12px;display:block;
  border:2px solid transparent;transition:border-color .15s ease,transform .15s ease;}
.fitem:hover img{transform:translateY(-2px);}
.fitem.sel img{border-color:var(--violet);box-shadow:0 0 16px rgba(139,92,246,.5);}
.fitem .fv{font-size:.68rem;font-weight:800;margin-top:5px;text-align:center;color:var(--muted);}
.fitem.sel .fv{color:var(--violet2);}
.sect{font-size:.78rem;font-weight:800;letter-spacing:.12em;color:var(--muted);
  margin:18px 0 8px;text-transform:uppercase;}

/* ===== glass cards ===== */
.gcard{background:var(--surface);border:1px solid var(--border);border-radius:18px;
  padding:16px;margin-bottom:12px;backdrop-filter:blur(12px);}
.gcard h4{margin:0 0 10px;font-size:.72rem;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);}
.kv-big{font-size:1.7rem;font-weight:900;letter-spacing:-.02em;
  background:linear-gradient(180deg,#fff,#c9cede);-webkit-background-clip:text;background-clip:text;color:transparent;}
.kv-muted{color:var(--muted);font-size:.84rem;}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px;}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;}
@media(max-width:640px){.grid3{grid-template-columns:1fr 1fr;}.kv-big{font-size:1.35rem;}}

/* ===== anillo de progreso ===== */
.ring{--p:50;--c:var(--violet);width:92px;height:92px;border-radius:50%;flex:0 0 auto;
  background:conic-gradient(var(--c) calc(var(--p)*1%),rgba(255,255,255,.08) 0);
  display:flex;align-items:center;justify-content:center;position:relative;}
.ring:before{content:"";position:absolute;inset:9px;border-radius:50%;background:#0b0b13;}
.ring span{position:relative;font-weight:900;font-size:1.05rem;}
.ringwrap{display:flex;align-items:center;gap:14px;}

/* ===== queue stepper ===== */
.qstep{display:flex;gap:12px;align-items:flex-start;padding:11px 2px;position:relative;}
.qstep .n{flex:0 0 30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;
  font-size:.75rem;font-weight:800;background:var(--surface2);border:1px solid var(--border2);color:var(--muted);z-index:1;}
.qstep:before{content:"";position:absolute;left:16px;top:44px;bottom:-6px;width:2px;background:var(--border);}
.qstep:last-child:before{display:none;}
.qstep.on .n{background:var(--grad);color:#0a0618;border:none;box-shadow:0 0 18px rgba(139,92,246,.6);}
.qstep.done .n{border-color:var(--green);color:var(--green);}
.qstep .t{font-weight:800;font-size:.92rem;}
.qstep .s{font-size:.78rem;color:var(--muted);}
.qstep.on .t{background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent;}

/* ===== verdict panel ===== */
.verdict{position:relative;overflow:hidden;border-radius:22px;padding:22px;margin:16px 0;
  border:1px solid rgba(240,199,106,.45);
  background:linear-gradient(135deg,rgba(139,92,246,.16),rgba(34,211,238,.07) 60%,rgba(240,199,106,.1));}
.verdict:before{content:"";position:absolute;inset:0;pointer-events:none;
  background:radial-gradient(420px 160px at 50% -20%,rgba(240,199,106,.22),transparent 65%);}
.verdict h3{margin:0 0 4px;font-size:1.25rem;text-align:center;}
.verdict .sub{text-align:center;color:var(--muted);font-size:.85rem;margin-bottom:14px;}

/* ===== timeline ===== */
.tl{position:relative;padding-left:20px;}
.tl:before{content:"";position:absolute;left:6px;top:8px;bottom:8px;width:2px;
  background:linear-gradient(180deg,var(--violet),var(--cyan));opacity:.35;}
.tl-ev{position:relative;padding:8px 0 8px 6px;}
.tl-ev:before{content:"";position:absolute;left:-18px;top:14px;width:9px;height:9px;border-radius:50%;
  background:#0b0b13;border:2px solid var(--muted);}
.tl-ev.g:before{border-color:var(--green);box-shadow:0 0 8px rgba(74,222,128,.6);}
.tl-ev.a:before{border-color:var(--amber);}
.tl-ev.r:before{border-color:var(--red);}
.tl-ev.b:before{border-color:var(--cyan);}
.tl-time{font-size:.7rem;color:var(--faint);font-variant-numeric:tabular-nums;}
.tl-txt{font-size:.88rem;}
.spec{display:grid;grid-template-columns:1fr 1fr;gap:10px 14px;}
.spec .k{font-size:.66rem;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);}
.spec .v{font-weight:800;font-size:.92rem;margin-top:2px;}

/* ===== nav ===== */
.mnav{display:none;}
@media(max-width:767px){
  .mnav{display:flex;position:fixed;left:12px;right:12px;bottom:calc(10px + env(safe-area-inset-bottom));z-index:950;
    background:rgba(14,16,26,.92);backdrop-filter:blur(18px);
    border:1px solid var(--border2);border-radius:22px;padding:6px;
    box-shadow:0 12px 40px rgba(0,0,0,.5);}
  .mnav button{flex:1;background:none!important;border:none!important;color:var(--muted);
    font-size:.6rem;font-weight:800;display:flex;flex-direction:column;align-items:center;gap:2px;
    padding:9px 0;border-radius:16px;min-height:0;}
  .mnav button .ic{font-size:1.3rem;line-height:1;}
  .mnav button[kind="primary"]{background:var(--grad)!important;color:#0a0618!important;}
  .dnav{display:none;}
}
@media(min-width:768px){
  .dnav{display:flex;gap:8px;margin-bottom:16px;}
  .dnav button{background:var(--surface2);border:1px solid var(--border);color:var(--muted);
    border-radius:999px;padding:10px 22px;font-weight:800;font-size:.85rem;}
  .dnav button[kind="primary"]{background:var(--grad);color:#0a0618;border:none;
    box-shadow:0 6px 24px rgba(139,92,246,.4);}
}

/* ===== botones ===== */
.stButton>button{background:var(--surface2);color:var(--text);border:1px solid var(--border2);
  border-radius:16px;min-height:54px;font-weight:800;font-size:.95rem;width:100%;}
.stButton>button:hover{border-color:var(--violet);color:var(--violet2);}
.stButton>button:active{transform:scale(.98);}
.stButton>button[kind="primary"]{background:var(--grad);color:#0a0618;border:none;
  box-shadow:0 8px 28px rgba(139,92,246,.45);}
.stButton>button[kind="primary"]:hover{filter:brightness(1.1);color:#0a0618;}
.stTextInput>div>div>input{background:var(--surface2);color:var(--text);
  border:1px solid var(--border2);border-radius:14px;font-size:.95rem;}
.stExpander{border:1px solid var(--border);border-radius:16px;background:var(--surface);}
.stExpander summary{color:var(--text);font-weight:700;}
[data-testid="stImage"] img{border-radius:16px;}
code{color:var(--violet2)!important;font-size:.8em;}
.login-wrap{max-width:380px;margin:10vh auto;padding:34px 30px;background:var(--surface);
  border:1px solid var(--border2);border-radius:24px;text-align:center;}
.login-wrap h1{font-size:1.35rem;margin-bottom:4px;background:var(--grad);
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


# Thumbnails base64 (un solo bloque HTML = filmstrip real)
@st.cache_data(ttl=120)
def thumb_b64(path: str, w: int = 236) -> str | None:
    try:
        from PIL import Image
        b = gh_raw(path)
        if not b:
            return None
        im = Image.open(io.BytesIO(b)).convert("RGB")
        im.thumbnail((w, w * 2), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=68)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


@st.cache_data(ttl=120)
def hero_b64(path: str, w: int = 900) -> str | None:
    try:
        from PIL import Image
        b = gh_raw(path)
        if not b:
            return None
        im = Image.open(io.BytesIO(b)).convert("RGB")
        im.thumbnail((w, w * 2), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=74)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


# ---------------- auth ----------------
if "auth" not in st.session_state:
    st.session_state.auth = False
if not st.session_state.auth:
    st.markdown('<div class="login-wrap"><h1>◈ KAIA VALE</h1>'
                '<p class="kv-muted">Neon Studio</p>', unsafe_allow_html=True)
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
    st.markdown('<div class="gcard">Sin jobs sincronizados todavía.</div>', unsafe_allow_html=True)
    code = gh_status("snapshot.json")
    st.warning(f"GitHub API: HTTP {code} — 401=token inválido, 404=repo mal, -1=sin conexión.")
    st.stop()

job_ids = [j["job_id"] for j in jobs]
jid = job_ids[0] if len(job_ids) == 1 else st.selectbox("Job", job_ids)
job = next(j for j in jobs if j["job_id"] == jid)
versions = job.get("versions", [])
cur = versions[-1]["version"] if versions else None
if not st.session_state.sel_ver or not any(v["version"] == st.session_state.sel_ver for v in versions):
    st.session_state.sel_ver = cur
sel = st.session_state.sel_ver
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


def gstatus():
    s = state.get("state", "")
    if s == "APPROVED":
        return ("APPROVED", "g", True)
    if _decision_pending() or s == "ELVIN_DECISION_REQUIRED":
        return ("VEREDICTO PENDIENTE", "a", True)
    if not IS_LIVE:
        return ("EN ESPERA", "gr", False)
    if s in ("GENERATING", "CORRECTING"):
        return ("GENERANDO", "g", True)
    if s in ("REVIEWING", "VALIDATING", "ESCALATED_INTERNAL"):
        return ("REVISANDO", "b", True)
    return ("EN ESPERA", "gr", False)


def send_decision(action: str, note: str) -> None:
    did = str(uuid.uuid4())
    dec = {"decision_id": did, "job_id": jid, "version": cur,
           "action": action, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "note": note.strip()}
    ok, detail = gh_put_json(f"decisions/inbox/{did}.json", dec, f"decision {action} {jid} {cur}")
    if ok:
        st.success("✅ Decisión enviada. El ACK aparecerá aquí en ~1 min.")
    else:
        st.error(f"No se pudo enviar. {detail}")


def asset_path(vn):
    mp4 = gh_raw(f"jobs/{jid}/versions/{vn}/asset.mp4")
    if mp4:
        return ("video", f"jobs/{jid}/versions/{vn}/asset.mp4")
    png = gh_raw(f"jobs/{jid}/versions/{vn}/asset.png")
    return ("image", f"jobs/{jid}/versions/{vn}/asset.png") if png else (None, None)


def vbadge(v):
    m = {"READY_FOR_ELVIN_REVIEW": ("LISTA PARA TI", "gold"),
         "CORREGIR": ("CORREGIR", "red"), "ESCALAR": ("ESCALAR", "red"),
         "APROBADO": ("APROBADA", "green"), "ESCALATED_INTERNAL": ("EN REVISIÓN", "blue")}
    t, c = m.get(v, (v or "—", "gray"))
    return f'<span class="vbadge {c}">{t}</span>'


def build_events():
    evs = []
    for v in versions:
        m = gh_json(f"jobs/{jid}/versions/{v['version']}/meta.json") or {}
        if m.get("registered"):
            evs.append((m["registered"], "g", f"◈ {v['version']} renderizada"))
    for d in disag:
        if d.get("job_id") == jid and d.get("ts"):
            cl = d.get("clase", "")
            txt = {"missed_by_muse": f"QA marcó CORREGIR en {d.get('version')}",
                   "acuerdo": f"QA aprobó {d.get('version')}",
                   "supervisor_false_positive": f"QA marcó · Muse discrepa ({d.get('version')})",
                   "human_caught_miss": f"Elvin detectó fallo en {d.get('version')}",
                   "human_calibration_positive": f"Elvin aprobó {d.get('version')}",
                   "user_overrule": f"Elvin decidió sobre {d.get('version')}"}.get(cl, f"{cl}")
            kc = "r" if cl in ("missed_by_muse", "human_caught_miss") else ("g" if cl == "acuerdo" else "a")
            evs.append((d["ts"], kc, txt))
    evs.sort(key=lambda x: x[0])
    return evs


pending = _decision_pending()
glabel, gcls, gactive = gstatus()

# ---------------- top bar ----------------
st.markdown(f"""<div class="topbar">
  <div class="logo">◈ KAIA VALE</div>
  <div class="spacer"></div>
  <span class="orb {gcls}"><span class="d"></span>{glabel}</span>
  </div>""", unsafe_allow_html=True)

# Banner decisión de Muse (SÍ/NO)
if ms.get("status") == "BLOCKED_ON_ELVIN" and ms.get("needs_decision"):
    _q = ms.get("needs_decision", "")
    st.markdown(f"""<div class="gcard" style="border-color:rgba(251,191,36,.45)">
      <h4 style="color:var(--amber)">⚠ Muse necesita tu decisión</h4>
      <div style="font-weight:700">{_q[:280]}</div></div>""", unsafe_allow_html=True)
    _b1, _b2 = st.columns(2)
    if _b1.button("✅ SÍ", key="elvin_yes", type="primary", use_container_width=True):
        _ok, _d = gh_put_json("progress/elvin_answer.json",
            {"question": _q, "answer": "yes",
             "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, "elvin answer: yes")
        st.success("✅ Enviada: SÍ.") if _ok else st.error(f"No se pudo enviar. {_d}")
    if _b2.button("❌ NO", key="elvin_no", use_container_width=True):
        _ok, _d = gh_put_json("progress/elvin_answer.json",
            {"question": _q, "answer": "no",
             "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, "elvin answer: no")
        st.success("Enviada: NO.") if _ok else st.error(f"No se pudo enviar. {_d}")

# ---------------- nav ----------------
NAV = [("studio", "◈", "Studio"), ("renders", "▦", "Renders"),
       ("queue", "≋", "Queue"), ("model", "✦", "Model")]
st.markdown('<div class="dnav">', unsafe_allow_html=True)
_dc = st.columns(4)
for i, (t, ic, label) in enumerate(NAV):
    if _dc[i].button(f"{ic} {label}", key=f"dnav_{t}", use_container_width=True,
                      type="primary" if TAB == t else "secondary"):
        st.session_state.tab = t
        st.rerun()
st.markdown('</div>', unsafe_allow_html=True)
st.markdown('<div class="mnav">', unsafe_allow_html=True)
_mc = st.columns(4)
for i, (t, ic, label) in enumerate(NAV):
    if _mc[i].button(f"{ic}\n{label}", key=f"mnav_{t}", use_container_width=True,
                      type="primary" if TAB == t else "secondary"):
        st.session_state.tab = t
        st.rerun()
st.markdown('</div>', unsafe_allow_html=True)

# ================= STUDIO (héroe + filmstrip + queue) =================
if TAB == "studio":
    vinfo = next((x for x in versions if x["version"] == sel), {})
    mtype, mpath = asset_path(sel)
    hb = hero_b64(mpath, 900) if mtype == "image" else None
    vd = gh_json(f"jobs/{jid}/versions/{sel}/verdict.json") or {}
    meta = gh_json(f"jobs/{jid}/versions/{sel}/meta.json") or {}
    conf = vd.get("confianza", "—")
    if hb:
        st.markdown(f"""<div class="hero">
          <img src="data:image/jpeg;base64,{hb}" alt="{sel}">
          <div class="shade"></div>
          <div class="cap"><div class="v">{sel}</div>
          <div class="row">{vbadge(vinfo.get("veredicto_efectivo"))}
          <span class="vbadge gray">conf {conf}</span></div>
          <div class="meta-line">{jid} · {meta.get("params", {}).get("model", "krea 2")} · {hace_str(hours_since(meta.get("registered")))}</div>
          </div></div>""", unsafe_allow_html=True)
    elif mtype == "image":
        st.image(gh_raw(mpath), use_container_width=True)
        st.markdown(f"""<div style="display:flex;align-items:center;gap:10px;margin:8px 0;flex-wrap:wrap">
          <div class="kv-big" style="font-size:1.3rem">{sel}</div>
          {vbadge(vinfo.get("veredicto_efectivo"))}</div>""", unsafe_allow_html=True)
    elif mtype == "video":
        st.video(gh_raw(mpath))
        st.markdown(f"<div class='kv-big' style='font-size:1.3rem'>{sel}</div>", unsafe_allow_html=True)
    else:
        st.info("Render aún no sincronizado.")

    # filmstrip
    st.markdown('<div class="sect">Todos los renders</div><div class="fstrip">', unsafe_allow_html=True)
    items = []
    for v in reversed(versions):
        vn = v["version"]
        _, p = asset_path(vn)
        t = thumb_b64(p, 236) if p else None
        if t:
            items.append(f'<div class="fitem{" sel" if vn == sel else ""}">'
                         f'<img src="data:image/jpeg;base64,{t}" alt="{vn}">'
                         f'<div class="fv">{vn}</div></div>')
    st.markdown("".join(items) + "</div>", unsafe_allow_html=True)
    st.caption("↑ Vista general · selecciona abajo para ver en grande")
    # selector (pills nativo si existe)
    try:
        pick = st.pills("Seleccionar render", [v["version"] for v in reversed(versions)],
                        default=sel, key="fpick")
    except Exception:
        pick = st.selectbox("Seleccionar render", [v["version"] for v in reversed(versions)],
                            index=[v["version"] for v in reversed(versions)].index(sel), key="fpick2")
    if pick and pick != sel:
        st.session_state.sel_ver = pick
        st.rerun()

    # verdict panel
    if pending:
        st.markdown(f"""<div class="verdict"><h3>◈ Veredicto</h3>
          <div class="sub">{cur} superó QA · tu decisión la publica</div></div>""",
                    unsafe_allow_html=True)
        halls = vd.get("hallazgos", []) if sel == cur else (gh_json(f"jobs/{jid}/versions/{cur}/verdict.json") or {}).get("hallazgos", [])
        if halls:
            for h in halls[:3]:
                st.markdown(f"• **{h.get('categoria','')}**: {h.get('descripcion','')[:130]}")
        else:
            st.markdown("<div class='kv-muted'>Sin hallazgos bloqueantes.</div>", unsafe_allow_html=True)
        with st.expander("✏️ Instrucciones (solo si pides cambios)"):
            st.text_input("instrucciones", key=f"vc_note_{jid}_{cur}",
                          label_visibility="collapsed", placeholder="Describe los cambios…")
        b1, b2, b3 = st.columns(3)
        if b1.button("✅ APROBAR", key=f"vc_ap_{jid}_{cur}", type="primary", use_container_width=True):
            send_decision("approve_final", "")
        if b2.button("🔄 CAMBIOS", key=f"vc_rc_{jid}_{cur}", use_container_width=True):
            nn = st.session_state.get(f"vc_note_{jid}_{cur}", "")
            st.error("Escribe las instrucciones primero.") if not nn.strip() else send_decision("request_changes", nn)
        if b3.button("❌ RECHAZAR", key=f"vc_rj_{jid}_{cur}", use_container_width=True):
            send_decision("reject", "")

    # queue stepper
    st.markdown('<div class="sect">Queue</div>', unsafe_allow_html=True)
    nodes = [("Muse", "brief + concepto"), ("Generar", "krea 2"), ("QC", "validación local"),
             ("QA", "supervisor"), ("Fix", "corrección"), ("Verdicto", "Elvin")]
    active_idx = {"GENERANDO": 1, "REVISANDO": 3, "VEREDICTO PENDIENTE": 5}.get(glabel, -1)
    if glabel == "GENERANDO" and vinfo.get("veredicto_efectivo") == "CORREGIR":
        active_idx = 4
    all_done = glabel == "APPROVED"
    qs = '<div class="gcard">'
    for i, (n, s) in enumerate(nodes):
        cls = "on" if i == active_idx else ("done" if (0 <= active_idx and i < active_idx) or all_done else "")
        qs += (f'<div class="qstep {cls}"><div class="n">{i+1}</div>'
               f'<div><div class="t">{n}</div><div class="s">{s}</div></div></div>')
    st.markdown(qs + "</div>", unsafe_allow_html=True)

    # muse mini status
    mstatus = ms.get("status", "—")
    mh = hours_since(ms.get("last_heartbeat")) if ms.get("last_heartbeat") else 999.0
    st.markdown(f"""<div class="gcard"><h4>🤖 Muse · {mstatus}</h4>
      <div class="kv-muted">{(ms.get("current_step") or "—")[:110]}</div>
      <div class="kv-muted" style="margin-top:4px;font-size:.76rem">heartbeat {hace_str(mh)}</div></div>""",
                unsafe_allow_html=True)

# ================= RENDERS (detalle) =================
elif TAB == "renders":
    vinfo = next((x for x in versions if x["version"] == sel), {})
    meta = gh_json(f"jobs/{jid}/versions/{sel}/meta.json") or {}
    vd = gh_json(f"jobs/{jid}/versions/{sel}/verdict.json") or {}
    dec = gh_json(f"jobs/{jid}/versions/{sel}/decision.json") or {}
    audit = gh_json(f"jobs/{jid}/versions/{sel}/audit.json") or {}
    mtype, mpath = asset_path(sel)
    st.markdown(f"""<div style="display:flex;align-items:center;gap:10px;margin:2px 0 10px;flex-wrap:wrap">
      <div class="kv-big" style="font-size:1.3rem">{sel}</div>{vbadge(vinfo.get("veredicto_efectivo"))}</div>""",
                unsafe_allow_html=True)
    if mtype == "image":
        st.image(gh_raw(mpath), use_container_width=True)
    elif mtype == "video":
        st.video(gh_raw(mpath))
    else:
        st.info("Aún no sincronizado.")
    params = meta.get("params", {})
    halls = vd.get("hallazgos", [])
    cov = vd.get("visual_coverage") or {}
    npass = sum(1 for c in cov.values() if isinstance(c, dict)
                for v2 in c.values() if isinstance(v2, dict) and v2.get("estado") == "PASS")
    nfail = sum(1 for c in cov.values() if isinstance(c, dict)
                for v2 in c.values() if isinstance(v2, dict) and v2.get("estado") == "FAIL")
    cost = dec.get("costo_usd_estimado", "—")
    st.markdown(f"""<div class="gcard"><h4>Specs</h4><div class="spec">
      <div><div class="k">Modelo</div><div class="v">{params.get("model", "—")}</div></div>
      <div><div class="k">Resolución</div><div class="v">{(audit.get("asset_original", {}) or {}).get("resolucion", "—")}</div></div>
      <div><div class="k">Confidence</div><div class="v">{vd.get("confianza", "—")}</div></div>
      <div><div class="k">Costo</div><div class="v">{f"${cost:.4f}" if isinstance(cost, (int, float)) else cost}</div></div>
      <div><div class="k">Defectos</div><div class="v">{len(halls)}</div></div>
      <div><div class="k">QA coverage</div><div class="v">{f"{npass}✓ {nfail}✗" if cov else "—"}</div></div>
      </div></div>""", unsafe_allow_html=True)
    if halls:
        hh = '<div class="gcard"><h4>Hallazgos QA</h4>'
        for h in halls:
            hh += f"<div style='margin-bottom:8px'>• <b>{h.get('categoria','')}</b> <span class='kv-muted'>({h.get('severidad','')})</span><br><span class='kv-muted'>{h.get('descripcion','')[:200]}</span></div>"
        st.markdown(hh + "</div>", unsafe_allow_html=True)
    tr = vd.get("temporal_review") or {}
    if tr:
        with st.expander("🎬 Video QA"):
            for cat, c in tr.items():
                if isinstance(c, dict):
                    ic = {"PASS": "✅", "FAIL": "❌", "NOT_VERIFIABLE": "⚠️"}.get(c.get("estado"), "▫")
                    st.markdown(f"{ic} **{cat}** — {c.get('estado')}")

# ================= QUEUE (actividad) =================
elif TAB == "queue":
    st.markdown(f"""<div class="gcard"><h4>Estado del job</h4>
      <span class="orb {gcls}"><span class="d"></span>{glabel}</span>
      <div class="kv-muted" style="margin-top:8px">Última actualización {hace_str(STATE_AGE_H)}</div></div>""",
                unsafe_allow_html=True)
    evs = build_events()
    tl = '<div class="gcard"><h4>Render log</h4><div class="tl">'
    for ts, kc, txt in evs[-25:]:
        tl += (f'<div class="tl-ev {kc}"><span class="tl-time">{fmt_ts(ts)}</span> '
               f'<span class="tl-txt">{txt}</span></div>')
    st.markdown(tl + "</div></div>", unsafe_allow_html=True)
    ev = gh_json(f"jobs/{jid}/events.json") or {"lines": []}
    with st.expander("Log técnico"):
        st.code("\n".join(ev.get("lines", [])[-40:]))

# ================= MODEL (aprendizaje) =================
elif TAB == "model":
    fase = metrics.get("fase", phase.get("fase", "?"))
    st.markdown(f"""<div class="gcard" style="text-align:center;padding:26px">
      <div class="kv-big" style="font-size:1.1rem">{fase}</div>
      <div class="kv-muted">{"Supervisión total" if fase == "FASE_1" else ""}</div></div>""",
                unsafe_allow_html=True)
    pct = metrics.get("acuerdo_pct")
    try:
        pnum = int(float(pct)) if pct not in (None, "?", "") else 0
    except Exception:
        pnum = 0
    ring_c = "var(--green)" if pnum >= 80 else ("var(--amber)" if pnum >= 50 else "var(--violet)")
    hcm = metrics.get("human_caught_miss", 0)
    st.markdown(f"""<div class="gcard"><h4>Muse ↔ QA</h4><div class="ringwrap">
      <div class="ring" style="--p:{pnum};--c:{ring_c}"><span>{pct if pct not in (None,'') else '—'}%</span></div>
      <div><div style="font-weight:800">acuerdo acumulado</div>
      <div class="kv-muted">{metrics.get("revisiones_totales", 0)} revisiones · {metrics.get("reglas_aprendidas", 0)} reglas</div></div>
      </div></div>""", unsafe_allow_html=True)
    fp = metrics.get("falsos_positivos_muse", 0) + metrics.get("falsos_positivos_supervisor", 0)
    st.markdown(f"""<div class="grid2">
      <div class="gcard"><h4>Costo QA</h4><div class="kv-big">${metrics.get("costo_supervisor_total_usd", 0):.4f}</div></div>
      <div class="gcard"><h4>Elvin caught</h4><div class="kv-big" style="{'color:var(--red)' if hcm else ''}">{hcm}</div>
        <div class="kv-muted">bloquea FASE_1</div></div>
      <div class="gcard"><h4>Falsos +</h4><div class="kv-big">{fp}</div></div>
      <div class="gcard"><h4>Sin desacuerdo</h4><div class="kv-big">{metrics.get("jobs_consecutivos_sin_desacuerdo", 0)}</div></div>
      </div>""", unsafe_allow_html=True)
    n_sup = sum(1 for d in disag if d.get("clase") == "missed_by_muse")
    n_elv = sum(1 for d in disag if d.get("clase") == "human_caught_miss")
    n_muse = metrics.get("llamadas_evitadas", 0)
    st.markdown(f"""<div class="gcard"><h4>Quién lo detectó</h4><div class="grid3">
      <div><div class="kv-big" style="color:var(--green);font-size:1.3rem">{n_muse}</div><div class="kv-muted">Muse</div></div>
      <div><div class="kv-big" style="color:var(--cyan);font-size:1.3rem">{n_sup}</div><div class="kv-muted">QA</div></div>
      <div><div class="kv-big" style="color:var(--amber);font-size:1.3rem">{n_elv}</div><div class="kv-muted">Elvin</div></div>
      </div></div>""", unsafe_allow_html=True)
    with st.expander("Reglas aprendidas"):
        for r in rules_l:
            if r.get("activa"):
                st.markdown(f"**{r['id']}** — {r['regla'][:200]}")

# ---------------- auto-refresh ----------------
st.caption("Auto-refresh ~30s · Neon Studio v4")
time.sleep(30)
st.rerun()
