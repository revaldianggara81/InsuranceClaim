"""
Email Notifier — Gmail SMTP
Sends claim decision notification to claimant.
Config: EMAIL_SENDER and EMAIL_APP_PASSWORD in .env
"""
import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

log = logging.getLogger(__name__)

DECISION_COLOR = {
    "APPROVE_FAST_TRACK": "#2e7d32",
    "APPROVE":            "#2e7d32",
    "REJECT":             "#c62828",
    "MANUAL_REVIEW":      "#e65100",
}
DECISION_ICON = {
    "APPROVE_FAST_TRACK": "✅",
    "APPROVE":            "✅",
    "REJECT":             "❌",
    "MANUAL_REVIEW":      "⚠️",
}


def send_claim_notification(
    to_email:   str,
    claim_id:   str,
    decision:   str,
    action:     str,
    payout_myr: float,
    summary:    str,
) -> bool:
    """
    Send HTML email notification via Gmail SMTP.
    Returns True on success, False on failure (never raises).
    """
    sender   = os.getenv("EMAIL_SENDER",       "")
    password = os.getenv("EMAIL_APP_PASSWORD", "")

    if not sender or not password:
        log.warning("[Email] Skipped — EMAIL_SENDER / EMAIL_APP_PASSWORD not set in .env")
        return False
    if not to_email or "@" not in to_email:
        log.warning(f"[Email] Skipped — invalid recipient: {to_email!r}")
        return False

    icon  = DECISION_ICON.get(decision,  "📋")
    color = DECISION_COLOR.get(decision, "#333333")

    subject = f"[Claim Notification] {icon} {claim_id} — {decision}"

    html = (
        "<html><body style='font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto;'>"
        "<div style='background:#17304d;padding:24px;border-radius:8px 8px 0 0;'>"
        "<h2 style='color:#fff;margin:0;font-size:20px;'>🛡️ Insurance Claim Decision</h2>"
        "</div>"
        "<div style='background:#fff;padding:24px;border:1px solid #ddd;border-radius:0 0 8px 8px;'>"
        "<table style='width:100%;border-collapse:collapse;margin-bottom:20px;'>"
        f"<tr><td style='padding:10px 12px;background:#f5f5f5;font-weight:bold;width:140px;'>Claim ID</td>"
        f"<td style='padding:10px 12px;border-bottom:1px solid #eee;'><strong>{claim_id}</strong></td></tr>"
        f"<tr><td style='padding:10px 12px;background:#f5f5f5;font-weight:bold;'>Decision</td>"
        f"<td style='padding:10px 12px;border-bottom:1px solid #eee;color:{color};font-weight:bold;'>{icon} {decision}</td></tr>"
        f"<tr><td style='padding:10px 12px;background:#f5f5f5;font-weight:bold;'>Action</td>"
        f"<td style='padding:10px 12px;border-bottom:1px solid #eee;'>{action}</td></tr>"
        f"<tr><td style='padding:10px 12px;background:#f5f5f5;font-weight:bold;'>Payout</td>"
        f"<td style='padding:10px 12px;border-bottom:1px solid #eee;font-weight:bold;'>RM {payout_myr:,.2f}</td></tr>"
        "</table>"
        "<h3 style='color:#17304d;font-size:15px;margin-bottom:8px;'>Claim Summary</h3>"
        f"<p style='line-height:1.7;color:#555;'>{summary}</p>"
        "<hr style='border:none;border-top:1px solid #eee;margin:20px 0;'>"
        "<p style='font-size:11px;color:#aaa;'>This is an automated notification from the Insurance Claim Processing System. "
        "Please do not reply to this email.</p>"
        "</div>"
        "</body></html>"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = to_email
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as smtp:
            smtp.login(sender, password)
            smtp.sendmail(sender, to_email, msg.as_string())
        log.info(f"[Email] Sent → {to_email} ({claim_id} / {decision})")
        return True
    except Exception as e:
        log.error(f"[Email] Failed for {claim_id}: {type(e).__name__}: {e}")
        return False
