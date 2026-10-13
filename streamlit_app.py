"""KAIA VALE — MISSION CONTROL v5 (2026-10-12).

Workspace de generacion IA. Arquitectura aprobada por Elvin.

Desktop: rail pipeline compacto | LIVE CANVAS ~65% | inspector colapsable.
Review mode automatico en READY_FOR_ELVIN_REVIEW.
Mobile: layout propio, asset protagonista, acciones sticky, inspector en expander.
Analytics solo en Model. Estados LIVE reales. Sin actividad simulada.

Intacto: sync daemon, GitHub inbox, ACK, approve/reject/request_changes,
auto-refresh, historial, supervisor, backend.
"""
import base64
import io
import json
import time
import uuid
from datetime import datetime

import requests
import streamlit as st

st.set_page_config(page_title="Kaia Vale · Mission Control", layout="wide",
                   initial_sidebar_state="collapsed")

try:
    PASSWORD = st.secrets["DASHBOARD_PASSWORD"]
    TOKEN = st.secrets["GITHUB_TOKEN"]
    REPO = st.secrets["SYNC_REPO"]
except Exception:
    st.error("Faltan secretos: DASHBOARD_PASSWORD, GITHUB_TOKEN, SYNC_REPO en Settings -> Secrets.")
    st.stop()

API = f"https://api.github.com/repos/{REPO}/contents"
H = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github.raw"}

for k, v in [("tab", "studio"), ("sel_ver", None), ("insp_open", True),
             ("pipe_sel", None), ("cmp", None), ("focus", False)]:
    if k not in st.session_state:
        st.session_state[k] = v
TAB = st.session_state.tab
if TAB not in ("studio", "queue", "model"):
    TAB = "studio"; st.session_state.tab = "studio"

