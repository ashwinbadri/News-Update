import os
import json
import requests
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from openai import OpenAI

from signal_model import Signal

# -----------------------
# Setup
# -----------------------
load_dotenv()

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

NEWSAPI_URL = "https://newsapi.org/v2/everything"

# -----------------------
# Portfolio
# -----------------------
def load_portfolio():
    with open("portfolio.json", "r") as f:
        return json.load(f)["stocks"]


# -----------------------
# Fetch news
# -----------------------
def fetch_news(ticker, company):
    now = datetime.now(timezone.utc)
    from_date = (now - timedelta(days=2)).strftime("%Y-%m-%d")

    params = {
        "q": f'("{ticker}" OR "{company}") AND (earnings OR revenue OR stock OR shares)',
        "from": from_date,
        "sortBy": "publishedAt",
        "language": "en",
        "pageSize": 5,
    }

    headers = {"X-Api-Key": NEWSAPI_KEY}

    res = requests.get(NEWSAPI_URL, params=params, headers=headers)
    res.raise_for_status()

    return res.json()["articles"]


# -----------------------
# Format articles for AI
# -----------------------
def articles_to_text(articles):
    text = ""
    for i, a in enumerate(articles):
        text += f"{i+1}. {a['title']}\n{a.get('description','')}\n\n"
    return text


# -----------------------
# AI → Signal
# -----------------------
def extract_signal(ticker, company, articles_text):
    prompt = f"""
You are a stock analyst.

Extract ONE most important investment signal.

Return ONLY valid JSON.

{{
  "event_type": "Earnings | Guidance | Product Launch | Regulation | Partnership | Layoffs | M&A | Analyst Change | Other",
  "sentiment": "Positive | Neutral | Negative",
  "impact": "Low | Medium | High",
  "confidence": "Low | Medium | High",
  "summary": "Short summary",
  "why_it_matters": "Why it matters"
}}

Ignore weak news.

Ticker: {ticker}
Company: {company}

News:
{articles_text}
"""

    response = client.responses.create(
        model="gpt-5",
        input=prompt
    )

    raw = response.output_text.strip()

    try:
        data = json.loads(raw)
    except Exception:
        print("⚠️ Failed JSON parse. Raw output:")
        print(raw)
        return None

    return Signal(
        ticker=ticker,
        company=company,
        event_type=data["event_type"],
        sentiment=data["sentiment"],
        impact=data["impact"],
        confidence=data["confidence"],
        summary=data["summary"],
        why_it_matters=data["why_it_matters"],
    )


# -----------------------
# Format output
# -----------------------
def format_signal(signal):
    return f"""
🚨 {signal.company} ({signal.ticker})

Event: {signal.event_type}
Sentiment: {signal.sentiment}
Impact: {signal.impact}
Confidence: {signal.confidence}

Summary:
{signal.summary}

Why it matters:
{signal.why_it_matters}
"""


# -----------------------
# Email (optional)
# -----------------------
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def send_email(subject, body):
    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_APP_PASSWORD")
    receiver = os.getenv("EMAIL_RECEIVER")

    if not sender or not password or not receiver:
        print("⚠️ Email config missing, skipping email")
        return

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = receiver
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.send_message(msg)

    print("✅ Email sent")


# -----------------------
# Main flow
# -----------------------
def main():
    portfolio = load_portfolio()

    for stock in portfolio:
        ticker = stock["ticker"]
        company = stock["company"]

        print(f"\n🔍 Processing {ticker}...")

        articles = fetch_news(ticker, company)

        if not articles:
            print("No news found")
            continue

        articles_text = articles_to_text(articles)

        signal = extract_signal(ticker, company, articles_text)

        if not signal:
            continue

        print(format_signal(signal))

        # Only alert on high impact
        if signal.impact == "High":
            send_email(
                subject=f"🚨 High Impact Signal: {ticker}",
                body=format_signal(signal)
            )


if __name__ == "__main__":
    main()