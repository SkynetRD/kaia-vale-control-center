"""KAIA VALE — Mission Control v6.
UI-only rewrite. Keeps GitHub bus, decision protocol and backend contracts unchanged.
"""
import base64, json, time, uuid
from datetime import datetime, timezone
import requests
import streamlit as st

st.set_page_config(page_title="Kaia Vale · Mission Control", layout="wide", initial_sidebar_state="collapsed")

try:
    PASSWORD = st.secrets["DASHBOARD_PASSWORD"]
    TOKEN = st.secrets["GITHUB_TOKEN"]
    REPO = st.secrets["SYNC_REPO"]
except Exception:
    st.error("Faltan DASHBOARD_PASSWORD, GITHUB_TOKEN y SYNC_REPO en Secrets.")
    st.stop()

API = f"https://api.github.com/repos/{REPO}/contents"
H_RAW = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github.raw"}
H_JSON = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"}

DEFAULTS = {"auth": False, "tab": "Studio", "sel_ver": None, "compare": False,
            "focus": False, "inspector": True, "pipe_detail": None, "change_open": False}
for k, v in DEFAULTS.items():
    st.session_state.setdefault(k, v)

st.markdown(r"""<style>
:root{--bg:#08090e;--panel:#10121a;--panel2:#151824;--line:#252a3a;--text:#f5f7ff;--muted:#8e96ad;
--violet:#8b5cf6;--cyan:#22d3ee;--green:#34d399;--red:#fb7185;--amber:#fbbf24}
html,body,[data-testid="stAppViewContainer"]{background:var(--bg);color:var(--text)}
[data-testid="stHeader"],#MainMenu,footer{display:none!important}.block-container{max-width:1800px;padding:.55rem .8rem 1rem}
[data-testid="stVerticalBlock"]{gap:.55rem}.kv-top{display:flex;align-items:center;gap:12px;height:48px;border-bottom:1px solid var(--line);margin-bottom:4px}
.kv-logo{font-weight:900;letter-spacing:.14em}.kv-logo span{background:linear-gradient(90deg,var(--violet),var(--cyan));-webkit-background-clip:text;color:transparent}
.kv-live{margin-left:auto;display:flex;align-items:center;gap:7px;color:var(--muted);font-size:.82rem}.dot{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 10px var(--green)}
[data-testid="stButton"] button{border-radius:10px;border:1px solid var(--line);background:#11131b;color:var(--text);min-height:38px}
[data-testid="stButton"] button:hover{border-color:#545b74}.nav [data-testid="stButton"] button{min-height:36px}
.pipe-title,.ins-title{font-size:.66rem;letter-spacing:.16em;color:var(--muted);font-weight:800;text-transform:uppercase;margin:2px 0 8px}
.pipe-item{display:flex;align-items:center;gap:9px;padding:9px 10px;border-radius:10px;color:var(--muted);font-size:.82rem;margin-bottom:5px;border:1px solid transparent}
.pipe-item.done{color:#b7f7d4}.pipe-item.active{color:white;background:#17152a;border-color:#5b3eb0}.pipe-item.pending{opacity:.58}
.pi{width:19px;height:19px;border-radius:50%;display:grid;place-items:center;border:1px solid #4a5062;font-size:.66rem}.done .pi{border-color:var(--green);color:var(--green)}.active .pi{border-color:var(--violet);background:#6d45db;color:white}
.canvas-shell{background:#05060a;border:1px solid #1d2130;border-radius:16px;padding:8px;min-height:62vh;display:flex;align-items:center;justify-content:center;overflow:hidden}
.canvas-label{display:flex;justify-content:space-between;align-items:center;color:var(--muted);font-size:.75rem;margin:0 2px 5px}.badge{padding:4px 8px;border-radius:999px;background:#171923;border:1px solid var(--line);font-size:.7rem;font-weight:800}
.ins{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:12px}.ins h4{font-size:.9rem;margin:0 0 10px}.qc{display:flex;justify-content:space-between;padding:7px 8px;background:#171923;border-radius:8px;margin:5px 0;font-size:.78rem}.ok{color:var(--green)}.bad{color:var(--red)}
.find{font-size:.76rem;line-height:1.42;color:#c5cada;padding:7px 0;border-bottom:1px solid #202432}.spec{display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:.72rem;color:var(--muted)}.spec b{display:block;color:var(--text);margin-top:2px}
.livebar{display:flex;align-items:center;gap:9px;height:38px;padding:0 12px;background:#0e1017;border:1px solid var(--line);border-radius:11px;color:var(--muted);font-size:.78rem}.livebar b{color:var(--text)}
.review{border:1px solid rgba(139,92,246,.55);background:linear-gradient(90deg,rgba(139,92,246,.09),rgba(34,211,238,.04));border-radius:12px;padding:8px 10px;color:#ddd9ff;font-size:.78rem}
.small{font-size:.72rem;color:var(--muted)}
[data-testid="stImage"] img{max-height:66vh;object-fit:contain!important;background:#05060a;border-radius:10px}
video{max-height:66vh!important;background:#05060a!important;border-radius:10px}
@media(max-width:760px){.block-container{padding:.35rem .45rem 5rem}.kv-top{height:42px}.desktop-only{display:none!important}
.canvas-shell{min-height:0}.ins{border-radius:12px}[data-testid="stImage"] img,video{max-height:64vh!important}.livebar{position:sticky;bottom:4px;z-index:20}.kv-logo{font-size:.8rem}}
</style>""", unsafe_allow_html=True)