st.markdown("""<style>
:root{--bg:#0a0a10;--s1:#101018;--s2:#17171f;--tx:#f0f1f6;--mu:#9aa0b8;--ft:#62687e;
--vi:#8b5cf6;--cy:#22d3ee;--grn:#4ade80;--red:#f87171;--amb:#fbbf24;}
html,body,[data-testid="stAppViewContainer"]{background:var(--bg);color:var(--tx);
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;}
[data-testid="stHeader"],#MainMenu,footer{visibility:hidden;display:none;}
.block-container{padding:.5rem .9rem 2rem;max-width:1700px;}
@keyframes fadeUp{from{opacity:0;transform:translateY(8px);}to{opacity:1;transform:none;}}
@keyframes pulseDot{0%,100%{opacity:.5;}50%{opacity:1;}}
.fade{animation:fadeUp .3s ease both;}
.topbar{position:sticky;top:0;z-index:900;display:flex;align-items:center;gap:10px;
padding:8px 2px;margin:-.5rem -.9rem .6rem;background:rgba(10,10,16,.92);
backdrop-filter:blur(14px);border-bottom:1px solid rgba(255,255,255,.06);}
.topbar .logo{font-weight:900;font-size:.92rem;letter-spacing:.1em;white-space:nowrap;}
.topbar .logo em{font-style:normal;background:linear-gradient(120deg,var(--vi),var(--cy));
-webkit-background-clip:text;background-clip:text;color:transparent;}
.topbar .sp{flex:1;}
.livedot{width:8px;height:8px;border-radius:50%;background:var(--grn);
box-shadow:0 0 10px var(--grn);animation:pulseDot 1.8s infinite;display:inline-block;}
.statuspill{display:inline-flex;align-items:center;gap:8px;font-size:.78rem;font-weight:700;
padding:6px 13px;border-radius:999px;background:var(--s2);white-space:nowrap;}
.topmeta{font-size:.78rem;color:var(--mu);white-space:nowrap;}
.railbtn .stButton>button{width:52px;height:54px;border-radius:14px;font-size:1.05rem;
background:var(--s1);border:1px solid rgba(255,255,255,.08);color:var(--mu);padding:0;}
.railbtn .stButton>button[kind="primary"]{background:rgba(139,92,246,.18);color:#fff;
border-color:var(--vi);box-shadow:0 0 12px rgba(139,92,246,.35);}
.rdetail{font-size:.76rem;color:var(--mu);background:var(--s1);border-radius:12px;
padding:10px 12px;line-height:1.55;margin-top:4px;}
.rdetail b{color:var(--tx);}
.stagebox{background:#07070c;border-radius:16px;padding:10px;display:flex;
align-items:center;justify-content:center;min-height:46vh;}
.stagebox img{max-height:68vh;object-fit:contain;border-radius:10px;animation:fadeUp .35s ease;}
.cbar{display:flex;align-items:center;gap:8px;margin-top:8px;flex-wrap:wrap;}
.cbadge{background:var(--s2);border-radius:999px;padding:5px 12px;font-size:.74rem;font-weight:800;}
.cbadge.gold{color:#f0c76a;}.cbadge.green{color:var(--grn);}.cbadge.red{color:var(--red);}
.cbadge.blue{color:var(--cy);}.cbadge.gray{color:var(--mu);}
.fstrip{display:flex;gap:8px;overflow-x:auto;padding:8px 2px;}
.fstrip img{width:60px;height:80px;object-fit:cover;border-radius:8px;flex:0 0 auto;
opacity:.5;border:2px solid transparent;}
.fstrip img.sel{opacity:1;border-color:var(--vi);}
.insp{background:var(--s1);border-radius:14px;padding:13px;}
.insp h5{font-size:.66rem;text-transform:uppercase;letter-spacing:.1em;color:var(--mu);margin:0 0 8px;}
.insp .vname{font-size:1.12rem;font-weight:800;}
.qcrow{display:flex;justify-content:space-between;font-size:.83rem;padding:6px 9px;
background:var(--s2);border-radius:9px;margin-bottom:6px;}
.ok{color:var(--grn);}.bad{color:var(--red);}.wrn{color:var(--amb);}
.find{font-size:.79rem;color:var(--mu);padding:5px 0;border-bottom:1px solid rgba(255,255,255,.05);line-height:1.45;}
.spec2{display:grid;grid-template-columns:1fr 1fr;gap:7px;font-size:.79rem;margin-top:6px;}
.spec2 .k{color:var(--ft);font-size:.62rem;text-transform:uppercase;letter-spacing:.05em;}
.spec2 .v{font-weight:700;}
.livebar{display:flex;align-items:center;gap:10px;margin-top:8px;padding:8px 13px;
background:var(--s1);border-radius:11px;font-size:.81rem;color:var(--mu);}
.livebar b{color:var(--tx);}
.rvhead{text-align:center;padding:6px 0 2px;}
.rvhead h3{margin:0;font-size:1.15rem;}
.rvhead p{color:var(--mu);font-size:.84rem;margin:2px 0 0;}
.stButton>button{background:var(--s2);color:var(--tx);border:1px solid rgba(255,255,255,.1);
border-radius:12px;min-height:48px;font-weight:700;font-size:.88rem;width:100%;}
.stButton>button:hover{border-color:var(--vi);}
.stButton>button:active{transform:scale(.98);}
.stButton>button[kind="primary"]{background:linear-gradient(120deg,var(--vi),#6d3ff5);color:#fff;border:none;}
.stTextInput>div>div>input{background:var(--s2);color:var(--tx);
border:1px solid rgba(255,255,255,.1);border-radius:11px;}
.stExpander{border:1px solid rgba(255,255,255,.08);border-radius:13px;background:var(--s1);}
[data-testid="stImage"] img{border-radius:12px;}
code{color:#c4b5fd!important;}
.only-m{display:none!important;}
@media(max-width:767px){
.only-d{display:none!important;}.only-m{display:block!important;}
.block-container{padding:.4rem .5rem 7rem;}
.m-canvas img{width:100%;border-radius:14px;max-height:60vh;object-fit:cover;animation:fadeUp .35s ease;}
.m-strip{display:flex;gap:7px;overflow-x:auto;padding:9px 2px;}
.m-strip img{width:54px;height:72px;object-fit:cover;border-radius:8px;flex:0 0 auto;opacity:.5;border:2px solid transparent;}
.m-strip img.sel{opacity:1;border-color:var(--vi);}
.m-anchor + div[data-testid="stVerticalBlock"]{position:sticky;bottom:0;z-index:900;
background:rgba(10,10,16,.95);backdrop-filter:blur(14px);margin:0 -.5rem;
padding:9px .5rem calc(9px + env(safe-area-inset-bottom));border-top:1px solid rgba(255,255,255,.08);}
.m-anchor + div[data-testid="stVerticalBlock"] .stButton>button{min-height:54px;font-size:.95rem;}
.mnav{position:fixed;left:10px;right:10px;bottom:calc(8px + env(safe-area-inset-bottom));z-index:940;
display:flex;background:rgba(18,18,28,.93);backdrop-filter:blur(16px);
border:1px solid rgba(255,255,255,.1);border-radius:18px;padding:5px;}
.mnav button{flex:1;background:none!important;border:none!important;color:var(--mu);
font-size:.58rem;font-weight:800;padding:8px 0;border-radius:13px;min-height:0;}
.mnav button[kind="primary"]{background:rgba(139,92,246,.22)!important;color:#d6c9ff!important;}
}
@media(min-width:768px){.dnav{display:flex;gap:2px;}
.dnav button{background:none;border:none;color:var(--mu);border-radius:9px;padding:7px 13px;font-weight:700;font-size:.8rem;}
.dnav button[kind="primary"]{background:var(--s2);color:var(--tx);}}
.login-wrap{max-width:340px;margin:12vh auto;padding:28px;background:var(--s1);border-radius:18px;text-align:center;}
</style>""", unsafe_allow_html=True)

