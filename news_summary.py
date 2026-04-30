import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import requests
from dotenv import load_dotenv
from openai import OpenAI
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


load_dotenv()

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not NEWSAPI_KEY:
    raise ValueError("Missing NEWSAPI_KEY in .env")

if not OPENAI_API_KEY:
    raise ValueError("Missing OPENAI_API_KEY in .env")


client = OpenAI(api_key=OPENAI_API_KEY)

NEWSAPI_URL = "https://newsapi.org/v2/everything"


def send_email_report(subject: str, body: str) -> None:
    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_APP_PASSWORD")
    receiver = os.getenv("EMAIL_RECEIVER")

    # Debug logs (safe, don't print password)
    print("EMAIL_SENDER:", sender)
    print("EMAIL_RECEIVER:", receiver)

    if not sender or not password or not receiver:
        raise ValueError("Missing email config (check env variables)")

    message = MIMEMultipart()
    message["From"] = sender
    message["To"] = receiver
    message["Subject"] = subject

    message.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.send_message(message)
        print("✅ Email sent successfully")
    except Exception as e:
        print("❌ Email failed:", str(e))
        raise

def load_portfolio(path: str = "portfolio.json") -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    stocks = data.get("stocks", [])
    if not stocks or not isinstance(stocks, list):
        raise ValueError("portfolio.json must contain a 'stocks' list")

    for item in stocks:
        if "ticker" not in item or "company" not in item:
            raise ValueError("Each stock must have 'ticker' and 'company'")

    return stocks


def build_query(ticker: str, company: str) -> str:
    # Keeps the query simple but more relevant than ticker-only search
    return f'("{ticker}" OR "{company}") AND (stock OR shares OR earnings OR revenue OR guidance)'


def fetch_news(ticker: str, company: str, days_back: int = 2, page_size: int = 10) -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    from_date = (now - timedelta(days=days_back)).strftime("%Y-%m-%d")
    to_date = now.strftime("%Y-%m-%d")

    params = {
        "q": build_query(ticker, company),
        "from": from_date,
        "to": to_date,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": page_size,
    }

    headers = {
        "X-Api-Key": NEWSAPI_KEY,
    }

    response = requests.get(NEWSAPI_URL, params=params, headers=headers, timeout=30)
    response.raise_for_status()
    data = response.json()

    if data.get("status") != "ok":
        raise RuntimeError(f"NewsAPI error: {data}")

    return data.get("articles", [])


def dedupe_articles(articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen_titles = set()
    result = []

    for article in articles:
        title = (article.get("title") or "").strip().lower()
        if not title:
            continue
        if title in seen_titles:
            continue
        seen_titles.add(title)
        result.append(article)

    return result


def trim_articles(articles: List[Dict[str, Any]], limit: int = 6) -> List[Dict[str, Any]]:
    return articles[:limit]


def articles_to_prompt_text(ticker: str, company: str, articles: List[Dict[str, Any]]) -> str:
    if not articles:
        return f"No recent relevant news found for {company} ({ticker})."

    lines = [f"Company: {company} ({ticker})", "Articles:"]
    for idx, article in enumerate(articles, start=1):
        source = (article.get("source") or {}).get("name", "")
        title = article.get("title", "")
        description = article.get("description", "")
        published_at = article.get("publishedAt", "")
        url = article.get("url", "")

        lines.append(
            f"{idx}. Title: {title}\n"
            f"   Source: {source}\n"
            f"   Published: {published_at}\n"
            f"   Description: {description}\n"
            f"   URL: {url}"
        )

    return "\n".join(lines)


def summarize_news(ticker: str, company: str, articles: List[Dict[str, Any]]) -> str:
    context = articles_to_prompt_text(ticker, company, articles)

    prompt = f"""
You are a stock news analyst.

Based only on the articles below, produce:

1. A 2-3 sentence summary
2. 3 bullet points of the most important developments
3. Sentiment: Positive, Neutral, or Negative
4. A one-line explanation of why this matters to shareholders

Be concise. Do not invent facts. If the evidence is weak, say so.

{context}
""".strip()

    response = client.responses.create(
        model="gpt-5",
        input=prompt,
    )

    return response.output_text.strip()


def build_report(stocks: List[Dict[str, str]]) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    output = [f"# Daily Stock News Report - {today}", ""]

    for stock in stocks:
        ticker = stock["ticker"]
        company = stock["company"]

        output.append(f"## {company} ({ticker})")

        try:
            raw_articles = fetch_news(ticker, company)
            unique_articles = dedupe_articles(raw_articles)
            selected_articles = trim_articles(unique_articles)

            if not selected_articles:
                output.append("No relevant recent articles found.")
                output.append("")
                continue

            summary = summarize_news(ticker, company, selected_articles)
            output.append(summary)
            output.append("")

        except Exception as e:
            output.append(f"Error: {e}")
            output.append("")

    return "\n".join(output)


def save_report(report_text: str) -> Path:
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)

    filename = datetime.now().strftime("%Y-%m-%d") + ".md"
    output_path = reports_dir / filename
    output_path.write_text(report_text, encoding="utf-8")

    return output_path


def main() -> None:
    stocks = load_portfolio()
    report = build_report(stocks)
    path = save_report(report)

    subject = f"Daily Stock News Report - {datetime.now().strftime('%Y-%m-%d')}"
    send_email_report(subject, report)

    print(f"Saved report to: {path}")
    print("Email sent successfully.")


if __name__ == "__main__":
    main()