@st.cache_data(ttl=20, show_spinner=False)
def gh_raw(path):
    try:
        r = requests.get(f"{API}/{path}?ref=main", headers=H_RAW, timeout=20)
        return r.content if r.status_code == 200 else None
    except requests.RequestException:
        return None

def gh_json(path, default=None):
    b = gh_raw(path)
    if not b: return default
    try: return json.loads(b.decode("utf-8"))
    except Exception: return default

def gh_meta(path):
    try:
        r=requests.get(f"{API}/{path}?ref=main",headers=H_JSON,timeout=20)
        return r.json() if r.status_code==200 else None
    except requests.RequestException: return None

def gh_put_json(path, obj, msg):
    body={"message":msg,"content":base64.b64encode(json.dumps(obj,ensure_ascii=False,indent=2).encode()).decode()}
    old=gh_meta(path)
    if old and old.get("sha"): body["sha"]=old["sha"]
    try: r=requests.put(f"{API}/{path}",headers=H_JSON,json=body,timeout=20)
    except Exception as e: return False,f"sin conexión: {type(e).__name__}"
    if r.status_code in (200,201): return True,"ok"
    try: detail=r.json().get("message","")[:160]
    except Exception: detail=r.text[:160]
    hint={401:"token inválido",403:"token sin permiso de escritura",404:"repo/ruta no encontrada"}.get(r.status_code,"")
    return False,f"HTTP {r.status_code}: {detail} {hint}".strip()

# auth
if not st.session_state.auth:
    st.markdown("<div style='max-width:360px;margin:14vh auto 1rem;text-align:center'><div class='kv-logo'><span>KAIA VALE</span></div><h2>Mission Control</h2></div>",unsafe_allow_html=True)
    with st.form("login"):
        pw=st.text_input("Password",type="password",label_visibility="collapsed",placeholder="Password")
        go=st.form_submit_button("Entrar",use_container_width=True)
    if go:
        if pw==PASSWORD: st.session_state.auth=True; st.rerun()
        else: st.error("Password incorrecto.")
    st.stop()

snap=gh_json("snapshot.json",{"jobs":[]}); jobs=snap.get("jobs",[])
if not jobs: st.info("Sin jobs sincronizados."); st.stop()
job_ids=[j.get("job_id") for j in jobs if j.get("job_id")]

# Header: ONE navigation, ONE status
state_job_default=job_ids[0]
if "jid" not in st.session_state or st.session_state.jid not in job_ids: st.session_state.jid=state_job_default
jid=st.session_state.jid
job=next(j for j in jobs if j["job_id"]==jid)
versions=job.get("versions",[]); cur=versions[-1].get("version") if versions else None
if st.session_state.sel_ver not in [v.get("version") for v in versions]: st.session_state.sel_ver=cur
sel=st.session_state.sel_ver
state=gh_json(f"jobs/{jid}/state.json",{}) or {}; ms=gh_json("progress/muse_status.json",{}) or {}; budget=gh_json("budget.json",{}) or {}
metrics=gh_json("learning/metrics.json",{}) or {}; rules_l=gh_json("learning/rules.json",[]) or []; disag=gh_json("learning/disagreements.json",[]) or []

def hours_since(iso):
    try:
        dt=datetime.fromisoformat(str(iso).replace("Z","+00:00")); dt=dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc)-dt).total_seconds()/3600
    except Exception:return 999

def human_age(h):
    if h>=999:return "?"
    m=int(h*60)
    return "ahora" if m<1 else f"{m} min" if m<60 else f"{int(h)} h" if h<24 else f"{int(h/24)} d"