# ---------------- github ----------------
@st.cache_data(ttl=20)
def gh_raw(path):
    r = requests.get(f"{API}/{path}?ref=main", headers=H, timeout=20)
    return r.content if r.status_code == 200 else None

def gh_json(path):
    b = gh_raw(path)
    return json.loads(b.decode()) if b else None

def gh_put_json(path, obj, msg):
    content = base64.b64encode(json.dumps(obj, ensure_ascii=False, indent=1).encode()).decode()
    body = {"message": msg, "content": content}
    try:
        ex = gh_json_raw(path)
        if ex and ex.get("sha"):
            body["sha"] = ex["sha"]
    except Exception:
        pass
    try:
        r = requests.put(f"{API}/{path}", headers={**H, "Accept": "application/vnd.github+json"},
                         json=body, timeout=20)
    except Exception as e:
        return (False, f"sin conexion: {e.__class__.__name__}")
    if r.status_code in (200, 201):
        return (True, "ok")
    try:
        detail = r.json().get("message", "")[:140]
    except Exception:
        detail = r.text[:140]
    hint = {401: "token invalido", 403: "token sin escritura", 404: "repo/ruta mal"}.get(r.status_code, "")
    return (False, f"HTTP {r.status_code}: {detail} {hint}".strip())

def gh_json_raw(path):
    r = requests.get(f"{API}/{path}", headers=H, timeout=20)
    return r.json() if r.status_code == 200 else None

@st.cache_data(ttl=120)
def thumb_b64(path, w=120):
    try:
        from PIL import Image
        b = gh_raw(path)
        if not b:
            return None
        im = Image.open(io.BytesIO(b)).convert("RGB")
        im.thumbnail((w, w * 2), Image.LANCZOS)
        buf = io.BytesIO(); im.save(buf, "JPEG", quality=60)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None

# ---------------- auth ----------------
if "auth" not in st.session_state:
    st.session_state.auth = False
if not st.session_state.auth:
    st.markdown('<div class="login-wrap"><h1>KAIA VALE</h1><p style="color:var(--mu)">Mission Control</p></div>',
                unsafe_allow_html=True)
    with st.form("login"):
        pw = st.text_input("Password", type="password", label_visibility="collapsed", placeholder="Password")
        go = st.form_submit_button("Entrar")
    st.markdown('</div>', unsafe_allow_html=True)
    if go:
        if pw == PASSWORD:
            st.session_state.auth = True; st.rerun()
        else:
            st.error("Password incorrecto.")
    st.stop()

# ---------------- datos ----------------
snap = gh_json("snapshot.json") or {"jobs": []}
budget = gh_json("budget.json") or {}
jobs = snap.get("jobs", [])
if not jobs:
    st.info("Sin jobs sincronizados.")
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
rules_l = gh_json("learning/rules.json") or []
disag = gh_json("learning/disagreements.json") or []
ms = gh_json("progress/muse_status.json") or {}

def is_pending():
    ci = next((x for x in versions if x["version"] == cur), {})
    return ci.get("veredicto_efectivo") == "READY_FOR_ELVIN_REVIEW" and not ci.get("decidido")

def hsince(iso):
    try:
        from datetime import timezone
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except Exception:
        return 999.0

def hace(h):
    if h >= 999: return "?"
    m = int(h * 60)
    if m < 1: return "ahora"
    if m < 60: return f"{m} min"
    if h < 24: return f"{int(h)} h"
    return f"{int(h/24)} d"

AGE = hsince(state.get("updated"))
LIVE = AGE < 0.25
PEND = is_pending()

