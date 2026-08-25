"""
Company resolution: raw text -> one or more Company rows, deduplicated by
normalize_company_name(). See database/normalization.py for the rule itself
and split_groupement() for the groupement case.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from database.models import Company
from database.normalization import normalize_company_name, split_groupement


def get_or_create_company(session: Session, raw_name: str) -> Company | None:
    """One raw company name -> its Company row, creating it if new.

    None only when `raw_name` normalizes to an empty string (e.g. pure
    punctuation/noise slipping through from an unvalidated field like
    liste_concurrents) — never silently create a blank Company.
    """
    normalized = normalize_company_name(raw_name)
    if not normalized:
        return None

    existing = session.query(Company).filter_by(normalized_name=normalized).one_or_none()
    if existing:
        return existing

    company = Company(normalized_name=normalized, display_name=raw_name.strip())
    session.add(company)
    session.flush()  # obtain company.id for the caller's award_companies link
    return company


def resolve_companies(session: Session, concurrent_retenu: str | None) -> list[Company]:
    """The winner field of an Award -> the Company row(s) behind it.

    A groupement resolves to 2+ Company rows (data_dictionary.md §3.1 — the
    Award record itself is never split, but its winner can be more than one
    legal entity). Everything else resolves to exactly one, or zero when
    concurrent_retenu is empty or pure noise.
    """
    if not concurrent_retenu:
        return []
    if "GROUPEMENT" in concurrent_retenu.upper():
        members = split_groupement(concurrent_retenu)
    else:
        members = [concurrent_retenu]
    companies = [get_or_create_company(session, m) for m in members]
    return [c for c in companies if c is not None]
