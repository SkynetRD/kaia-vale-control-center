"""Kaia Vale Control Center — frontend Streamlit.

Lee el estado del reviewer-loop desde el repo privado de sincronización
(kaia-control-sync). GitHub es SOLO transporte: la autoridad que valida y
aplica decisiones es el reviewer-loop local (Cosmo).

Secretos (Streamlit Cloud -> Settings -> Secrets, NUNCA en el código):
  DASHBOARD_PASSWORD = "tu password del dashboard"
  GITHUB_TOKEN       = "fine-grained PAT con Contents read/write solo en kaia-control-sync"
  SYNC_REPO          = "tu-usuario/kaia-control-sync"
"""
import base64
import json
import time
import uuid

import requests
import streamlit as st

st.set_page_config(page_title="Kaia Vale Control Center", layout="wide")

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

# ---------------- auth gate ----------------
if "auth" not in st.session_state:
    st.session_state.auth = False
if not st.session_state.auth:
    st.title("🎛️ Kaia Vale Control Center")
    with st.form("login"):
        pw = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Entrar")
    if submitted:
        if pw == PASSWORD:
            st.session_state.auth = True
            st.rerun()
        else:
            st.error("Password incorrecto.")
    st.stop()


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


def gh_put_json(path: str, obj: dict, msg: str) -> bool:
    content = base64.b64encode(json.dumps(obj, ensure_ascii=False, indent=1).encode()).decode()
    r = requests.put(f"{API}/{path}", headers={**H, "Accept": "application/vnd.github+json"},
                     json={"message": msg, "content": content}, timeout=20)
    return r.status_code in (200, 201)


# ---------------- UI ----------------
st.title("🎛️ Kaia Vale Control Center")
snap = gh_json("snapshot.json") or {"jobs": []}
agent = gh_json("agent.json") or {}
budget = gh_json("budget.json") or {}

c1, c2 = st.columns([3, 1])
with c1:
    st.caption(f"🤖 Cosmo: {agent.get('status', '—')}")
with c2:
    caps = budget.get("caps_usd", {})
    used = budget.get("monthly_used_usd", 0)
    st.caption(f"💰 ${used:.4f} / ${caps.get('monthly', '?')} mensual")

jobs = snap.get("jobs", [])
if not jobs:
    st.info("Sin jobs sincronizados todavía.")
    code = gh_status("snapshot.json")
    st.warning(f"Diagnóstico GitHub API: HTTP {code} — 401=token inválido o sin acceso al repo, "
               f"404=SYNC_REPO mal escrito o repo sin contenido, -1=sin conexión.")
    st.stop()

job_ids = [j["job_id"] for j in jobs]
jid = st.selectbox("Job", job_ids)
job = next(j for j in jobs if j["job_id"] == jid)
cur = job["versions"][-1]["version"] if job.get("versions") else None
curinfo = next((x for x in job["versions"] if x["version"] == cur), {}) if cur else {}
state = gh_json(f"jobs/{jid}/state.json") or {}
st.subheader(f"{jid} — `{state.get('state', '?')}`")
if state.get("detail"):
    st.caption(state["detail"])
if state.get("state") == "ELVIN_DECISION_REQUIRED":
    st.error("⛔ Requiere tu decisión: el sistema no pudo resolverlo con el canon ni las reglas. Revisa el veredicto y decide.")
elif state.get("state") == "ESCALATED_INTERNAL":
    st.info("🔧 Escalación interna: el supervisor tuvo incertidumbre pero el canon la resuelve automáticamente. El loop continúa solo.")

tabs = st.tabs(["Versiones", "Veredicto", "Eventos", "Decidir"])


