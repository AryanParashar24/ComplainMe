# Complain.io

Turn informal public grievances into formal government complaints — automatically find responsible officials and forward your complaint with evidence attached.

## What it does

1. **Simple intake** — write your complaint in Hindi, Hinglish, English, or any language
2. **AI formalization** — Groq (Llama) rewrites it as a professional letter to authorities
3. **Authority mapping** — identifies relevant departments, DMs, commissioners, police, health officers, etc.
4. **Web scraping** — searches gov.in / nic.in sites and extracts official email addresses
5. **Email forwarding** — opens Gmail with the formal complaint pre-filled to all discovered contacts

## Quick start

```bash
# Clone and enter the project
cd complain.io

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your GROQ_API_KEY (required — free at console.groq.com)
# SMTP is optional — only needed for automatic sending without opening Gmail

# Run the app
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GROQ_API_KEY` | Yes | Groq API key for AI processing (free tier at [console.groq.com](https://console.groq.com)) |
| `GROQ_MODEL` | No | Model name (default: `llama-3.3-70b-versatile`) |
| `SMTP_HOST` | No | SMTP server (default: `smtp.gmail.com`) |
| `SMTP_PORT` | No | SMTP port (default: `587`) |
| `SMTP_USER` | No | SMTP username |
| `SMTP_PASSWORD` | No | SMTP password or app password |
| `SMTP_FROM` | No | From address (defaults to `SMTP_USER`) |

Without SMTP, use **Open in Gmail** — the app pre-fills recipients, subject, and body in your logged-in Gmail. Attach photos/videos manually in Gmail before sending.

## Project structure

```
complain.io/
├── app.py                      # Streamlit UI
├── data/departments.json       # Department & state lists
├── src/
│   ├── ai/agent.py             # Groq: formalize + identify authorities
│   ├── scraper/email_finder.py # DuckDuckGo search + web scraping
│   ├── email/sender.py         # SMTP with attachments
│   └── models/complaint.py     # Data models
└── uploads/                    # User-uploaded media (gitignored)
```

## How email discovery works

1. AI identifies 5–10 responsible authorities with targeted search queries
2. DuckDuckGo searches for each authority's official contact page
3. BeautifulSoup scrapes pages (and contact/about links) for email addresses
4. If scraping finds nothing, AI suggests likely gov.in email patterns as fallback
5. All unique emails are collected and used as recipients

## Gmail SMTP setup

1. Enable 2FA on your Google account
2. Create an [App Password](https://myaccount.google.com/apppasswords)
3. Set `SMTP_USER`, `SMTP_PASSWORD`, and `SMTP_FROM` in `.env`

## License

MIT
