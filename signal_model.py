from dataclasses import dataclass


@dataclass
class Signal:
    ticker: str
    company: str
    event_type: str
    sentiment: str
    impact: str
    confidence: str
    summary: str
    why_it_matters: str