AGE=hours_since(state.get("updated")); LIVE=AGE<.25
cur_info=next((v for v in versions if v.get("version")==cur),{})
PEND=cur_info.get("veredicto_efectivo")=="READY_FOR_ELVIN_REVIEW" and not cur_info.get("decidido")

def live_state():
    s=state.get("state",""); mst=ms.get("status","")
    if PEND or s=="ELVIN_DECISION_REQUIRED" or mst=="BLOCKED_ON_ELVIN": return "Waiting for Elvin"
    if not LIVE:return "Idle"
    if s=="GENERATING":return "Generating"
    if mst in ("VALIDATING","CORRECTING"):return "Muse QC"
    if mst=="SUPERVISOR_REVIEW" or s=="REVIEWING":return "Supervisor reviewing"
    if mst=="WORKING":return "Working"
    if mst=="WAITING_ON_TOOL":return f"Waiting: {ms.get('waiting_on') or 'tool'}"
    return "Idle"
LIVE_LBL=live_state(); MSTEP=ms.get("current_step") or ""

st.markdown(f"<div class='kv-top'><div class='kv-logo'><span>◆ KAIA VALE</span></div><div class='small'>{jid}</div><div class='kv-live'><span class='dot'></span><b style='color:white'>{LIVE_LBL}</b><span class='desktop-only'>QA ${budget.get('monthly_used_usd',0):.2f}</span></div></div>",unsafe_allow_html=True)
nav=st.columns([1,1,1,5])
for i,name in enumerate(("Studio","Queue","Model")):
    if nav[i].button(name,key=f"nav_{name}",type="primary" if st.session_state.tab==name else "secondary",use_container_width=True):
        st.session_state.tab=name; st.session_state.compare=False; st.session_state.focus=False; st.rerun()
if len(job_ids)>1:
    chosen=nav[3].selectbox("Job",job_ids,index=job_ids.index(jid),label_visibility="collapsed")
    if chosen!=jid: st.session_state.jid=chosen; st.session_state.sel_ver=None; st.rerun()

# Muse yes/no blocker
if ms.get("status")=="BLOCKED_ON_ELVIN" and ms.get("needs_decision"):
    q=str(ms.get("needs_decision"))
    st.warning(q)
    y,n=st.columns(2)
    if y.button("SÍ, CONTINÚA",type="primary",use_container_width=True):
        ok,d=gh_put_json("progress/elvin_answer.json",{"question":q,"answer":"yes","timestamp":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())},"elvin answer: yes")
        st.success("Respuesta enviada.") if ok else st.error(d)
    if n.button("NO",use_container_width=True):
        ok,d=gh_put_json("progress/elvin_answer.json",{"question":q,"answer":"no","timestamp":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())},"elvin answer: no")
        st.success("Respuesta enviada.") if ok else st.error(d)

def asset_path(vn):
    for typ,ext in (("video","mp4"),("image","png"),("image","jpg"),("image","jpeg")):
        p=f"jobs/{jid}/versions/{vn}/asset.{ext}"
        if gh_raw(p): return typ,p
    return None,None

def verdict(vn): return gh_json(f"jobs/{jid}/versions/{vn}/verdict.json",{}) or {}
def meta(vn): return gh_json(f"jobs/{jid}/versions/{vn}/meta.json",{}) or {}
def send_decision(action,note=""):
    did=str(uuid.uuid4()); obj={"decision_id":did,"job_id":jid,"version":cur,"action":action,"timestamp":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),"note":note.strip()}
    ok,d=gh_put_json(f"decisions/inbox/{did}.json",obj,f"decision {action} {jid} {cur}")
    if ok: st.success(f"Decisión enviada · {did[:8]} · ACK esperado en ~1 min.")
    else: st.error(f"No se pudo enviar: {d}")

def stage_data():
    vd=verdict(cur) if cur else {}; ve=cur_info.get("veredicto_efectivo",""); s=state.get("state",""); has=bool(versions)
    return [("Brief",has and s!="GENERATING"),("Generate",has),("Muse QC",bool(vd)),("Supervisor",ve in ("CORREGIR","ESCALAR","READY_FOR_ELVIN_REVIEW","APROBADO")),("Elvin",PEND or bool(cur_info.get("decidido"))),("Publish",s=="APPROVED")]