def _send_decision(action: str, note: str, key: str) -> None:
    """Escribe la decisión en el repo y espera el ACK. Reutilizable."""
    did = str(uuid.uuid4())
    dec = {"decision_id": did, "job_id": jid, "version": cur,
           "action": action, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "note": note.strip()}
    if gh_put_json(f"decisions/inbox/{did}.json", dec, f"decision {action} {jid} {cur}"):
        st.success("Decisión enviada. Esperando ACK del reviewer-loop…")
        for _ in range(20):  # ~2 min máx
            time.sleep(6)
            ack = gh_json(f"decisions/acks/{did}.json")
            gh_raw.clear()  # limpiar caché para reintentar
            if ack:
                if ack["status"] == "accepted":
                    st.success(f"✅ Aceptada: {ack['reason']}")
                else:
                    st.error(f"❌ Rechazada: {ack['reason']}")
                st.json(ack)
                break
        else:
            st.warning("Sin ACK todavía. Revisa en unos segundos.")
    else:
        st.error("No se pudo escribir la decisión en el repo.")


def _decision_pending() -> bool:
    return (curinfo.get("veredicto_efectivo") == "READY_FOR_ELVIN_REVIEW"
            and not curinfo.get("decidido"))


with tabs[0]:
    for v in job.get("versions", []):
        vn = v["version"]
        with st.expander(f"{vn} — {v.get('veredicto_efectivo', '?')}"):
            media = gh_raw(f"jobs/{jid}/versions/{vn}/asset.mp4") or gh_raw(f"jobs/{jid}/versions/{vn}/asset.png")
            if media:
                if v.get("media") == "video":
                    st.video(media)
                else:
                    st.image(media)
            meta = gh_json(f"jobs/{jid}/versions/{vn}/meta.json") or {}
            st.json(meta.get("params", {}))
    # botones rápidos sobre la versión actual
    if _decision_pending():
        st.divider()
        st.markdown(f"**Decidir sobre {cur}:**")
        qc_note = st.text_input("Instrucciones (solo para pedir cambios)", key=f"qc_note_{jid}_{cur}")
        b1, b2, b3 = st.columns(3)
        if b1.button("✅ Aprobar", key=f"qc_ap_{jid}_{cur}"):
            _send_decision("approve_final", "", f"qc_ap_{jid}_{cur}")
        if b2.button("❌ Rechazar", key=f"qc_rj_{jid}_{cur}"):
            _send_decision("reject", "", f"qc_rj_{jid}_{cur}")
        if b3.button("✏️ Pedir cambios", key=f"qc_rc_{jid}_{cur}"):
            if not qc_note.strip():
                st.error("Escribe las instrucciones arriba para pedir cambios.")
            else:
                _send_decision("request_changes", qc_note, f"qc_rc_{jid}_{cur}")

with tabs[1]:
    cur = job["versions"][-1]["version"] if job.get("versions") else None
    if cur:
        verdict = gh_json(f"jobs/{jid}/versions/{cur}/verdict.json")
        if verdict:
            st.json({k: verdict.get(k) for k in
                     ("veredicto", "motivo_principal", "causa_probable", "blocking_issues",
                      "regression_check", "nota_para_usuario")})
            with st.expander("Veredicto completo"):
                st.json(verdict)

with tabs[2]:
    ev = gh_json(f"jobs/{jid}/events.json") or {"lines": []}
    st.code("\n".join(ev["lines"][-30:]))

