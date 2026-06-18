from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ComplaintInput:
    informal_text: str
    primary_department: str
    state: str
    city: str
    area: str = ""
    is_anonymous: bool = False
    name: str = ""
    address: str = ""
    email: str = ""
    phone: str = ""
    media_paths: list[Path] = field(default_factory=list)


@dataclass
class Authority:
    name: str
    role: str
    reason: str
    emails: list[str] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)


@dataclass
class ProcessedComplaint:
    formal_letter: str
    subject: str
    authorities: list[Authority]
    all_emails: list[str]
    original: ComplaintInput