TAB=st.session_state.tab
if TAB=="Studio":
    if not versions:
        st.info("Este job todavía no tiene renders.")
    elif st.session_state.focus:
        typ,p=asset_path(sel)
        if st.button("← Volver a Mission Control"): st.session_state.focus=False; st.rerun()
        if typ=="image": st.image(gh_raw(p),use_container_width=True)
        elif typ=="video": st.video(gh_raw(p))
    else:
        # Desktop workspace. Streamlit stacks these columns on narrow screens automatically.
        pipe,canvas,insp=st.columns([1.25,5.6,2.15],gap="small")
        with pipe:
            st.markdown("<div class='pipe-title'>Pipeline</div>",unsafe_allow_html=True)
            stages=stage_data(); active_idx=next((i for i,(n,d) in enumerate(stages) if not d),len(stages)-1)
            if PEND: active_idx=4
            for i,(name,done) in enumerate(stages):
                cls="done" if done and i<active_idx else "active" if i==active_idx else "pending"
                sym="✓" if cls=="done" else str(i+1)
                st.markdown(f"<div class='pipe-item {cls}'><span class='pi'>{sym}</span><b>{name}</b></div>",unsafe_allow_html=True)
            with st.expander("Estado del job"):
                st.caption(state.get("detail") or "Sin detalle")
                st.caption(f"Actualizado: {human_age(AGE)}")
        with canvas:
            vd=verdict(sel); mt=meta(sel); typ,p=asset_path(sel); vi=next((v for v in versions if v.get("version")==sel),{})
            st.markdown(f"<div class='canvas-label'><span>LIVE CANVAS · <b>{sel}</b></span><span class='badge'>{vi.get('veredicto_efectivo') or '—'}</span></div>",unsafe_allow_html=True)
            if st.session_state.compare:
                choices=[v.get("version") for v in versions]
                if len(choices)<2: st.info("Necesitas al menos dos versiones para comparar.")
                else:
                    left,right=st.columns(2)
                    pair=choices[-2:]
                    for col,vn in zip((left,right),pair):
                        with col:
                            st.caption(vn); t,pp=asset_path(vn)
                            if t=="image": st.image(gh_raw(pp),use_container_width=True)
                            elif t=="video": st.video(gh_raw(pp))
            else:
                if typ=="image": st.image(gh_raw(p),use_container_width=True)
                elif typ=="video": st.video(gh_raw(p))
                else: st.info("Asset todavía no sincronizado.")
            # one control row only
            a,b,c=st.columns([1,1,1])
            if a.button("Comparar" if not st.session_state.compare else "Cerrar comparación",use_container_width=True): st.session_state.compare=not st.session_state.compare; st.rerun()
            if b.button("Fullscreen",use_container_width=True): st.session_state.focus=True; st.rerun()
            if c.button("Inspector" if not st.session_state.inspector else "Ocultar inspector",use_container_width=True): st.session_state.inspector=not st.session_state.inspector; st.rerun()
            # one version selector only
            opts=[v.get("version") for v in reversed(versions)]
            picked=st.pills("Versiones",opts,default=sel,label_visibility="collapsed") if hasattr(st,"pills") else st.selectbox("Versiones",opts,index=opts.index(sel),label_visibility="collapsed")
            if picked and picked!=sel: st.session_state.sel_ver=picked; st.session_state.compare=False; st.rerun()
            if PEND:
                st.markdown("<div class='review'><b>READY FOR ELVIN REVIEW</b> · Esta decisión usa el protocolo existente del inbox.</div>",unsafe_allow_html=True)
                r1,r2,r3=st.columns([1,1.3,1])
                if r1.button("REJECT",use_container_width=True): send_decision("reject")
                if r2.button("REQUEST CHANGES",use_container_width=True): st.session_state.change_open=not st.session_state.change_open; st.rerun()
                if r3.button("APPROVE",type="primary",use_container_width=True): send_decision("approve_final")
                if st.session_state.change_open:
                    with st.form("changes_form"):
                        note=st.text_area("Cambios solicitados",placeholder="Describe exactamente qué debe corregirse…")
                        if st.form_submit_button("Enviar cambios",type="primary",use_container_width=True):
                            if note.strip(): send_decision("request_changes",note); st.session_state.change_open=False
                            else: st.error("Escribe los cambios.")
            st.markdown(f"<div class='livebar'><span class='dot'></span><b>{LIVE_LBL}</b><span>{MSTEP[:120] or (state.get('detail') or '')[:120]}</span></div>",unsafe_allow_html=True)
        with insp:
            if st.session_state.inspector:
                vd=verdict(sel); mt=meta(sel); vi=next((v for v in versions if v.get("version")==sel),{})
                st.markdown("<div class='pipe-title'>Inspector</div>",unsafe_allow_html=True)
                st.markdown(f"<div class='ins'><h4>{sel}</h4><span class='badge'>{vi.get('veredicto_efectivo') or '—'}</span></div>",unsafe_allow_html=True)
                # Support both old compact verdicts and richer verdicts from real bus.
                cov=vd.get("visual_coverage") or {}
                rich={"identity":vd.get("identity_review"),"anatomy":vd.get("anatomy_review"),"skin":vd.get("skin_review"),"hands":None}
                st.markdown("<div class='ins' style='margin-top:8px'><div class='ins-title'>QC</div>",unsafe_allow_html=True)
                for cat in ("identity","anatomy","skin","hands"):
                    fail=False
                    cv=cov.get(cat)
                    if isinstance(cv,dict): fail=any(isinstance(x,dict) and x.get("estado")=="FAIL" for x in cv.values())
                    rv=rich.get(cat)
                    if isinstance(rv,dict) and str(rv.get("estado","")).upper().startswith("FALLA"): fail=True
                    st.markdown(f"<div class='qc'><b>{cat.title()}</b><span class='{'bad' if fail else 'ok'}'>{'✕' if fail else '✓'}</span></div>",unsafe_allow_html=True)
                st.markdown("</div>",unsafe_allow_html=True)
                findings=vd.get("hallazgos") or vd.get("blocking_issues") or vd.get("motivo_principal") or []
                if findings:
                    st.markdown("<div class='ins' style='margin-top:8px'><div class='ins-title'>Findings</div>",unsafe_allow_html=True)
                    for f in findings[:5]:
                        txt=(f.get("titulo") or f.get("descripcion") or f.get("categoria") or str(f)) if isinstance(f,dict) else str(f)
                        st.markdown(f"<div class='find'>• {txt[:180]}</div>",unsafe_allow_html=True)
                    st.markdown("</div>",unsafe_allow_html=True)
                prm=mt.get("params",{}) if isinstance(mt,dict) else {}
                st.markdown(f"<div class='ins' style='margin-top:8px'><div class='ins-title'>Specs</div><div class='spec'><div>Model<b>{prm.get('model','—')}</b></div><div>Ratio<b>{prm.get('ratio','—')}</b></div><div>Duration<b>{prm.get('duration','—')}</b></div><div>Render<b>{human_age(hours_since(mt.get('registered')))}</b></div></div></div>",unsafe_allow_html=True)
            else:
                if st.button("Abrir inspector",use_container_width=True): st.session_state.inspector=True; st.rerun()