with tabs[3]:
    if not _decision_pending():
        st.info("Este job no está pendiente de tu decisión ahora mismo.")
    else:
        action = st.radio("Decisión", ["approve_final", "reject", "request_changes"])
        note = st.text_area("Instrucciones (obligatorio para REQUEST CHANGES)") if action == "request_changes" else ""
        if st.button("Enviar decisión"):
            if action == "request_changes" and not note.strip():
                st.error("REQUEST_CHANGES requiere instrucciones.")
            else:
                did = str(uuid.uuid4())
                dec = {"decision_id": did, "job_id": jid, "version": cur,
                       "action": action, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                       "note": note.strip()}
                if gh_put_json(f"decisions/inbox/{did}.json", dec, f"decision {action} {jid} {cur}"):
                    st.success("Decisión enviada. Esperando ACK del reviewer-loop…")
                    for _ in range(20):  # ~2 min máx
                        time.sleep(6)
                        ack = gh_json(f"decisions/acks/{did}.json")
                        # limpiar caché para reintentar
                        gh_raw.clear()
                        if ack:
                            if ack["status"] == "accepted":
                                st.success(f"✅ Aceptada: {ack['reason']}")
                            else:
                                st.error(f"❌ Rechazada: {ack['reason']}")
                            st.json(ack)
                            break
                    else:
                        st.warning("Sin ACK todavía. Revisa en unos segundos.")
                else:
                    st.error("No se pudo escribir la decisión en el repo.")

# ---------------- aprendizaje operacional ----------------
st.divider()
st.subheader("📚 Aprendizaje operacional")
learn_tab1, learn_tab2, learn_tab3 = st.tabs(["Métricas", "Reglas", "Desacuerdos"])
metrics = gh_json("learning/metrics.json") or {}
phase = gh_json("learning/phase.json") or {}
rules_l = gh_json("learning/rules.json") or []
disag = gh_json("learning/disagreements.json") or []

with learn_tab1:
    fase = metrics.get("fase", phase.get("fase", "?"))
    st.markdown(f"**Fase actual: {fase}**")
    st.caption({"FASE_1": "Supervisión total — el supervisor revisa todo.",
                "FASE_2": "Supervisión adaptativa.", "FASE_3": "Auditoría.",
                "FASE_4": "Muse autónomo."}.get(fase, ""))
    c1, c2, c3 = st.columns(3)
    c1.metric("Acuerdo Muse↔Supervisor", f"{metrics.get('acuerdo_pct', '?')}%")
    c2.metric("Revisiones", metrics.get("revisiones_totales", 0))
    c3.metric("Costo supervisor total", f"${metrics.get('costo_supervisor_total_usd', 0):.4f}")
    c1.metric("Errores no detectados por Muse", metrics.get("errores_no_detectados_por_muse", 0))
    c2.metric("Falsos positivos Muse", metrics.get("falsos_positivos_muse", 0))
    c3.metric("Falsos positivos supervisor", metrics.get("falsos_positivos_supervisor", 0))
    c1.metric("Racha sin desacuerdos", metrics.get("jobs_consecutivos_sin_desacuerdo", 0))
    c2.metric("Llamadas evitadas", metrics.get("llamadas_evitadas", 0))
    c3.metric("Reglas aprendidas", metrics.get("reglas_aprendidas", 0))
    if metrics.get("defectos_repetidos"):
        st.warning(f"Defectos repetidos: {metrics['defectos_repetidos']}")
    cpj = metrics.get("costo_supervisor_por_job", {})
    if cpj:
        st.caption("Costo por job: " + ", ".join(f"{k} ${v:.4f}" for k, v in cpj.items()))

with learn_tab2:
    if not rules_l:
        st.info("Sin reglas aprendidas todavía.")
    for r in rules_l:
        if r.get("activa"):
            st.markdown(f"**{r['id']}** — {r['regla']}")
            st.caption(f"Fuente: {r.get('fuente','')} · aplicada {r.get('veces_aplicada',0)}x"
                       + (" · ⚠️ error recurrente" if r.get("error_recurrente") else ""))

with learn_tab3:
    if not disag:
        st.info("Sin desacuerdos registrados.")
    for d in reversed(disag[-10:]):
        st.markdown(f"**{d['job_id']} {d['version']}** — {d['clase']} "
                    f"({d['evaluacion_muse']} → {d['veredicto_supervisor']})")
        if d.get("criterio_faltante"):
            st.caption(f"Criterio: {d['criterio_faltante']}")

# ---------------- auto-refresh suave ----------------
st.caption("Actualización automática cada ~30s.")
time.sleep(30)
st.rerun()
