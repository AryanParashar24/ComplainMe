"""Complain.io — End-to-end public grievance platform."""

import json
import uuid
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from src.ai.agent import (
    formalize_complaint,
    identify_authorities,
    process_complaint,
    suggest_emails_for_authority,
)
from src.email.gmail_draft import (
    create_gmail_draft,
    credentials_from_session,
    credentials_to_session,
    exchange_code,
    get_auth_url,
    oauth_configured,
)
from src.email.mime_builder import load_attachment_payloads
from src.email.sender import build_eml_download, get_compose_links, send_complaint_email_smtp
from src.email.share_component import render_share_to_mail
from src.models.complaint import ComplaintInput
from src.scraper.email_finder import discover_all_emails

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Complain.io",
    page_icon="logo.png",
    layout="wide",
    initial_sidebar_state="expanded",
)

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

DATA_PATH = Path("data/departments.json")
with open(DATA_PATH) as f:
    CONFIG = json.load(f)


def save_uploads(uploaded_files) -> list[Path]:
    paths = []
    for uf in uploaded_files or []:
        dest = UPLOAD_DIR / f"{uuid.uuid4().hex[:8]}_{uf.name}"
        dest.write_bytes(uf.getbuffer())
        paths.append(dest)
    return paths


def render_header():
    # We use a container with display: flex for the "Gmail-like" alignment.
    # Note: src="app/static/logo.png" is the correct path for Streamlit static files.
    st.markdown(
        """
        <div style="display: flex; align-items: center; gap: 15px; margin-bottom: 20px;">
            <img src="app/static/logo.png" style="width: 55px; height: auto;">
            <h1 style="margin: 0; font-family: sans-serif; font-weight: 500;">Complain.io</h1>
        </div>
        """,
        unsafe_allow_html=True
    )
    
    st.markdown(
        "Write your complaint in **plain, informal language** — we'll turn it into a formal letter, "
        "find the right government officials, and forward it with your photos/videos attached."
    )
    st.write("---")
    

def render_complaint_form() -> ComplaintInput | None:
    st.header("1. Tell us what's wrong")

    col1, col2 = st.columns(2)
    with col1:
        state = st.selectbox("State / UT", [""] + CONFIG["indian_states"])
        city = st.text_input("City / Town", placeholder="e.g. Delhi, Bangalore, Lucknow")
    with col2:
        area = st.text_input("Area / Village / Locality (optional)", placeholder="e.g. Kothrud, Sector 12")
        department = st.selectbox(
            "Which department is this mainly about?",
            [""] + CONFIG["departments"],
        )

    complaint_text = st.text_area(
        "Describe your problem (any language — Hindi, Hinglish, English, whatever is easiest):",
        height=160,
        placeholder=(
            "Example: 'Hamare mohalle mein 3 hafte se kachra nahi uthaya gaya, "
            "badbu aa rahi hai aur bachche bimar pad rahe hain. Please kuch karo!'"
        ),
    )

    st.subheader("Attach evidence (optional)")
    uploaded = st.file_uploader(
        "Photos or videos showing the problem",
        type=["jpg", "jpeg", "png", "gif", "webp", "mp4", "mov", "avi", "pdf"],
        accept_multiple_files=True,
    )
    if uploaded:
        cols = st.columns(min(len(uploaded), 4))
        for i, f in enumerate(uploaded):
            with cols[i % 4]:
                if f.type and f.type.startswith("image"):
                    st.image(f, caption=f.name, use_container_width=True)
                else:
                    st.write(f"📎 {f.name} ({f.size // 1024} KB)")

    st.divider()
    st.header("2. Your details (optional)")

    is_anonymous = st.checkbox("Submit anonymously", value=False)

    name = address = email = phone = ""
    if not is_anonymous:
        c1, c2 = st.columns(2)
        with c1:
            name = st.text_input("Your name")
            email = st.text_input("Your email (for replies)")
        with c2:
            address = st.text_area("Your address", height=80)
            phone = st.text_input("Phone number (optional)")

    submitted = st.button("🚀 Process & Forward Complaint", type="primary", use_container_width=True)

    if not submitted:
        return None

    if not complaint_text.strip():
        st.error("Please describe your complaint.")
        return None
    if not department:
        st.error("Please select a department.")
        return None
    if not state or not city:
        st.error("Please provide your state and city.")
        return None

    media_paths = save_uploads(uploaded)
    return ComplaintInput(
        informal_text=complaint_text.strip(),
        primary_department=department,
        state=state,
        city=city,
        area=area.strip(),
        is_anonymous=is_anonymous,
        name=name.strip(),
        address=address.strip(),
        email=email.strip(),
        phone=phone.strip(),
        media_paths=media_paths,
    )


