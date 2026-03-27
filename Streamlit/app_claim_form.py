import os
import sys
import datetime as dt
from typing import Optional

import streamlit as st
import oci

# ── Path setup so pipeline/ is importable ─────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pipeline.streamlit_pipeline import run_full_pipeline
from pipeline.email_notifier     import send_claim_notification
from pipeline.dashboard_queries  import load_all_decisions, load_claim_details, apply_manual_decision

# ── Page Config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Claim Insurance",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── OCI Object Storage Config (dari .env) ────────────────────────────────────
OCI_REGION      = os.getenv("OCI_REGION",         "ap-singapore-1")
BUCKET_NAME     = os.getenv("OCI_BUCKET_NAME",    "ClaimInsurance")
EVIDENCE_PREFIX = os.getenv("OCI_EVIDENCE_PREFIX", "Evidance")

try:
    signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
    object_storage = oci.object_storage.ObjectStorageClient(
        config={"region": OCI_REGION},
        signer=signer,
    )
    namespace = object_storage.get_namespace().data
except Exception as e:
    st.error(f"OCI Auth Error: {str(e)}")
    st.stop()

# ── Claim ID Generation (format: CLM-NNN, global auto-increment) ──────────────

if "page"            not in st.session_state: st.session_state.page            = "new_claim"
if "submitted"       not in st.session_state: st.session_state.submitted       = False
if "processing"      not in st.session_state: st.session_state.processing      = False
if "claim_id"        not in st.session_state: st.session_state.claim_id        = None
if "decision"        not in st.session_state: st.session_state.decision        = None
if "policy_id"       not in st.session_state: st.session_state.policy_id       = None
if "email_notified"  not in st.session_state: st.session_state.email_notified  = None
if "review_claim_id" not in st.session_state: st.session_state.review_claim_id = None


@st.cache_data(ttl=60)
def load_existing_policy_ids() -> list:
    """Load all existing claim IDs from Bronze DB, newest first."""
    try:
        from sqlalchemy import create_engine, text as _text
        import os as _os
        host = _os.getenv("ORACLE_BRONZE_HOST",    "localhost")
        port = _os.getenv("ORACLE_BRONZE_PORT",    "1521")
        svc  = _os.getenv("ORACLE_BRONZE_SERVICE", "FREEPDB1")
        user = _os.getenv("ORACLE_BRONZE_USER",    "claims_bronze")
        pw   = _os.getenv("ORACLE_BRONZE_PASSWORD","claims_bronze")
        eng  = create_engine(f"oracle+oracledb://{user}:{pw}@{host}:{port}/?service_name={svc}")
        with eng.connect() as conn:
            rows = conn.execute(_text(
                "SELECT claim_id_ext FROM inbound_claims ORDER BY created_at DESC"
            )).fetchall()
        return [r[0] for r in rows if r[0]]
    except Exception:
        return []


def generate_next_policy_id(existing: list) -> str:
    """Generate next CLM-NNN ID based on the highest number in the DB."""
    import re as _re
    nums = []
    for cid in existing:
        m = _re.match(r"^CLM-(\d+)$", str(cid or ""))
        if m:
            nums.append(int(m.group(1)))
    next_num = max(nums) + 1 if nums else 1
    return f"CLM-{next_num:03d}"


# Initialise policy_id once on first load
if st.session_state.policy_id is None:
    st.session_state.policy_id = generate_next_policy_id(load_existing_policy_ids())


def save_upload(file, claim_id: str, prefix: str) -> bool:
    if file is None:
        return False
    filename = file.name.strip()
    if prefix == "video-claimant":
        object_name = f"{EVIDENCE_PREFIX}/{claim_id}/claimant_video_evidence/{filename}"
    elif prefix == "img-claimant":
        object_name = f"{EVIDENCE_PREFIX}/{claim_id}/claimant_img_evidence/{filename}"
    elif prefix == "img-counterparty":
        object_name = f"{EVIDENCE_PREFIX}/{claim_id}/counterparty_img_evidence/{filename}"
    else:
        return False
    object_storage.put_object(
        namespace_name=namespace,
        bucket_name=BUCKET_NAME,
        object_name=object_name,
        put_object_body=file.getvalue(),
        content_type=file.type,
    )
    return True


