import json
import os
import re

from groq import Groq

from src.models.complaint import Authority, ComplaintInput, ProcessedComplaint

DEFAULT_MODEL = "llama-3.3-70b-versatile"


def _get_client() -> Groq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY is not set")
    return Groq(api_key=api_key)


def _chat(prompt: str, *, json_mode: bool = False) -> str:
    client = _get_client()
    model = os.getenv("GROQ_MODEL", DEFAULT_MODEL)
    kwargs: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content or ""


def _fix_json_control_chars(raw: str) -> str:
    """Escape unescaped newlines/tabs inside JSON string values."""
    out: list[str] = []
    in_string = False
    escape = False
    for ch in raw:
        if escape:
            out.append(ch)
            escape = False
            continue
        if ch == "\\" and in_string:
            out.append(ch)
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            out.append(ch)
            continue
        if in_string and ch == "\n":
            out.append("\\n")
            continue
        if in_string and ch == "\r":
            out.append("\\r")
            continue
        if in_string and ch == "\t":
            out.append("\\t")
            continue
        out.append(ch)
    return "".join(out)


def _parse_json_block(text: str) -> dict | list:
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    raw = match.group(1).strip() if match else text.strip()

    if raw and raw[0] not in "{[":
        obj_match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", raw)
        if obj_match:
            raw = obj_match.group(1)

    for candidate in (raw, _fix_json_control_chars(raw)):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    raise json.JSONDecodeError("Could not parse JSON from model response", raw, 0)


def formalize_complaint(complaint: ComplaintInput) -> tuple[str, str]:
    """Turn informal complaint into a formal letter. Returns (subject, letter_body)."""
    identity = (
        "The complainant wishes to remain anonymous."
        if complaint.is_anonymous
        else f"Name: {complaint.name}\nAddress: {complaint.address}\nEmail: {complaint.email}\nPhone: {complaint.phone}"
    )

    prompt = f"""You are a public grievance officer helping citizens file formal complaints in India.

Location: {complaint.area}, {complaint.city}, {complaint.state}
Primary department complained against: {complaint.primary_department}
Complainant details:
{identity}

Raw informal complaint (may be in Hindi, Hinglish, or any language):
\"\"\"{complaint.informal_text}\"\"\"

Tasks:
1. Translate to clear professional English if needed.
2. Write a formal complaint letter addressed to the relevant government authorities.
3. Include: Subject line, respectful salutation, clear description of the issue with dates/locations if mentioned,
   impact on citizens, specific action requested, and proper closing.
4. Tone: firm, respectful, factual — suitable for government correspondence.
5. If anonymous, do not include personal details in the letter body.
6. Use \\n for line breaks inside formal_letter (valid JSON string).

Respond with a JSON object only (no markdown):
{{
  "subject": "Brief subject line for the email",
  "formal_letter": "Full formal letter. Use \\n for paragraph breaks."
}}
"""
    data = _parse_json_block(_chat(prompt, json_mode=True))
    letter = data["formal_letter"].replace("\\n", "\n")
    return data["subject"], letter


def identify_authorities(complaint: ComplaintInput) -> list[Authority]:
    """Use AI to identify all responsible departments and officials."""
    prompt = f"""You are an expert on Indian government administration and grievance redressal.

Complaint location: {complaint.area}, {complaint.city}, {complaint.state}
Primary department: {complaint.primary_department}
Complaint summary: {complaint.informal_text[:800]}

Identify ALL government departments, officials, and authorities who should receive this complaint.
Include local, district, and state-level authorities as appropriate.

For each authority provide:
- name: official title/department name (e.g. "District Magistrate, Pune", "Municipal Commissioner, Nagpur")
- role: their designation (IAS, IPS, Commissioner, Superintendent, etc.)
- reason: one sentence why they should receive this complaint
- search_queries: 2-3 specific web search queries to find their official contact email/page

Return a JSON object with an "authorities" array, 5-10 entries:
{{
  "authorities": [
    {{
      "name": "...",
      "role": "...",
      "reason": "...",
      "search_queries": ["query1", "query2"]
    }}
  ]
}}
"""
    data = _parse_json_block(_chat(prompt, json_mode=True))
    items = data["authorities"] if isinstance(data, dict) else data

    authorities = []
    for item in items:
        authorities.append(
            Authority(
                name=item["name"],
                role=item.get("role", ""),
                reason=item.get("reason", ""),
                search_queries=item.get("search_queries", []),
            )
        )
    return authorities


def suggest_emails_for_authority(authority: Authority, location: str) -> list[str]:
    """Fallback: ask AI for likely official email patterns when scraping finds nothing."""
    prompt = f"""For the Indian government authority "{authority.name}" ({authority.role}) in {location},
list the most likely official email addresses. Use standard Indian government email patterns
(e.g. dm-[district]@[state].gov.in, commissioner.[city]@nic.in).

Return JSON only:
{{"emails": ["email1@...", "email2@..."]}}

If unsure, provide the most probable pattern-based emails. Max 3 emails.
"""
    try:
        data = _parse_json_block(_chat(prompt, json_mode=True))
        return data.get("emails", [])
    except Exception:
        return []


def process_complaint(
    complaint: ComplaintInput,
    authorities_with_emails: list[Authority],
    subject: str,
    formal_letter: str,
) -> ProcessedComplaint:
    """Finalize processed complaint with all gathered data."""
    all_emails = []
    seen = set()
    for auth in authorities_with_emails:
        for email in auth.emails:
            if email.lower() not in seen:
                seen.add(email.lower())
                all_emails.append(email)

    return ProcessedComplaint(
        formal_letter=formal_letter,
        subject=subject,
        authorities=authorities_with_emails,
        all_emails=all_emails,
        original=complaint,
    )