elif TAB=="Queue":
    st.subheader("Queue")
    st.caption(f"{jid} · {LIVE_LBL} · actualizado {human_age(AGE)}")
    events=gh_json(f"jobs/{jid}/events.json",{}) or {}
    lines=events.get("lines",[]) if isinstance(events,dict) else []
    if lines: st.code("\n".join(lines[-80:]))
    else:
        rows=[]
        for v in versions:
            m=meta(v.get("version")); rows.append({"version":v.get("version"),"status":v.get("veredicto_efectivo"),"registered":m.get("registered"),"model":(m.get("params") or {}).get("model")})
        st.dataframe(rows,use_container_width=True,hide_index=True)

elif TAB=="Model":
    st.subheader("Model / Analytics")
    c1,c2,c3,c4=st.columns(4)
    c1.metric("Muse ↔ QA",f"{metrics.get('acuerdo_pct',0) or 0}%")
    c2.metric("QA cost",f"${metrics.get('costo_supervisor_total_usd',0):.4f}")
    c3.metric("Elvin caught",metrics.get("human_caught_miss",0))
    fp=(metrics.get("falsos_positivos_muse",0) or 0)+(metrics.get("falsos_positivos_supervisor",0) or 0)
    c4.metric("False positives",fp)
    st.caption(f"Phase: {metrics.get('fase','—')} · Reviews: {metrics.get('revisiones_totales',0)} · Learned rules: {metrics.get('reglas_aprendidas',0)}")
    with st.expander("Reglas aprendidas"):
        active=[r for r in rules_l if isinstance(r,dict) and r.get("activa")]
        if not active: st.caption("Sin reglas activas sincronizadas.")
        for r in active: st.markdown(f"**{r.get('id','—')}** — {r.get('regla','')}")

st.caption("Mission Control v6 · UI rewrite · auto-refresh 30s")
time.sleep(30)
st.rerun()
