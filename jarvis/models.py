"""Datenmodelle: was Jarvis aus einem Profil herausliest."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

Category = Literal["pflege", "arzt", "lkw", "andere"]
Recognition = Literal[
    "anerkannt",          # SRK- bzw. MEBEKO-Anerkennung liegt vor
    "positiver_precheck", # positiver Pre-Check / positiver Verfahrensstand
    "laufend",            # Verfahren eingereicht, noch offen
    "nicht_noetig",       # Schweizer Diplom
    "fehlt",              # Ausländisches Diplom ohne Verfahren
    "unbekannt",
]
GermanLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2", "muttersprache", "unbekannt"]


class Assessment(BaseModel):
    """Von Claude extrahierte Fakten. Bewertung passiert danach regelbasiert im Code."""

    full_name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    current_location: Optional[str] = None
    currently_in_switzerland: Optional[bool] = None
    category: Category
    nursing_field: Optional[str] = None      # z.B. "Akutspital", "Psychiatrie", "FaGe"
    physician_specialty: Optional[str] = None
    has_diploma_certificate: Optional[bool] = None
    diploma_country: Optional[str] = None
    german_level: GermanLevel = "unbekannt"
    recognition_status: Recognition = "unbekannt"  # SRK (Pflege) bzw. MEBEKO (Arzt)
    years_experience: Optional[float] = None
    # LKW-Fahrer
    driving_license: Optional[str] = None    # z.B. "CE", "C", "C1E"
    driver_card: Optional[bool] = None       # Fahrerkarte vorhanden
    code95: Optional[bool] = None            # Schlüsselzahl 95 / Modul 95
    adr: Optional[bool] = None               # Gefahrgutschein
    traffic_type: Optional[str] = None       # Fernverkehr, Nahverkehr, Baustelle …
    availability: Optional[str] = None
    summary: str = ""
    evidence: list[str] = []                 # Zitate aus dem Profil als Beleg


class ScoredCandidate(BaseModel):
    assessment: Assessment
    source: str            # Datei / URL / E-Mail, woher der Kandidat stammt
    score: int             # 0-100
    tier: Literal["A", "B", "C", "X"]  # X = erfüllt Pflichtkriterien nicht
    reasons: list[str]
    missing: list[str]     # was noch fehlt / nachzufragen ist
    whatsapp_message: str = ""
    whatsapp_link: Optional[str] = None
    consent_whatsapp: bool = False  # darf automatisch per WhatsApp angeschrieben werden
    consent_call: bool = False      # darf (auch vom KI-Assistenten) angerufen werden