def run_pipeline(complaint: ComplaintInput):
    location = f"{complaint.area}, {complaint.city}, {complaint.state}".strip(", ")

    with st.status("Processing your complaint...", expanded=True) as status:
        st.write("✍️ Formalizing your complaint with AI...")
        subject, formal_letter = formalize_complaint(complaint)

        st.write("🏛️ Identifying responsible departments & officials...")
        authorities = identify_authorities(complaint)

        st.write("🔍 Searching the web for official email addresses...")
        authorities = discover_all_emails(authorities, location)

        st.write("📧 Filling gaps with AI-suggested contacts...")
        for auth in authorities:
            if not auth.emails:
                auth.emails = suggest_emails_for_authority(auth, location)

        processed = process_complaint(complaint, authorities, subject, formal_letter)

        status.update(label="Analysis complete!", state="complete", expanded=False)

    st.session_state["processed"] = processed
    st.session_state["processed_at"] = datetime.now().isoformat()


def render_results():
    processed = st.session_state.get("processed")
    if not processed:
        return

    st.divider()
    st.header("3. Results")

    tab_letter, tab_recipients, tab_send = st.tabs(["📄 Formal Letter", "📬 Recipients", "✉️ Send"])

    with tab_letter:
        st.markdown(f"**Subject:** {processed.subject}")
        edited = st.text_area("Review & edit before sending:", value=processed.formal_letter, height=400)
        processed.formal_letter = edited

        if processed.original.media_paths:
            st.subheader("Attached media")
            cols = st.columns(min(len(processed.original.media_paths), 4))
            for i, p in enumerate(processed.original.media_paths):
                with cols[i % 4]:
                    if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
                        st.image(str(p), caption=p.name, use_container_width=True)
                    else:
                        st.write(f"📎 {p.name}")

    with tab_recipients:
        total_emails = len(processed.all_emails)
        st.metric("Email addresses found", total_emails)

        for auth in processed.authorities:
            with st.expander(f"**{auth.name}** — {auth.role}", expanded=total_emails <= 5):
                st.write(auth.reason)
                if auth.emails:
                    for e in auth.emails:
                        st.code(e, language=None)
                else:
                    st.warning("No email found via web scraping — AI suggestion used if available.")
                if auth.source_urls:
                    st.caption("Sources scraped:")
                    for url in auth.source_urls[:3]:
                        st.markdown(f"- [{url}]({url})")

        if not processed.all_emails:
            st.error(
                "No emails were discovered. Try adding more location details, "
                "or manually add emails below before sending."
            )
            manual = st.text_area(
                "Manual email addresses (comma-separated)",
                placeholder="dm-pune@maharashtra.gov.in, health.pune@municipal.gov.in",
            )
            if manual.strip():
                processed.all_emails = [e.strip() for e in manual.split(",") if e.strip()]

    with tab_send:
        st.markdown(
            "Send from **your own email** — recipients and formal letter are pre-filled. "
            "Use the options below to include your photos/videos as attachments."
        )

        cc_user = False
        if processed.original.email and not processed.original.is_anonymous:
            cc_user = st.checkbox(f"CC me at {processed.original.email}", value=True)

        cc = [processed.original.email] if cc_user and processed.original.email else None
        links = get_compose_links(processed, cc_emails=cc)
        has_media = bool(processed.original.media_paths)

        if not links.get("success"):
            st.error(links.get("error", "Could not build email links."))
            return

        st.markdown("**Recipients**")
        st.write(f"**To:** {links['to']}")
        if links["cc_list"]:
            st.write(f"**CC:** {', '.join(links['cc_list'])}")

        if has_media:
            st.subheader("Send with attachments")
            st.caption("Gmail web links cannot auto-attach files — use one of these instead:")

            eml_data = build_eml_download(processed, cc_emails=cc, from_email=processed.original.email or "")
            st.download_button(
                "📥 Download email (.eml) with all attachments",
                data=eml_data,
                file_name="complaint_with_attachments.eml",
                mime="message/rfc822",
                use_container_width=True,
                help="Open this file — your mail app loads the full email with photos/videos attached.",
            )
            st.caption("Desktop: open the .eml file (Outlook, Apple Mail, Thunderbird). It includes all media.")

            attachments = load_attachment_payloads(processed)
            if attachments:
                render_share_to_mail(processed.subject, processed.formal_letter, attachments)
                st.caption("Phone: tap Share above → pick Gmail. Text + files are attached automatically.")

            if oauth_configured():
                if "gmail_token" not in st.session_state:
                    st.link_button(
                        "🔐 Sign in with Google → save Gmail draft (with attachments)",
                        get_auth_url(),
                        use_container_width=True,
                    )
                elif st.button("📧 Create Gmail draft with attachments", use_container_width=True):
                    try:
                        creds = credentials_from_session(st.session_state["gmail_token"])
                        draft = create_gmail_draft(
                            creds, processed, cc_emails=cc, from_email=processed.original.email or ""
                        )
                        st.session_state["gmail_draft_url"] = draft["drafts_url"]
                        st.success("Draft saved in Gmail with all attachments! Open Drafts below.")
                    except Exception as e:
                        st.error(f"Could not create Gmail draft: {e}")
                if st.session_state.get("gmail_draft_url"):
                    st.link_button(
                        "Open Gmail Drafts folder",
                        st.session_state["gmail_draft_url"],
                        use_container_width=True,
                    )
            else:
                with st.expander("Optional: auto-attach in Gmail browser (one-time Google setup)"):
                    st.markdown(
                        "Add `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` to `.env` "
                        "to save a Gmail draft with attachments. See README."
                    )

            st.divider()

        st.subheader("Quick open (text only)" if has_media else "Open in your mail app")
        if links.get("body_truncated"):
            st.warning(
                "Letter is long — copy the full text from the **Formal Letter** tab if needed."
            )

        col1, col2 = st.columns(2)
        with col1:
            st.link_button(
                "📧 Open in Gmail (browser)",
                links["gmail_url"],
                use_container_width=True,
            )
        with col2:
            st.markdown(
                f'<a href="{links["mailto_url"]}" target="_blank" '
                f'style="display:block;text-align:center;padding:12px 20px;'
                f'background:#1a73e8;color:white;text-decoration:none;border-radius:8px;'
                f'font-weight:500;">📱 Open in Mail App</a>',
                unsafe_allow_html=True,
            )
        if has_media:
            st.caption("These links pre-fill text and recipients only — use .eml or Share above for media.")

        with st.expander("Advanced: send directly via Gmail app password"):
            st.caption(
                "Sends immediately with attachments. Use a [Gmail App Password](https://myaccount.google.com/apppasswords) "
                "— not your normal login password."
            )
            smtp_user = st.text_input("Your Gmail", value=processed.original.email or "")
            smtp_pass = st.text_input("Gmail App Password", type="password")
            if st.button("Send now with attachments"):
                with st.spinner("Sending..."):
                    result = send_complaint_email_smtp(
                        processed, cc_emails=cc, smtp_user=smtp_user, smtp_password=smtp_pass
                    )
                if result["success"]:
                    st.success(f"Sent to {len(result['sent_to'])} recipient(s) with attachments!")
                else:
                    st.error(f"Send failed: {result.get('error', 'Unknown error')}")