# ── Styling ───────────────────────────────────────────────────────────────────
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700&family=Inter:wght@300;400;500;600;700&display=swap');
html, body, [data-testid="stAppViewContainer"] { font-family: 'Inter', sans-serif !important; background: #f0f3f8 !important; }
[data-testid="stHeader"], [data-testid="stToolbar"], footer { display: none !important; }
.block-container { padding: 36px 52px 64px !important; max-width: 960px !important; background-image: radial-gradient(#c5cad4 1px, transparent 1px); background-size: 26px 26px; }
[data-testid="stSidebar"] { background: linear-gradient(168deg, #17304d 0%, #0d1f35 100%) !important; }
label { font-size: 11px !important; font-weight: 700 !important; color: #b87716 !important; text-transform: uppercase !important; }
input[type="text"], [data-baseweb="select"] > div, textarea, [data-testid="stFileUploadDropzone"] { background-color: #ffffff !important; border: 1.5px solid #dde3ec !important; border-radius: 8px !important; }
.decision-card { background: #ffffff; border: 1px solid #DDE0E3; border-radius: 8px; padding: 0; box-shadow: 0 2px 8px rgba(0,0,0,0.06); margin-bottom: 20px; overflow: hidden; }
.decision-header { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 12px; background: #f8f9fa; border-bottom: 1px solid #E9ECEF; padding: 14px 20px; }
.decision-header-item { font-size: 13px; font-weight: 600; color: #495057; }
.decision-header-item strong { font-weight: 700; }
.decision-body { padding: 16px 20px; font-size: 13px; color: #495057; line-height: 1.6; }
.decision-label { font-size: 11px; font-weight: 700; color: #b87716; text-transform: uppercase; margin-bottom: 6px; }
</style>""", unsafe_allow_html=True)

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<p style="font-family:\'Playfair Display\',serif;font-size:20px;font-weight:700;color:#ffffff;margin:0;">Claim Insurance</p>', unsafe_allow_html=True)
    st.markdown('<p style="font-family:\'Inter\',sans-serif;font-size:8.5px;font-weight:600;color:rgba(255,255,255,0.30);text-transform:uppercase;">Powered by Oracle AIDP</p>', unsafe_allow_html=True)
    st.markdown("<hr style='border-color:rgba(255,255,255,0.12);margin:16px 0;'>", unsafe_allow_html=True)

    if st.button("📝  New Claim", use_container_width=True):
        load_existing_policy_ids.clear()
        st.session_state.page            = "new_claim"
        st.session_state.submitted       = False
        st.session_state.claim_id        = None
        st.session_state.decision        = None
        st.session_state.policy_id       = None
        st.session_state.email_notified  = False
        st.rerun()

    if st.button("📊  Claim Dashboard", use_container_width=True):
        st.session_state.page = "dashboard"
        st.rerun()

    # Highlight active page
    active = st.session_state.page
    active_label = {"new_claim": "📝 New Claim", "dashboard": "📊 Dashboard", "review": "🔍 Manual Review"}.get(active, "")
    st.markdown(
        f'<p style="font-size:10px;color:rgba(255,255,255,0.35);margin-top:8px;">Active: {active_label}</p>',
        unsafe_allow_html=True,
    )


# ── Decision Color Helpers ────────────────────────────────────────────────────
DECISION_COLOR = {
    "APPROVE_FAST_TRACK": "#198754",
    "APPROVE":            "#198754",
    "MANUAL_REVIEW":      "#fd7e14",
    "REJECT":             "#dc3545",
}
DECISION_ICON = {
    "APPROVE_FAST_TRACK": "✅",
    "APPROVE":            "✅",
    "MANUAL_REVIEW":      "⚠️",
    "REJECT":             "❌",
}
ACTION_ICON = {
    "PAYOUT":   "🔔",
    "ESCALATE": "⚠️",
    "NOTIFY":   "📧",
    "ARCHIVE":  "📁",
}


def render_decision_card(decision: dict):
    cid        = decision.get("claim_id",       "—")
    dec        = decision.get("decision",        "MANUAL_REVIEW")
    action     = decision.get("action",          "NOTIFY")
    payout     = float(decision.get("est_payout_myr", decision.get("est_payout_usd", 0.0)))
    summary    = decision.get("fusion_text",     "")
    reasons    = decision.get("reasons_json",    "")
    evidence   = decision.get("evidence_list",   [])
    pdf_url    = decision.get("pdf_url",         "")

    dec_color  = DECISION_COLOR.get(dec,    "#495057")
    dec_icon   = DECISION_ICON.get(dec,     "📋")
    act_icon   = ACTION_ICON.get(action,    "📋")

    # Build evidence HTML
    evidence_html = ""
    if evidence:
        items = "".join(f"<li>{e}</li>" for e in evidence)
        evidence_html = (
            '<div style="margin-top:16px;">'
            '<div class="decision-label">Evidence</div>'
            f'<ul style="margin:6px 0 0 16px;padding:0;font-size:13px;color:#495057;">{items}</ul>'
            '</div>'
        )

    # Convert [Page N] citations to clickable hyperlinks
    import re as _re
    def _linkify_pages(text, base_url):
        if not base_url:
            return text
        return _re.sub(
            r'\[Page\s*(\d+)\]',
            lambda m: (
                f'<a href="{base_url}#page={m.group(1)}" target="_blank" '
                f'style="color:#b87716;font-weight:600;">'
                f'[Page {m.group(1)}]</a>'
            ),
            text,
        )

    # Build reasons HTML
    reasons_html = ""
    if reasons:
        # Split into bullet points on ". " so each citation is its own line
        sentences = [s.strip() for s in _re.split(r'(?<=\.)\s+', reasons) if s.strip()]
        if len(sentences) <= 1:
            # Single block — render as paragraph
            bullet_html = f'<p style="margin:4px 0;font-size:13px;color:#495057;">{_linkify_pages(reasons, pdf_url)}</p>'
        else:
            items = "".join(
                f'<li style="margin-bottom:4px;">{_linkify_pages(s, pdf_url)}</li>'
                for s in sentences
            )
            bullet_html = f'<ul style="margin:6px 0 0 16px;padding:0;font-size:13px;color:#495057;">{items}</ul>'

        pdf_link_html = ""
        if pdf_url:
            pdf_link_html = (
                f'<div style="margin-top:8px;font-size:11px;padding:6px 10px;'
                f'background:#fffbf0;border-left:3px solid #b87716;border-radius:4px;">'
                f'📄 Policy Reference: <a href="{pdf_url}" target="_blank" '
                f'style="color:#b87716;font-weight:600;">Private Car Policy Wording (PDF)</a>'
                f' — click page links above to jump to relevant sections'
                f'</div>'
            )

        reasons_html = (
            '<div style="margin-top:16px;">'
            '<div class="decision-label">Reasons</div>'
            f'{bullet_html}'
            f'{pdf_link_html}'
            '</div>'
        )

    html = (
        '<div class="decision-card">'
        '<div class="decision-header">'
        f'<div class="decision-header-item">📄 Claim ID: <strong>{cid}</strong></div>'
        f'<div class="decision-header-item">{dec_icon} Decision: <strong style="color:{dec_color};">{dec}</strong></div>'
        f'<div class="decision-header-item">{act_icon} Action: <strong style="color:#0d6efd;">{action}</strong></div>'
        f'<div class="decision-header-item">💰 Payout: <strong style="color:#d63384;">RM {payout:,.2f}</strong></div>'
        '</div>'
        '<div class="decision-body">'
        '<div class="decision-label">Summary</div>'
        f'<div>{summary}</div>'
        f'{reasons_html}'
        f'{evidence_html}'
        '</div>'
        '</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


# ── Dashboard Page ────────────────────────────────────────────────────────────

_DEC_ICON = {
    "APPROVE_FAST_TRACK": "🟢",
    "APPROVE":            "🟢",
    "REJECT":             "🔴",
    "MANUAL_REVIEW":      "🟡",
}
_DEC_COLOR = {
    "APPROVE_FAST_TRACK": "#2e7d32",
    "APPROVE":            "#2e7d32",
    "REJECT":             "#c62828",
    "MANUAL_REVIEW":      "#e65100",
}
_TABLE_COLS = [0.8, 1.8, 0.8, 1.2, 0.8, 1.5, 1.5, 2.5]
_TABLE_HEADERS = ["Claim ID", "Decision", "Action", "Payout", "Conf.", "Tag", "Processed At", "Actions"]


def render_dashboard():
    st.markdown(
        "<h1 style='font-family:Playfair Display;color:#17304d;'>"
        "📊 Claim <span style='color:#b87716;'>Dashboard</span></h1>",
        unsafe_allow_html=True,
    )

    df = load_all_decisions()
    if df.empty:
        st.info("No claims found in the system yet.")
        return

    # Filter bar
    decisions = ["All"] + sorted(df["decision"].dropna().unique().tolist())
    col_f, col_r = st.columns([2, 1])
    selected = col_f.selectbox("Filter by Decision", decisions, label_visibility="visible")
    col_r.markdown(
        f"<p style='padding-top:28px;font-size:13px;color:#6c757d;'>{len(df)} total claim(s)</p>",
        unsafe_allow_html=True,
    )

    display_df = df if selected == "All" else df[df["decision"] == selected]

    # ── Table header ──────────────────────────────────────────────────────────
    hcols = st.columns(_TABLE_COLS)
    for hcol, label in zip(hcols, _TABLE_HEADERS):
        hcol.markdown(
            f"<span style='font-size:11px;font-weight:700;color:#6c757d;"
            f"text-transform:uppercase;'>{label}</span>",
            unsafe_allow_html=True,
        )
    st.markdown("<hr style='margin:4px 0 8px;border-color:#dee2e6;'>", unsafe_allow_html=True)

    # ── Table rows ────────────────────────────────────────────────────────────
    for _, row in display_df.iterrows():
        cid      = str(row["claim_id"])
        decision = str(row["decision"])
        tag      = str(row.get("decision_tag") or "—")
        icon     = _DEC_ICON.get(decision, "⚪")
        color    = _DEC_COLOR.get(decision, "#495057")

        cols = st.columns(_TABLE_COLS)
        cols[0].write(cid)
        cols[1].markdown(
            f"<span style='color:{color};font-weight:600;font-size:13px;'>{icon} {decision}</span>",
            unsafe_allow_html=True,
        )
        cols[2].write(row["action"])
        cols[3].write(row["payout_myr"])
        cols[4].write(row["confidence"])
        cols[5].write(tag)
        cols[6].write(row["created_at"])

        # Actions column — only for MANUAL_REVIEW not yet reviewed
        if decision == "MANUAL_REVIEW":
            if tag in ("APPROVE_MANUAL", "REJECT_MANUAL"):
                cols[7].markdown(
                    f"<span style='font-size:12px;color:#6c757d;'>✔ {tag}</span>",
                    unsafe_allow_html=True,
                )
            else:
                with cols[7]:
                    bc1, bc2, bc3 = st.columns(3)
                    if bc1.button("🔍", key=f"rev_{cid}", help="Open full review",
                                  use_container_width=True):
                        st.session_state.review_claim_id = cid
                        st.session_state.page = "review"
                        st.rerun()
                    if bc2.button("✅", key=f"app_{cid}", help="Approve claim",
                                  use_container_width=True, type="primary"):
                        if apply_manual_decision(cid, "APPROVE"):
                            st.rerun()
                    if bc3.button("❌", key=f"rej_{cid}", help="Reject claim",
                                  use_container_width=True):
                        if apply_manual_decision(cid, "REJECT"):
                            st.rerun()

        st.markdown("<hr style='margin:4px 0;border-color:#f0f0f0;'>", unsafe_allow_html=True)


# ── Manual Review Page ────────────────────────────────────────────────────────

def _get_oci_bytes(uri: str) -> Optional[bytes]:
    """Download evidence file bytes from OCI Object Storage."""
    if not uri:
        return None
    try:
        resp = object_storage.get_object(
            namespace_name=namespace,
            bucket_name=BUCKET_NAME,
            object_name=uri,
        )
        return resp.data.content
    except Exception:
        return None


def render_manual_review(claim_id: str):
    st.markdown(
        "<h1 style='font-family:Playfair Display;color:#17304d;'>"
        "🔍 Manual <span style='color:#fd7e14;'>Review</span></h1>",
        unsafe_allow_html=True,
    )
    if st.button("← Back to Dashboard"):
        st.session_state.page = "dashboard"
        st.rerun()

    details = load_claim_details(claim_id)
    dec_row = details.get("decision_row", {})

    # ── Claim header ──────────────────────────────────────────────────────────
    dec      = dec_row.get("decision",  "—")
    conf     = dec_row.get("confidence", 0)
    payout   = dec_row.get("payout_myr", 0)
    dec_color = DECISION_COLOR.get(dec, "#495057")
    st.markdown(
        f'<div style="background:#fff;border:1px solid #DDE0E3;border-radius:8px;padding:14px 20px;margin-bottom:16px;">'
        f'<span style="font-size:13px;font-weight:600;">📄 Claim: <strong>{claim_id}</strong></span>&nbsp;&nbsp;'
        f'<span style="font-size:13px;font-weight:600;color:{dec_color};">| Decision: {dec}</span>&nbsp;&nbsp;'
        f'<span style="font-size:13px;color:#6c757d;">| Confidence: {conf:.0%} | Payout: RM {payout:,.2f}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Incident Narrative ────────────────────────────────────────────────────
    narrative = details.get("narrative", "")
    if narrative:
        st.markdown("<p style='font-size:11px;font-weight:700;color:#b87716;text-transform:uppercase;margin-top:12px;'>Incident Narrative</p>", unsafe_allow_html=True)
        st.info(narrative)

    # ── AI Summary & Reasons ──────────────────────────────────────────────────
    fusion = dec_row.get("fusion_text", "")
    if fusion:
        st.markdown("<p style='font-size:11px;font-weight:700;color:#b87716;text-transform:uppercase;margin-top:12px;'>AI Summary</p>", unsafe_allow_html=True)
        st.write(fusion)

    reasons = dec_row.get("reasons_json", "")
    if reasons:
        st.markdown("<p style='font-size:11px;font-weight:700;color:#b87716;text-transform:uppercase;margin-top:8px;'>AI Reasons</p>", unsafe_allow_html=True)
        st.write(reasons)

    # ── Evidence Findings ──────────────────────────────────────────────────────
    findings = details.get("findings", [])
    if findings:
        st.markdown("<p style='font-size:11px;font-weight:700;color:#b87716;text-transform:uppercase;margin-top:12px;'>VLM Analysis Findings</p>", unsafe_allow_html=True)
        for f in findings:
            modality   = str(f.get("modality",   "")).upper()
            source_uri = str(f.get("source_uri", ""))
            finding    = str(f.get("findings",   ""))
            conf_val   = float(f.get("confidence") or 0)
            with st.expander(f"{modality} — {source_uri.split('/')[-1]}  (conf: {conf_val:.0%})"):
                st.caption(finding[:1000])

    # ── Evidence Preview ───────────────────────────────────────────────────────
    ev_uris = details.get("evidence_uris", {})
    img1_uri  = ev_uris.get("img1",  "")
    img2_uri  = ev_uris.get("img2",  "")
    video_uri = ev_uris.get("video", "")

    has_media = any([img1_uri, img2_uri, video_uri])
    if has_media:
        st.markdown("<p style='font-size:11px;font-weight:700;color:#b87716;text-transform:uppercase;margin-top:12px;'>Evidence Preview</p>", unsafe_allow_html=True)
        img_cols = [c for c in [img1_uri, img2_uri] if c]
        if img_cols:
            cols = st.columns(len(img_cols))
            for col, uri in zip(cols, img_cols):
                data = _get_oci_bytes(uri)
                if data:
                    col.image(data, caption=uri.split("/")[-1], use_container_width=True)
                else:
                    col.caption(f"⚠️ Could not load: {uri.split('/')[-1]}")
        if video_uri:
            vdata = _get_oci_bytes(video_uri)
            if vdata:
                st.video(vdata)
            else:
                st.caption(f"⚠️ Could not load video: {video_uri.split('/')[-1]}")

    # ── Human Decision Buttons ────────────────────────────────────────────────
    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown("<p style='font-size:13px;font-weight:700;color:#17304d;'>Human Decision Override</p>", unsafe_allow_html=True)

    current_tag = dec_row.get("decision_tag", "")
    if current_tag in ("APPROVE_MANUAL", "REJECT_MANUAL"):
        st.success(f"✅ Already reviewed — tagged as **{current_tag}**")
    else:
        btn_col1, btn_col2, _ = st.columns([1, 1, 3])
        if btn_col1.button("✅  APPROVE", type="primary", use_container_width=True):
            if apply_manual_decision(claim_id, "APPROVE"):
                st.success(f"Claim {claim_id} manually **APPROVED**. Tag: APPROVE_MANUAL")
                st.balloons()
                st.rerun()
            else:
                st.error("Failed to update decision. Check DB connection.")
        if btn_col2.button("❌  REJECT", use_container_width=True):
            if apply_manual_decision(claim_id, "REJECT"):
                st.warning(f"Claim {claim_id} manually **REJECTED**. Tag: REJECT_MANUAL")
                st.rerun()
            else:
                st.error("Failed to update decision. Check DB connection.")


# ── Main Content ──────────────────────────────────────────────────────────────
if st.session_state.page == "dashboard":
    render_dashboard()
elif st.session_state.page == "review" and st.session_state.review_claim_id:
    render_manual_review(st.session_state.review_claim_id)
elif not st.session_state.submitted:

    st.markdown(
        "<h1 style='font-family:Playfair Display; color:#17304d;'>"
        "New <span style='color:#b87716;'>Claim</span> Submission</h1>",
        unsafe_allow_html=True,
    )

    st.markdown(
        "<p style='font-size:11px;font-weight:700;color:#b87716;text-transform:uppercase;'>"
        "Policy Information</p><hr style='margin:0 0 15px;'>",
        unsafe_allow_html=True,
    )

    c1, c2 = st.columns([1, 2])
    existing_ids   = load_existing_policy_ids()
    new_id         = generate_next_policy_id(existing_ids)
    # New ID selalu pertama dan selalu terpilih — user tinggal isi nama & narasi
    policy_options = [new_id] + existing_ids
    policy_id = c1.selectbox("Policy ID", options=policy_options, index=0)
    full_name = c2.text_input("Full Name", value="")

    email_address = st.text_input("Email Address (Gmail) — for decision notification", value="", placeholder="you@gmail.com")

    st.markdown(
        "<p style='font-size:11px;font-weight:700;color:#b87716;text-transform:uppercase;margin-top:20px;'>"
        "Incident Details</p><hr style='margin:0 0 15px;'>",
        unsafe_allow_html=True,
    )
    narrative = st.text_area("Incident Narrative", value="", height=100)

    st.markdown(
        "<p style='font-size:11px;font-weight:700;color:#b87716;text-transform:uppercase;margin-top:20px;'>"
        "Evidence Upload</p><hr style='margin:0 0 15px;'>",
        unsafe_allow_html=True,
    )

    v_file = st.file_uploader("Upload Video", type=["mp4", "mov", "mpeg4"], label_visibility="collapsed")
    if v_file:
        st.video(v_file)

    col_i1, col_i2 = st.columns(2)
    with col_i1:
        img1 = st.file_uploader("Img1", type=["jpg", "png", "jpeg"], label_visibility="collapsed")
        if img1:
            st.image(img1, use_container_width=True)
    with col_i2:
        img2 = st.file_uploader("Img2", type=["jpg", "png", "jpeg"], label_visibility="collapsed")
        if img2:
            st.image(img2, use_container_width=True)

    if st.button("SUBMIT CLAIM", use_container_width=True, type="primary"):

        claim_id = policy_id  # use policy_id as claim_id (matches existing logic)
        st.session_state.claim_id = claim_id

        # Baca bytes sebelum upload agar bisa dipakai VLM
        video_bytes    = v_file.read()  if v_file else None
        video_filename = v_file.name    if v_file else None
        img1_bytes     = img1.read()    if img1   else None
        img1_filename  = img1.name      if img1   else None
        img2_bytes     = img2.read()    if img2   else None
        img2_filename  = img2.name      if img2   else None

        with st.spinner("Uploading evidence to OCI Object Storage..."):
            if v_file:
                v_file.seek(0)
                save_upload(v_file, claim_id, "video-claimant")
            if img1:
                img1.seek(0)
                save_upload(img1, claim_id, "img-claimant")
            if img2:
                img2.seek(0)
                save_upload(img2, claim_id, "img-counterparty")

        with st.spinner("Running Bronze → Silver → Gold pipeline..."):
            decision = run_full_pipeline(
                claim_id=claim_id,
                policy_id=policy_id,
                holder_name=full_name,
                narrative=narrative,
                evidence_prefix=EVIDENCE_PREFIX,
                video_bytes=video_bytes,
                video_filename=video_filename,
                img1_bytes=img1_bytes,
                img1_filename=img1_filename,
                img2_bytes=img2_bytes,
                img2_filename=img2_filename,
            )

        st.session_state.decision  = decision
        wib = dt.timezone(dt.timedelta(hours=7))
        st.session_state.claim_ts  = dt.datetime.now(wib).strftime("%d %B %Y at %H:%M WIB")
        st.session_state.submitted = True
        st.session_state.page      = "new_claim"  # stay on new_claim page to show result

        # Send email notification (non-blocking)
        if email_address:
            with st.spinner("Sending email notification..."):
                sent = send_claim_notification(
                    to_email=email_address,
                    claim_id=decision.get("claim_id",   claim_id),
                    decision=decision.get("decision",   "MANUAL_REVIEW"),
                    action=decision.get("action",       "NOTIFY"),
                    payout_myr=decision.get("est_payout_myr", 0.0),
                    summary=decision.get("fusion_text", ""),
                )
                st.session_state.email_notified = sent

        st.rerun()

else:
    # ── Decision Result Page ──────────────────────────────────────────────────
    st.markdown(
        "<h1 style='font-family:Playfair Display; color:#17304d;'>"
        "Claim <span style='color:#2ecc71;'>Decision</span></h1>",
        unsafe_allow_html=True,
    )

    st.markdown(
        f"<p style='color:#6c757d;font-size:13px;margin-bottom:20px;'>"
        f"Processed on {st.session_state.get('claim_ts','')}</p>",
        unsafe_allow_html=True,
    )

    if st.session_state.decision:
        render_decision_card(st.session_state.decision)
    else:
        st.warning("No decision available.")

    # Email notification status (None = not attempted, True = sent, False = failed)
    if st.session_state.get("email_notified") is True:
        st.success("Email notification sent successfully.")
    elif st.session_state.get("email_notified") is False:
        st.warning("Email notification could not be sent. Check EMAIL_SENDER / EMAIL_APP_PASSWORD in .env.")

    if st.button("Submit New Claim"):
        # Clear cache so new ID is computed from updated DB
        load_existing_policy_ids.clear()
        st.session_state.policy_id     = None   # will be re-initialised on next render
        st.session_state.submitted     = False
        st.session_state.claim_id      = None
        st.session_state.decision      = None
        st.session_state.email_notified = None   # reset for next submission
        st.session_state.page          = "new_claim"
        st.rerun()
