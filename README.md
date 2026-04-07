# InsuranceClaim — AI-Powered Auto Insurance Claims Processing System

An end-to-end, AI-driven insurance claim adjudication system that combines **Vision Language Models (VLM)** for evidence analysis, a **deterministic rule engine** for transparent decisions, and an **LLM** for professional narrative generation — all served via a Streamlit web UI and backed by a multi-layer Oracle Database.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Data Pipeline: Medallion Architecture](#data-pipeline-medallion-architecture)
- [Decision Logic](#decision-logic)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Getting Started](#getting-started)
- [Environment Variables](#environment-variables)
- [Database Schema](#database-schema)
- [Application Pages](#application-pages)
- [Knowledge Base & Policy Citations](#knowledge-base--policy-citations)
- [Email Notifications](#email-notifications)

---

## Overview

When a claimant submits an auto insurance claim, the system:

1. Accepts the claim form and evidence (video + images) via a web UI
2. Uploads evidence to Oracle RED Object Storage
3. Runs the evidence through a **VLM (llava:7b)** for visual fraud detection
4. Applies a **rule engine** to produce a transparent, auditable decision
5. Generates a **professional adjuster narrative** using an LLM (qwen2:7b) with policy citations
6. Persists the full decision to Oracle Database
7. Sends an **email notification** to the claimant
8. Exposes a **dashboard** and **manual review** interface for human adjusters

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                      Streamlit Web UI                            │
│     New Claim Form │ Claim Dashboard │ Manual Review             │
└──────────────────────────┬───────────────────────────────────────┘
                           │ Submit
                           ▼
              ┌────────────────────────┐
              │   RED Object Storage   │  ← evidence upload (video/images)
              └────────────┬───────────┘
                           │ URI
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Pipeline (streamlit_pipeline.py)              │
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐   │
│  │ BRONZE LAYER │───▶│ SILVER LAYER │───▶│   GOLD LAYER     │   │
│  │ inbound_     │    │ evidence_    │    │  claim_decision  │   │
│  │ claims       │    │ summary      │    │  (final output)  │   │
│  └──────────────┘    └──────┬───────┘    └──────────────────┘   │
│                             │                                    │
│                    ┌────────▼─────────┐                         │
│                    │  VLM Analyzer    │  llava:7b                │
│                    │  (vlm_analyzer)  │  image + video analysis  │
│                    └────────┬─────────┘                         │
│                             │                                    │
│                    ┌────────▼─────────┐                         │
│                    │  Rule Engine     │  deterministic rules     │
│                    │  (silver_to_gold)│  R0–R6                  │
│                    └────────┬─────────┘                         │
│                             │                                    │
│                    ┌────────▼─────────┐                         │
│                    │  LLM Narrative   │  qwen2:7b                │
│                    │  Generation      │  with policy context     │
│                    └──────────────────┘                         │
└──────────────────────────────────────────────────────────────────┘
                           │
                  ┌────────▼────────┐
                  │  Email Notifier │  Gmail SMTP
                  └─────────────────┘
```

---

## Project Structure

```
InsuranceClaim/
├── Streamlit/
│   ├── app_claim_form.py       # Main web application (3 pages)
│   ├── requirements.txt        # Streamlit-specific dependencies
│   └── oracle_favicon.png
│
├── pipeline/
│   ├── streamlit_pipeline.py   # Pipeline orchestrator (Bronze→Silver→Gold)
│   ├── vlm_analyzer.py         # VLM image/video analysis (llava:7b)
│   ├── silver_to_gold.py       # Rule engine + LLM narrative generation
│   ├── kb_loader.py            # Policy PDF knowledge base loader
│   ├── email_notifier.py       # Gmail HTML notification sender
│   └── dashboard_queries.py    # SQL query helpers for dashboard
│
├── sql/
│   ├── bronze.sql              # inbound_claims table
│   ├── silver.sql              # claim_evidence_summary table
│   ├── gold.sql                # claims, policies, drivers, claim_decision tables
│   ├── init.sql                # DB initialization script
│   └── create_user.sql         # Schema user creation
│
├── knowledge_base/
│   └── Private_Car_Policy_Wording_M_PCP.pdf  # Policy document for LLM context
│
├── scripts/
│   └── ollama_init.sh          # Pull and initialize Ollama models
│
├── Claim Evidence/             # Local evidence staging directory
├── docker-compose.yml          # 3-service Docker orchestration
├── Dockerfile                  # Oracle DB image
├── Dockerfile.streamlit        # Streamlit app image
├── start.sh                    # Full deployment script
├── requirements.txt            # Base Python dependencies
└── .env.example                # Environment variable template
```

---

## Data Pipeline: Medallion Architecture

The system implements a **Bronze → Silver → Gold** medallion pattern for data governance and traceability.

### Bronze — Raw Inbound Data

Table: `BRONZE.INBOUND_CLAIMS`

Stores the raw claim as submitted. No processing applied yet.

| Column | Description |
|---|---|
| `claim_id_ext` | External claim ID |
| `policy_id` | Claimant's policy number |
| `incident_ts` | Date/time of incident |
| `narrative` | Claimant's written description |
| `video_uri` | RED Object Storage URI for video |
| `image_uri_claimant` | URI for claimant's photo evidence |
| `image_uri_counterparty` | URI for counterparty photo evidence |

### Silver — VLM Evidence Analysis

Table: `SILVER.CLAIM_EVIDENCE_SUMMARY`

Stores the output from the Vision Language Model for each piece of evidence.

| Column | Description |
|---|---|
| `modality` | `image` or `video` |
| `source_uri` | Evidence URI analyzed |
| `findings` | VLM output prefixed with `[VALID_ACCIDENT]` or `[NOT_ACCIDENT]` |
| `confidence` | 0.0–1.0 confidence score |

**VLM classification labels:**
- `VALID_ACCIDENT` — Evidence confirms an accident
- `NOT_ACCIDENT` — Evidence does not show an accident (triggers immediate rejection)
- `UNCLEAR` — Low-confidence fallback (triggers manual review)

### Gold — Business Decision Output

Table: `GOLD.CLAIM_DECISION`

The final adjudicated decision ready for downstream systems or display.

| Column | Description |
|---|---|
| `decision` | `APPROVE`, `APPROVE_FAST_TRACK`, `REJECT`, `MANUAL_REVIEW` |
| `action` | `PAYOUT`, `NOTIFY`, `ESCALATE`, `ARCHIVE` |
| `decision_tag` | `APPROVE_SYSTEM`, `REJECT_SYSTEM`, `APPROVE_MANUAL`, `REJECT_MANUAL`, `PENDING_REVIEW` |
| `est_payout_usd` | Estimated payout in USD |
| `fusion_text` | Professional 5-sentence adjuster narrative |
| `reasons_json` | Structured reasons array with policy page citations |
| `confidence` | Aggregated confidence from VLM |

---

## Decision Logic

The rule engine (`silver_to_gold.py`) applies rules in priority order. The **first matching rule wins**.

| Rule | Condition | Decision | Action |
|---|---|---|---|
| R0 | VLM classified `NOT_ACCIDENT` | `REJECT` | `ARCHIVE` |
| R1 | Policy is inactive | `REJECT` | `NOTIFY` |
| R2 | Duplicate claim detected | `MANUAL_REVIEW` | `ESCALATE` |
| R3 | Confidence < 70% | `MANUAL_REVIEW` | `ESCALATE` |
| R4 | Video evidence + confidence ≥ 85% | `APPROVE_FAST_TRACK` | `PAYOUT` |
| R5 | Image evidence + confidence ≥ 80% | `APPROVE` | `PAYOUT` |
| R6 | Default fallback | `MANUAL_REVIEW` | `ESCALATE` |

**Payout calculation:**

```
est_payout_usd = (policy_limit_myr / 4.70) × modifier × confidence

modifier:
  - APPROVE_FAST_TRACK (video): 0.80
  - APPROVE (image):             0.60
```

**Safety gate:** If `NOT_ACCIDENT` is detected in any evidence, the pipeline aborts **before writing to the database** and returns an immediate rejection to the UI.

---

## Tech Stack

| Component | Technology |
|---|---|
| Web UI | Streamlit |
| VLM (image/video analysis) | Ollama + llava:7b |
| LLM (narrative generation) | Ollama + qwen2:7b |
| Database | Oracle Database Free Edition |
| Object Storage | Oracle RED Object Storage (OCI) |
| Containerization | Docker + Docker Compose |
| Email | Gmail SMTP (HTML) |
| Language | Python 3 |

---

## Prerequisites

- Docker and Docker Compose installed
- A configured `.env` file (see [Environment Variables](#environment-variables))
- Oracle RED / OCI Object Storage bucket for evidence
- Gmail account with App Password enabled for email notifications
- Minimum 16GB RAM recommended (for running Ollama models)

---

## Getting Started

### 1. Clone the repository

```bash
git clone git@github.com:revaldianggara81/insuranceClaim-RED.git
cd insuranceClaim-RED
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your credentials
```

### 3. Start all services

```bash
chmod +x start.sh
./start.sh
```

`start.sh` will:
- Install Docker/Docker Compose if not present
- Pull Ollama models (`llava:7b`, `qwen2:7b`)
- Build and start 3 containers: `oracle-db`, `ollama`, `streamlit`
- Register a systemd service for auto-start on reboot

### 4. Access the application

| Service | URL |
|---|---|
| Streamlit UI | `http://<YOUR_IP>:8501` |
| Ollama API | `http://<YOUR_IP>:11434` |
| Oracle DB | `<YOUR_IP>:1521` (service: `FREEPDB1`) |

---

## Environment Variables

Copy `.env.example` to `.env` and fill in all values.

```env
# Oracle Database — Bronze layer
BRONZE_USER=bronze_user
BRONZE_PASSWORD=<your_password>
BRONZE_DSN=localhost:1521/FREEPDB1

# Oracle Database — Silver layer
SILVER_USER=silver_user
SILVER_PASSWORD=<your_password>
SILVER_DSN=localhost:1521/FREEPDB1

# Oracle Database — Gold layer
GOLD_USER=gold_user
GOLD_PASSWORD=<your_password>
GOLD_DSN=localhost:1521/FREEPDB1

# Ollama
VLM_MODEL=llava:7b
TEXT_MODEL=qwen2:7b
OLLAMA_BASE_URL=http://ollama:11434/v1

# Oracle RED Object Storage
RED_STORAGE_URL=<your_object_storage_url>
RED_ACCESS_KEY=<your_access_key>
RED_SECRET_KEY=<your_secret_key>

# Knowledge Base
KB_LOCAL_PATH=/app/knowledge_base
KB_PDF_PAR_URL=<pre-authenticated_url_to_policy_pdf>  # optional, for clickable citations

# Email (Gmail)
EMAIL_SENDER=your@gmail.com
EMAIL_APP_PASSWORD=<gmail_app_password>
```

---

## Database Schema

The three schemas map directly to the medallion layers:

```
BRONZE schema
└── INBOUND_CLAIMS           ← raw claim submissions

SILVER schema
└── CLAIM_EVIDENCE_SUMMARY   ← VLM analysis results per evidence file

GOLD schema
├── DRIVERS                  ← driver master data
├── POLICIES                 ← policy master data (limits, status, coverage)
├── CLAIMS                   ← historical claim reference
└── CLAIM_DECISION           ← final adjudicated decisions (primary output)
```

Foreign key relationships: `POLICIES → DRIVERS`, `CLAIM_DECISION → POLICIES`

---

## Application Pages

### New Claim

The primary claim submission form. Fields:
- Policy ID and claimant name
- Incident date and narrative description
- Email address (for notification)
- Evidence upload: 1 video (mp4/mov) + 2 images (jpg/png)

On submit, the full pipeline runs synchronously and returns the decision.

### Claim Dashboard

A sortable, filterable table of all claims with their decisions, actions, confidence scores, and payout estimates. Useful for adjusters to monitor volume and status.

### Manual Review

Lists all claims with `PENDING_REVIEW` status. Adjusters can:
- Read the VLM findings and LLM narrative
- Click **Approve** or **Reject** to override the system decision
- The `decision_tag` updates to `APPROVE_MANUAL` or `REJECT_MANUAL`

---

## Knowledge Base & Policy Citations

The file `knowledge_base/Private_Car_Policy_Wording_M_PCP.pdf` is loaded by `kb_loader.py` and passed as context to the LLM during narrative generation.

- The LLM is instructed to cite specific pages using `[Page N]` notation
- In the Manual Review UI, citations render as clickable links to the policy PDF (requires `KB_PDF_PAR_URL` to be set in `.env`)
- No vector embeddings or semantic search are used — the first 15 pages of the PDF are extracted as plain text and appended to the LLM prompt

---

## Email Notifications

After every pipeline run, an HTML-formatted email is sent to the claimant's provided address via Gmail SMTP. The email includes:

- Claim decision and action
- Estimated payout (if applicable)
- Professional adjuster summary (`fusion_text`)
- Structured reasons with policy page references

To enable, configure `EMAIL_SENDER` and `EMAIL_APP_PASSWORD` in `.env`. Gmail requires an [App Password](https://support.google.com/accounts/answer/185833) (not your regular password).
