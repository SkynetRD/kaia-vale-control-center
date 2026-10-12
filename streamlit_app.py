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
    pw = st.text_input("Password", type="password")
    if st.button("Entrar") and pw == PASSWORD:
        st.session_state.auth = True
        st.rerun()
    st.stop()


# ---------------- github helpers ----------------
@st.cache_data(ttl=20)
def gh_raw(path: str) -> bytes | None:
    r = requests.get(f"{API}/{path}?ref=main", headers=H, timeout=20)
    return r.content if r.status_code == 200 else None


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
    st.stop()

job_ids = [j["job_id"] for j in jobs]
jid = st.selectbox("Job", job_ids)
job = next(j for j in jobs if j["job_id"] == jid)
state = gh_json(f"jobs/{jid}/state.json") or {}
st.subheader(f"{jid} — `{state.get('state', '?')}`")
if state.get("detail"):
    st.caption(state["detail"])

tabs = st.tabs(["Versiones", "Veredicto", "Eventos", "Decidir"])

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
    cur = job["versions"][-1]["version"] if job.get("versions") else None
    curinfo = next((x for x in job["versions"] if x["version"] == cur), {})
    if curinfo.get("veredicto_efectivo") != "READY_FOR_ELVIN_REVIEW" or curinfo.get("decidido"):
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

# ---------------- auto-refresh suave ----------------
st.caption("Actualización automática cada ~30s.")
time.sleep(30)
st.rerun()
