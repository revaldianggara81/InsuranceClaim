# app_claim_form.py
import os
import uuid
import datetime as dt
import json
from typing import Optional

import streamlit as st
import oci

st.set_page_config(page_title="Auto Claim Intake Form", page_icon="🚗", layout="centered")

# -----------------------------
# OCI Object Storage Setup (Instance Principal)
# -----------------------------
signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
object_storage = oci.object_storage.ObjectStorageClient(config={}, signer=signer)
namespace = object_storage.get_namespace().data
BUCKET_NAME = "aidp_claims_demo"

# -----------------------------
# Policy Auto Increment via Object Storage JSON
# -----------------------------
SEQUENCE_OBJECT = "config/policy_sequence.json"

def get_next_policy_id():
    try:
        obj = object_storage.get_object(namespace, BUCKET_NAME, SEQUENCE_OBJECT)
        data = json.loads(obj.data.text)
        next_id = data.get("next_id", 45678)
    except Exception:
        next_id = 45678

    new_id = next_id + 1

    object_storage.put_object(
        namespace,
        BUCKET_NAME,
        SEQUENCE_OBJECT,
        json.dumps({"next_id": new_id})
    )

    return f"TX-INS-{new_id}"

# -----------------------------
# Upload to Object Storage
# -----------------------------
def upload_to_object_storage(file, claim_id, folder) -> Optional[str]:
    if not file:
        return None

    object_name = f"claims/{claim_id}/{folder}/{file.name}"

    object_storage.put_object(
        namespace_name=namespace,
        bucket_name=BUCKET_NAME,
        object_name=object_name,
        put_object_body=file.getbuffer()
    )

    return f"oci://{BUCKET_NAME}@{namespace}/{object_name}"

# -----------------------------
# Styling (UNCHANGED)
# -----------------------------
st.markdown(
    """
    <style>
    .stApp { background-color: #f7f9fb; }
    .card { background: white; border-radius: 12px; padding: 18px; box-shadow: 0 2px 8px rgba(23,43,77,0.08); }
    .muted { color: #6b7280; font-size: 14px; }
    .section-title { font-weight: 700; font-size: 18px; margin-bottom: 8px; }
    .logo { font-weight:700; font-size:22px; color:#0b66c3; }
    </style>
    """,
    unsafe_allow_html=True,
)

# -----------------------------
# Header
# -----------------------------
col1, col2 = st.columns([1,3])
with col1:
    st.markdown('<div class="logo">AutoClaimPro</div>', unsafe_allow_html=True)
with col2:
    st.markdown("### Auto Claim Intake Form")

st.write("")
st.markdown('<div class="card">', unsafe_allow_html=True)

# -----------------------------
# Form (UNCHANGED PATTERN)
# -----------------------------
with st.form("claim_form"):

    st.markdown('<div class="section-title">Policy</div>', unsafe_allow_html=True)
    policy_placeholder = st.empty()

    st.write("---")
    st.markdown('<div class="section-title">Incident Details</div>', unsafe_allow_html=True)

    incident_date = st.date_input("Incident Date (UTC)")
    incident_time = st.time_input("Incident Time (UTC)")

    narrative = st.text_area("Claimant's Narrative", height=120)

    st.write("---")
    st.markdown('<div class="section-title">Evidence</div>', unsafe_allow_html=True)

    video_file_claimant = st.file_uploader("Video (claimant)", type=["mp4","mov","avi","mkv"])
    img_claimant = st.file_uploader("Photo: Claimant vehicle", type=["jpg","jpeg","png","webp"])
    img_counter = st.file_uploader("Photo: Counterparty vehicle", type=["jpg","jpeg","png","webp"])

    submit_clicked = st.form_submit_button("Submit")

st.markdown('</div>', unsafe_allow_html=True)

# -----------------------------
# Submit Handler
# -----------------------------
if submit_clicked:

    if not incident_date:
        st.error("Incident Date is required.")
        st.stop()

    # 1Generate claim_id
    claim_id = f"CLM-{uuid.uuid4().hex[:8]}"

    # Auto increment policy_id
    policy_id = get_next_policy_id()

    incident_ts = dt.datetime.combine(incident_date, incident_time)

    # pload files to Object Storage
    video_uri_claimant = upload_to_object_storage(video_file_claimant, claim_id, "claimant_video_evidence")
    image_uri_claimant = upload_to_object_storage(img_claimant, claim_id, "claimant_img_evidence")
    image_uri_counterparty = upload_to_object_storage(img_counter, claim_id, "counterparty_img_evidence")

    # Build payload (for API call later if needed)
    payload = {
        "claim_id": claim_id,
        "policy_id": policy_id,
        "incident_ts": incident_ts.isoformat(),
        "narrative": narrative,
        "video_uri_claimant": video_uri_claimant,
        "image_uri_claimant": image_uri_claimant,
        "image_uri_counterparty": image_uri_counterparty,
        "status": "RECEIVED",
        "created_at": dt.datetime.utcnow().isoformat()
    }

    st.success("Claim Submitted Successfully.")
    st.markdown(
        f"<h3 style='text-align:center; color:#0000FF; font-weight:bold;'>Claim ID# {claim_id}</h3>",
        unsafe_allow_html=True
    )

    st.markdown(f"**Policy ID:** {policy_id}")