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
from src.email.sender import get_compose_links, send_complaint_email_smtp
from src.models.complaint import ComplaintInput
from src.scraper.email_finder import discover_all_emails

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Complain.io",
    page_icon="📢",
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
    st.title("📢 Complain.io")
    st.markdown(
        "Write your complaint in **plain, informal language** — we'll turn it into a formal letter, "
        "find the right government officials, and forward it with your photos/videos attached."
    )


def render_complaint_form() -> ComplaintInput | None:
    st.header("1. Tell us what's wrong")

    col1, col2 = st.columns(2)
    with col1:
        state = st.selectbox("State / UT", [""] + CONFIG["indian_states"])
        city = st.text_input("City / Town", placeholder="e.g. Pune, Lucknow, Bhopal")
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
            "Send from **your own Gmail** — we pre-fill the formal letter and all official emails. "
            "You just sign in (if needed) and hit Send. No passwords stored in this app."
        )

        cc_user = False
        if processed.original.email and not processed.original.is_anonymous:
            cc_user = st.checkbox(f"CC me at {processed.original.email}", value=True)

        cc = [processed.original.email] if cc_user and processed.original.email else None
        links = get_compose_links(processed, cc_emails=cc)

        if not links.get("success"):
            st.error(links.get("error", "Could not build email links."))
        else:
            if links.get("body_truncated"):
                st.warning(
                    "The letter is long — Gmail opens with a short preview. "
                    "Copy the full text from the **Formal Letter** tab and paste it in Gmail before sending."
                )

            if links.get("has_attachments"):
                st.warning(
                    "Photos/videos cannot be attached automatically via a web link. "
                    "Please attach them manually in Gmail before sending."
                )

            st.markdown("**Recipients**")
            st.write(f"**To:** {links['to']}")
            if links["cc_list"]:
                st.write(f"**CC:** {', '.join(links['cc_list'])}")

            col1, col2 = st.columns(2)
            with col1:
                st.link_button(
                    "📧 Open in Gmail (browser)",
                    links["gmail_url"],
                    use_container_width=True,
                    help="Opens Gmail compose in your browser. Works best on desktop.",
                )
            with col2:
                st.markdown(
                    f'<a href="{links["mailto_url"]}" target="_blank" '
                    f'style="display:block;text-align:center;padding:12px 20px;'
                    f'background:#1a73e8;color:white;text-decoration:none;border-radius:8px;'
                    f'font-weight:500;">📱 Open in Mail App</a>',
                    unsafe_allow_html=True,
                )
                st.caption("On phone, this usually opens the Gmail app if installed.")

            with st.expander("Advanced: auto-send via SMTP (needs app password)"):
                st.caption("Only use this if you have configured SMTP_USER and SMTP_PASSWORD in .env")
                if st.button("Send automatically via SMTP"):
                    with st.spinner("Sending..."):
                        result = send_complaint_email_smtp(processed, cc_emails=cc)
                    if result["success"]:
                        st.success(f"Sent to {len(result['sent_to'])} recipient(s)!")
                    else:
                        st.error(f"SMTP failed: {result.get('error', 'Unknown error')}")


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


def main():
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