def render_sidebar():
    with st.sidebar:
        st.header("How it works")
        st.markdown(
            """
1. **You complain** — in any language, as informal as you like
2. **AI formalizes** — turns it into a proper government letter
3. **We research** — finds departments, officers, DMs, commissioners, etc.
4. **Web scraper** — pulls official emails from gov.in / nic.in sites
5. **You send** — opens Gmail with everything pre-filled; you hit Send
            """
        )
        st.divider()
        if not __import__("os").getenv("GROQ_API_KEY"):
            st.error("Set `GROQ_API_KEY` in `.env` to enable AI.")
        else:
            st.success("AI (Groq) connected")
        st.info("Email opens in your Gmail — no SMTP password needed.")


def handle_gmail_oauth_callback():
    if not oauth_configured() or "code" not in st.query_params:
        return
    try:
        creds = exchange_code(st.query_params["code"])
        st.session_state["gmail_token"] = credentials_to_session(creds)
        st.query_params.clear()
        st.toast("Gmail connected — you can now create drafts with attachments.")
    except Exception as e:
        st.error(f"Gmail sign-in failed: {e}")


def main():
    handle_gmail_oauth_callback()
    render_header()
    render_sidebar()

    complaint = render_complaint_form()
    if complaint:
        if not __import__("os").getenv("GROQ_API_KEY"):
            st.error("Please set GROQ_API_KEY in your .env file.")
        else:
            run_pipeline(complaint)

    render_results()


if __name__ == "__main__":
    main()