def live_state():
    s = state.get("state", ""); mst = ms.get("status", "")
    if PEND or s == "ELVIN_DECISION_REQUIRED" or mst == "BLOCKED_ON_ELVIN":
        return "Waiting for Elvin"
    if not LIVE: return "Idle"
    if s == "GENERATING": return "Generating"
    if mst in ("VALIDATING", "CORRECTING"): return "Muse QC"
    if mst == "SUPERVISOR_REVIEW" or s == "REVIEWING": return "Supervisor reviewing"
    if mst == "WORKING": return "Working"
    if mst == "WAITING_ON_TOOL": return "Waiting: " + str(ms.get("waiting_on") or "")
    return "Idle"

LIVE_LBL = live_state()
MSTEP = ms.get("current_step") or ""

def send_decision(action, note=""):
    did = str(uuid.uuid4())
    dec = {"decision_id": did, "job_id": jid, "version": cur, "action": action,
           "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "note": note.strip()}
    ok, detail = gh_put_json(f"decisions/inbox/{did}.json", dec, f"decision {action} {jid} {cur}")
    st.success("Decision enviada. ACK en ~1 min.") if ok else st.error(f"No se pudo enviar. {detail}")

def apath(vn):
    if gh_raw(f"jobs/{jid}/versions/{vn}/asset.mp4"): return ("video", f"jobs/{jid}/versions/{vn}/asset.mp4")
    if gh_raw(f"jobs/{jid}/versions/{vn}/asset.png"): return ("image", f"jobs/{jid}/versions/{vn}/asset.png")
    return (None, None)

def vcls(v):
    return {"READY_FOR_ELVIN_REVIEW": "gold", "CORREGIR": "red", "ESCALAR": "red",
            "APROBADO": "green", "ESCALATED_INTERNAL": "blue"}.get(v, "gray")
def vlab(v):
    return {"READY_FOR_ELVIN_REVIEW": "READY", "CORREGIR": "CORREGIR", "ESCALAR": "ESCALAR",
            "APROBADO": "APROBADA", "ESCALATED_INTERNAL": "EN REVISION"}.get(v, v or "--")

def pipe_stages():
    ci = next((x for x in versions if x["version"] == cur), {})
    ve = ci.get("veredicto_efectivo", "")
    vd = gh_json(f"jobs/{jid}/versions/{cur}/verdict.json") or {} if cur else {}
    s = state.get("state", "")
    has_v = bool(versions)
    return [
        ("brief", "◈", "Brief", has_v and s != "GENERATING",
         f"<b>Concepto</b><br>{jid}<br>{len(versions)} versiones"),
        ("gen", "⬢", "Generate", has_v,
         f"<b>Modelo</b><br>krea 2<br>{len(versions)} renders"),
        ("qc", "◐", "Muse QC", bool(vd),
         f"<b>Hallazgos:</b> {len(vd.get('hallazgos', []))}<br><b>Conf:</b> {vd.get('confianza', '--')}"),
        ("sup", "⬣", "Supervisor", ve in ("CORREGIR", "READY_FOR_ELVIN_REVIEW", "APROBADO"),
         f"<b>Veredicto:</b> {vlab(ve)}<br><b>Costo:</b> ${metrics.get('costo_supervisor_total_usd', 0):.4f}"),
        ("elvin", "◉", "Elvin", PEND or bool(ci.get("decidido")),
         "<b>Tu decision pendiente</b>" if PEND else f"<b>Decision:</b> {vlab(ve)}"),
        ("pub", "➤", "Publish", s == "APPROVED",
         "<b>Estado:</b> " + ("publicado" if s == "APPROVED" else "pendiente")),
    ]

def evts():
    evs = []
    for v in versions:
        m = gh_json(f"jobs/{jid}/versions/{v['version']}/meta.json") or {}
        if m.get("registered"): evs.append((m["registered"], f"{v['version']} renderizada"))
    for d in disag:
        if d.get("job_id") == jid and d.get("ts"):
            evs.append((d["ts"], f"QA {d.get('clase', '')} {d.get('version', '')}"))
    evs.sort(key=lambda x: x[0])
    return evs

# ---------------- top bar ----------------
st.markdown('<div class="topbar"><div class="logo"><em>◈ KAIA VALE</em></div><div class="dnav only-d">',
            unsafe_allow_html=True)
_dc = st.columns(3)
for i, (t, label) in enumerate([("studio", "Studio"), ("queue", "Queue"), ("model", "Model")]):
    if _dc[i].button(label, key=f"dnav_{t}", type="primary" if TAB == t else "secondary"):
        st.session_state.tab = t; st.session_state.cmp = None; st.session_state.focus = False; st.rerun()
st.markdown('</div><div class="sp"></div>', unsafe_allow_html=True)
st.markdown(f"""<span class="statuspill"><span class="livedot"></span>{LIVE_LBL}""" +
            (f""" <span style="color:var(--mu);font-weight:600">· {MSTEP[:38]}</span>""" if MSTEP and LIVE else "") +
            """</span><span class="topmeta only-d">QA $""" +
            f"{budget.get('monthly_used_usd', 0):.2f}</span></div>", unsafe_allow_html=True)
st.markdown('<div class="mnav only-m">', unsafe_allow_html=True)
_mc = st.columns(3)
for i, (t, label) in enumerate([("studio", "Studio"), ("queue", "Queue"), ("model", "Model")]):
    if _mc[i].button(label, key=f"mnav_{t}", type="primary" if TAB == t else "secondary"):
        st.session_state.tab = t; st.session_state.cmp = None; st.session_state.focus = False; st.rerun()
st.markdown('</div>', unsafe_allow_html=True)

# Banner SÍ/NO de Muse
if ms.get("status") == "BLOCKED_ON_ELVIN" and ms.get("needs_decision"):
    _q = ms.get("needs_decision", "")
    st.markdown(f"""<div class="insp" style="border:1px solid rgba(251,191,36,.4);margin-bottom:8px">
      <h5 style="color:var(--amb)">Muse necesita tu decision</h5>
      <div style="font-weight:700;margin-bottom:6px">{_q[:240]}</div></div>""", unsafe_allow_html=True)
    _b1, _b2 = st.columns(2)
    if _b1.button("SI, CONTINUA", key="elvin_yes", type="primary", use_container_width=True):
        _ok, _d = gh_put_json("progress/elvin_answer.json",
            {"question": _q, "answer": "yes",
             "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, "elvin answer: yes")
        st.success("Enviada: SI.") if _ok else st.error(f"No se pudo enviar. {_d}")
    if _b2.button("NO", key="elvin_no", use_container_width=True):
        _ok, _d = gh_put_json("progress/elvin_answer.json",
            {"question": _q, "answer": "no",
             "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, "elvin answer: no")
        st.success("Enviada: NO.") if _ok else st.error(f"No se pudo enviar. {_d}")

# ================================================================ STUDIO
if TAB == "studio":
    vinfo = next((x for x in versions if x["version"] == sel), {})
    mtype, mpath = apath(sel)
    vd = gh_json(f"jobs/{jid}/versions/{sel}/verdict.json") or {}
    meta = gh_json(f"jobs/{jid}/versions/{sel}/meta.json") or {}
    cmpv = st.session_state.cmp
    focus = st.session_state.focus

    # ================= MOBILE =================
    st.markdown('<div class="only-m">', unsafe_allow_html=True)
    st.markdown(f"""<div style="display:flex;align-items:center;gap:8px;padding:6px 2px;
      font-size:.8rem;font-weight:700"><span class="livedot"></span>{LIVE_LBL}
      <span style="color:var(--ft);margin-left:auto">{sel}</span></div>""", unsafe_allow_html=True)
    if focus and st.button("< Volver", key="m_unfocus"):
        st.session_state.focus = False; st.rerun()
    if cmpv and len(cmpv) == 2:
        c1, c2 = st.columns(2)
        for col, vn in zip((c1, c2), cmpv):
            _, p = apath(vn)
            with col:
                st.markdown(f"<div style='text-align:center;font-weight:800;font-size:.8rem'>{vn}</div>",
                            unsafe_allow_html=True)
                if p: st.image(gh_raw(p), use_container_width=True)
        if st.button("Cerrar comparacion", key="m_cmp_off"):
            st.session_state.cmp = None; st.rerun()
    elif mtype == "image":
        st.markdown('<div class="m-canvas fade">', unsafe_allow_html=True)
        st.image(gh_raw(mpath), use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
    elif mtype == "video":
        st.video(gh_raw(mpath))
    else:
        st.info("Render aun no sincronizado.")
    strip = '<div class="m-strip">'
    for v in reversed(versions):
        vn = v["version"]; _, p = apath(vn)
        t = thumb_b64(p) if p else None
        if t:
            strip += f'<img src="data:image/jpeg;base64,{t}" class="{"sel" if vn == sel else ""}">'
    st.markdown(strip + "</div>", unsafe_allow_html=True)
    try:
        mpick = st.pills("v", [v["version"] for v in reversed(versions)],
                         default=sel, key="mpick", label_visibility="collapsed")
    except Exception:
        mpick = st.selectbox("v", [v["version"] for v in reversed(versions)], key="mpick2",
                             label_visibility="collapsed")
    if mpick and mpick != sel:
        st.session_state.sel_ver = mpick; st.rerun()
    # sticky actions
    st.markdown('<div class="m-anchor"></div>', unsafe_allow_html=True)
    with st.container():
        if PEND:
            st.markdown(f"<div style='text-align:center;font-weight:800;margin-bottom:6px'>{cur} · tu decision</div>",
                        unsafe_allow_html=True)
            a1, a2 = st.columns(2)
            if a1.button("APROBAR", key="m_ap", type="primary", use_container_width=True):
                send_decision("approve_final", "")
            if a2.button("RECHAZAR", key="m_rj", use_container_width=True):
                send_decision("reject", "")
            if st.button("PEDIR CAMBIOS", key="m_rc", use_container_width=True):
                st.session_state["m_rc_open"] = not st.session_state.get("m_rc_open", False)
            if st.session_state.get("m_rc_open"):
                nn = st.text_input("cambios", key="m_note", placeholder="Describe los cambios…",
                                   label_visibility="collapsed")
                if st.button("Enviar", key="m_rc_go", type="primary"):
                    if nn.strip(): send_decision("request_changes", nn)
                    else: st.error("Escribe los cambios primero.")
        else:
            b1, b2 = st.columns(2)
            if b1.button("Comparar", key="m_cmp"):
                vs = [v["version"] for v in versions]
                st.session_state.cmp = vs[-2:] if len(vs) >= 2 else None
                st.rerun()
            if b2.button("Fullscreen", key="m_fs"):
                st.session_state.focus = True; st.rerun()
    with st.expander("Detalles / QC"):
        halls = vd.get("hallazgos", []); cov = vd.get("visual_coverage") or {}
        st.markdown(f"**{sel}** · {vlab(vinfo.get('veredicto_efectivo'))}")
        for cat in ("identity", "anatomy", "skin", "hands"):
            it = cov.get(cat, {}) if isinstance(cov.get(cat), dict) else {}
            fl = [k for k, x in it.items() if isinstance(x, dict) and x.get("estado") == "FAIL"]
            st.markdown(f"{'❌' if fl else '✓'} {cat}")
        for h in halls[:4]:
            st.caption(f"• {h.get('categoria')}: {str(h.get('descripcion'))[:110]}")
    st.markdown('</div>', unsafe_allow_html=True)

    # ================= DESKTOP =================
    st.markdown('<div class="only-d">', unsafe_allow_html=True)
    if focus:
        if st.button("< Volver", key="d_unfocus"):
            st.session_state.focus = False; st.rerun()
        if mtype == "image": st.image(gh_raw(mpath), use_container_width=True)
        elif mtype == "video": st.video(gh_raw(mpath))
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        insp_open = st.session_state.insp_open
        cols = st.columns([0.55, 5.2, 2.4] if insp_open else [0.55, 7.6])
        # ---- rail ----
        with cols[0]:
            st.markdown('<div class="railbtn">', unsafe_allow_html=True)
            stages = pipe_stages()
            for sid, icon, label, active, _ in stages:
                mk = "primary" if (st.session_state.pipe_sel == sid or
                                   (not st.session_state.pipe_sel and
                                    ((sid == "elvin" and PEND) or
                                     (sid == "sup" and LIVE_LBL == "Supervisor reviewing") or
                                     (sid == "gen" and LIVE_LBL == "Generating")))) else "secondary"
                if st.button(("✓ " if active and mk == "secondary" else "") + icon,
                             key=f"rail_{sid}", help=label, type=mk):
                    st.session_state.pipe_sel = None if st.session_state.pipe_sel == sid else sid
                    st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)
            if st.session_state.pipe_sel:
                sg = next(s for s in stages if s[0] == st.session_state.pipe_sel)
                st.markdown(f'<div class="rdetail"><b>{sg[2]}</b><br>{sg[4]}</div>',
                            unsafe_allow_html=True)
        # ---- canvas ----
        with cols[1]:
            if cmpv and len(cmpv) == 2:
                c1, c2 = st.columns(2)
                for col, vn in zip((c1, c2), cmpv):
                    _, p = apath(vn)
                    with col:
                        st.markdown(f"<div style='font-weight:800;margin-bottom:4px'>{vn}</div>",
                                    unsafe_allow_html=True)
                        if p: st.image(gh_raw(p), use_container_width=True)
                if st.button("Cerrar comparacion", key="d_cmp_off"):
                    st.session_state.cmp = None; st.rerun()
            elif mtype == "image":
                st.markdown('<div class="stagebox fade">', unsafe_allow_html=True)
                st.image(gh_raw(mpath), use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
            elif mtype == "video":
                st.video(gh_raw(mpath))
            else:
                st.info("Render aun no sincronizado.")
            st.markdown('<div class="cbar">', unsafe_allow_html=True)
            st.markdown(f"""<span class="cbadge {vcls(vinfo.get('veredicto_efectivo'))}">{sel} · {vlab(vinfo.get('veredicto_efectivo'))}</span>
              <span style="color:var(--ft);font-size:.76rem">{hace(AGE)} · {meta.get('params', {}).get('model', 'krea 2')}</span>""",
                        unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
            cb1, cb2, cb3, cb4 = st.columns(4)
            if cb1.button("◐ Comparar", key="d_cmp"):
                vs = [v["version"] for v in versions]
                st.session_state.cmp = vs[-2:] if len(vs) >= 2 else None
                st.rerun()
            if cb2.button("⛶ Fullscreen", key="d_fs"):
                st.session_state.focus = True; st.rerun()
            if cb3.button(("◀ Inspector" if insp_open else "Inspector ▶"), key="d_insp"):
                st.session_state.insp_open = not insp_open; st.rerun()
            # filmstrip
            fs = '<div class="fstrip">'
            for v in reversed(versions):
                vn = v["version"]; _, p = apath(vn)
                t = thumb_b64(p) if p else None
                if t:
                    fs += f'<img src="data:image/jpeg;base64,{t}" class="{"sel" if vn == sel else ""}" title="{vn}">'
            st.markdown(fs + "</div>", unsafe_allow_html=True)
            try:
                dpick = st.pills("vv", [v["version"] for v in reversed(versions)],
                                 default=sel, key="dpick", label_visibility="collapsed")
            except Exception:
                dpick = st.selectbox("vv", [v["version"] for v in reversed(versions)], key="dpick2",
                                     label_visibility="collapsed")
            if dpick and dpick != sel:
                st.session_state.sel_ver = dpick; st.rerun()
            # live bar
            st.markdown(f"""<div class="livebar"><span class="livedot"></span>
              <b>{LIVE_LBL}</b><span>{MSTEP[:90]}</span></div>""", unsafe_allow_html=True)
        # ---- inspector ----
        if insp_open:
            with cols[2]:
                if PEND:
                    st.markdown(f"""<div class="rvhead"><h3>Tu decision</h3>
                      <p>{cur} supero QA · nada secundario aqui</p></div>""", unsafe_allow_html=True)
                    halls = (gh_json(f"jobs/{jid}/versions/{cur}/verdict.json") or {}).get("hallazgos", [])
                    if not halls:
                        st.markdown("<p style='color:var(--grn);font-weight:700'>Sin hallazgos bloqueantes.</p>",
                                    unsafe_allow_html=True)
                    else:
                        for h in halls[:3]:
                            st.markdown(f"<div class='find'>• <b>{h.get('categoria')}</b>: {str(h.get('descripcion'))[:120]}</div>",
                                        unsafe_allow_html=True)
                    if st.button("APROBAR", key="d_ap", type="primary", use_container_width=True):
                        send_decision("approve_final", "")
                    if st.button("PEDIR CAMBIOS", key="d_rc", use_container_width=True):
                        st.session_state["d_rc_open"] = not st.session_state.get("d_rc_open", False)
                    if st.session_state.get("d_rc_open"):
                        nn = st.text_input("c", key="d_note", placeholder="Describe los cambios…",
                                           label_visibility="collapsed")
                        if st.button("Enviar cambios", key="d_rc_go", type="primary"):
                            if nn.strip(): send_decision("request_changes", nn)
                            else: st.error("Escribe los cambios primero.")
                    if st.button("RECHAZAR", key="d_rj", use_container_width=True):
                        send_decision("reject", "")
                else:
                    st.markdown(f"""<div class="insp fade"><h5>Inspector</h5>
                      <div class="vname">{sel}</div>
                      <div style="margin:4px 0 8px"><span class="cbadge {vcls(vinfo.get('veredicto_efectivo'))}">{vlab(vinfo.get('veredicto_efectivo'))}</span></div>""",
                                unsafe_allow_html=True)
                    halls = vd.get("hallazgos", []); cov = vd.get("visual_coverage") or {}
                    st.markdown("<h5>QC</h5>", unsafe_allow_html=True)
                    for cat in ("identity", "anatomy", "skin", "hands"):
                        it = cov.get(cat, {}) if isinstance(cov.get(cat), dict) else {}
                        fl = [k for k, x in it.items() if isinstance(x, dict) and x.get("estado") == "FAIL"]
                        st.markdown(f"<div class='qcrow'><b>{cat}</b><span class='{'bad' if fl else 'ok'}'>{'✗' if fl else '✓'}</span></div>",
                                    unsafe_allow_html=True)
                    if halls:
                        st.markdown("<h5 style='margin-top:10px'>Findings</h5>", unsafe_allow_html=True)
                        for h in halls[:4]:
                            st.markdown(f"<div class='find'>• <b>{h.get('categoria')}</b>: {str(h.get('descripcion'))[:120]}</div>",
                                        unsafe_allow_html=True)
                    cost = (gh_json(f"jobs/{jid}/versions/{sel}/decision.json") or {}).get("costo_usd_estimado", "--")
                    st.markdown(f"""<h5 style='margin-top:10px'>Specs</h5><div class="spec2">
                      <div><div class="k">Modelo</div><div class="v">{meta.get('params', {}).get('model', 'krea 2')}</div></div>
                      <div><div class="k">Conf</div><div class="v">{vd.get('confianza', '--')}</div></div>
                      <div><div class="k">Costo</div><div class="v">{cost}</div></div>
                      <div><div class="k">Render</div><div class="v">{hace(hsince(meta.get('registered')))}</div></div>
                      </div></div>""", unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

# ================================================================ QUEUE
elif TAB == "queue":
    st.markdown(f"""<div class="insp" style="margin-bottom:10px"><h5>Job</h5>
      <div style="display:flex;align-items:center;gap:10px"><b>{jid}</b>
      <span class="cbadge {'green' if LIVE else 'gray'}">{LIVE_LBL}</span></div>
      <div style="color:var(--mu);font-size:.8rem;margin-top:6px">Actualizado {hace(AGE)}</div></div>""",
                unsafe_allow_html=True)
    evs = evts()
    st.markdown('<div class="insp"><h5>Render log</h5>', unsafe_allow_html=True)
    for ts, txt in evs[-25:]:
        try:
            tstr = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).strftime("%H:%M")
        except Exception:
            tstr = "--"
        st.markdown(f"<div class='find'><span style='color:var(--ft)'>{tstr}</span> · {txt}</div>",
                    unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
    with st.expander("Log tecnico"):
        ev = gh_json(f"jobs/{jid}/events.json") or {"lines": []}
        st.code("\n".join(ev.get("lines", [])[-40:]))

# ================================================================ MODEL
elif TAB == "model":
    fase = metrics.get("fase", "?")
    pct = metrics.get("acuerdo_pct", 0) or 0
    hcm = metrics.get("human_caught_miss", 0)
    fp = metrics.get("falsos_positivos_muse", 0) + metrics.get("falsos_positivos_supervisor", 0)
    st.markdown(f"""<div class="insp" style="text-align:center;margin-bottom:10px">
      <h5>Model</h5><div style="font-size:1.4rem;font-weight:800">{fase}</div>
      <div style="color:var(--mu);font-size:.82rem">Acuerdo Muse-QA: <b style="color:var(--tx)">{pct}%</b> ·
      Revisiones: {metrics.get('revisiones_totales', 0)} · Reglas: {metrics.get('reglas_aprendidas', 0)}</div></div>""",
                unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"""<div class="insp"><h5>Costo QA</h5>
          <div style="font-size:1.5rem;font-weight:800">${metrics.get('costo_supervisor_total_usd', 0):.4f}</div></div>""",
                    unsafe_allow_html=True)
        st.markdown(f"""<div class="insp"><h5>Falsos positivos</h5>
          <div style="font-size:1.5rem;font-weight:800">{fp}</div></div>""", unsafe_allow_html=True)
    with c2:
        st.markdown(f"""<div class="insp" {'style="border:1px solid rgba(248,113,113,.35)"' if hcm else ''}><h5>Elvin caught</h5>
          <div style="font-size:1.5rem;font-weight:800;{'color:var(--red)' if hcm else ''}">{hcm}</div>
          <div style="color:var(--mu);font-size:.78rem">bloquea salida de FASE_1</div></div>""",
                    unsafe_allow_html=True)
        st.markdown(f"""<div class="insp"><h5>Sin desacuerdo</h5>
          <div style="font-size:1.5rem;font-weight:800">{metrics.get('jobs_consecutivos_sin_desacuerdo', 0)}</div></div>""",
                    unsafe_allow_html=True)
    with st.expander("Reglas aprendidas"):
        for r in rules_l:
            if r.get("activa"):
                st.markdown(f"**{r['id']}** — {r['regla'][:200]}")

st.caption("Mission Control v5 · auto-refresh 30s")
time.sleep(30)
st.rerun()
