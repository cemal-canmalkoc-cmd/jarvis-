"""Claude-Anbindung: Profile auslesen und öffentliche Stellengesuche finden."""
from __future__ import annotations

import json
import re

import anthropic

from .config import EFFORT, LKW_REQUIREMENTS_TEXT, MODEL, REQUIREMENTS_TEXT, WEB_SEARCHES_PER_FOCUS
from .models import Assessment

_client: anthropic.Anthropic | None = None

FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Modelle mit serverseitigem Ersatzmodell bei Ablehnung (Haiku hat keins)
FALLBACK_MODELS = ("claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-2", "claude-fable-5-1")


def fallback_kwargs(model: str) -> dict:
    return {"betas": [FALLBACK_BETA], "fallbacks": "default"} if model in FALLBACK_MODELS else {}


def create(**kw):
    """Ein Claude-Aufruf; nutzt automatisch das Ersatzmodell, wo verfügbar."""
    from . import budget
    extra = fallback_kwargs(kw["model"])
    if extra:
        resp = client().beta.messages.create(**kw, **extra)
    else:
        resp = client().messages.create(**kw)
    budget.record(kw["model"], resp)
    return resp


def web_search_tool(model: str, max_uses: int) -> dict:
    """Websuche mit dynamischer Filterung, wo das Modell sie kann; sonst die Basisversion."""
    advanced = any(model.startswith(p) for p in ("claude-opus", "claude-sonnet", "claude-fable", "claude-mythos"))
    return {"type": "web_search_20260209" if advanced else "web_search_20250305",
            "name": "web_search", "max_uses": max_uses}


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _nullable(t: str, enum: list[str] | None = None) -> dict:
    if enum:
        return {"anyOf": [{"type": t, "enum": enum}, {"type": "null"}]}
    return {"type": [t, "null"]}


ASSESSMENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "full_name": {"type": "string"},
        "phone": _nullable("string"),
        "email": _nullable("string"),
        "current_location": _nullable("string"),
        "currently_in_switzerland": _nullable("boolean"),
        "category": {"type": "string", "enum": ["pflege", "arzt", "lkw", "andere"]},
        "driving_license": _nullable("string"),
        "driver_card": _nullable("boolean"),
        "code95": _nullable("boolean"),
        "adr": _nullable("boolean"),
        "traffic_type": _nullable("string"),
        "nursing_field": _nullable("string"),
        "physician_specialty": _nullable("string"),
        "has_diploma_certificate": _nullable("boolean"),
        "diploma_country": _nullable("string"),
        "german_level": {
            "type": "string",
            "enum": ["A1", "A2", "B1", "B2", "C1", "C2", "muttersprache", "unbekannt"],
        },
        "recognition_status": {
            "type": "string",
            "enum": ["anerkannt", "positiver_precheck", "laufend", "nicht_noetig", "fehlt", "unbekannt"],
        },
        "years_experience": _nullable("number"),
        "availability": _nullable("string"),
        "summary": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "full_name", "phone", "email", "current_location", "currently_in_switzerland",
        "category", "nursing_field", "physician_specialty", "has_diploma_certificate",
        "diploma_country", "german_level", "recognition_status", "years_experience",
        "availability", "summary", "evidence",
        "driving_license", "driver_card", "code95", "adr", "traffic_type",
    ],
}

EXTRACT_SYSTEM = f"""Du bist Jarvis, ein erfahrener Personalvermittler (Gesundheitsberufe Schweiz und
LKW-Fahrer Deutschland). Du liest Lebensläufe, Bewerbungen und Profile und extrahierst nur Fakten,
die im Text belegt sind.

{REQUIREMENTS_TEXT}

{LKW_REQUIREMENTS_TEXT}

Regeln für die Extraktion:
- Erfinde nichts. Wenn etwas nicht im Text steht, setze null bzw. "unbekannt".
- recognition_status: Pflege = SRK, Ärzte = MEBEKO.
  "nicht_noetig" nur bei Schweizer Diplom. "positiver_precheck" bei positivem SRK-Pre-Check
  oder positivem Zwischenstand bei der MEBEKO. "fehlt" bei ausländischem Diplom ohne Verfahren.
- german_level: höchstes nachgewiesenes oder klar angegebenes Niveau; Muttersprache Deutsch = "muttersprache".
- FaGe zählt als Pflege (category "pflege", nursing_field "FaGe").
- LKW-/Berufskraftfahrer → category "lkw". driving_license: höchste LKW-Klasse ("CE", "C", "C1E", "C1").
  "Fahrerkarte" → driver_card true. "Modul 95", "Schlüsselzahl 95", "Code 95", "BKrFQG", "Weiterbildung
  Berufskraftfahrer" → code95 true. "ADR"/"Gefahrgut" → adr true. traffic_type: Fernverkehr/Nahverkehr/
  Baustelle/Kipper/Tank/Kühl … has_diploma_certificate und recognition_status sind bei LKW nicht relevant
  (null bzw. "unbekannt"). currently_in_switzerland bei Fahrern in Deutschland: false.
- Abschluss-Begriffe wie "examiniert", "gelernt", "staatlich anerkannt", "Diplom", "HF", "FH", "B.Sc. Nursing",
  "Gesundheits- und Krankenpfleger/in", "Pflegefachfrau/-mann" bedeuten has_diploma_certificate = true.
  "Pflegehelfer/in", "Pflegeassistenz", "Betreuungskraft", "Auszubildende/r" bedeuten false.
- Altenpfleger/in → category "pflege", nursing_field "Geriatrie / Langzeitpflege".
- Deutsches Diplom ohne Hinweis auf ein Anerkennungsverfahren → recognition_status "fehlt".
- currently_in_switzerland: true nur, wenn Wohnort/aktuelle Stelle klar in der Schweiz liegt.
- evidence: 2-5 kurze wörtliche Zitate, die die wichtigsten Angaben belegen.
- summary: 1-2 Sätze auf Deutsch für den Recruiter."""


def _text_of(response) -> str:
    return "".join(b.text for b in response.content if b.type == "text")


def extract(profile_text: str) -> Assessment:
    """Liest ein Kandidatenprofil aus und gibt strukturierte Fakten zurück."""
    response = create(
        model=MODEL,
        max_tokens=16000,
        system=EXTRACT_SYSTEM,
        output_config={
            "effort": EFFORT,
            "format": {"type": "json_schema", "schema": ASSESSMENT_SCHEMA},
        },
        messages=[{"role": "user", "content": f"Kandidatenprofil:\n\n{profile_text}"}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Claude hat abgelehnt: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("Antwort abgeschnitten (max_tokens)")
    return Assessment.model_validate_json(_text_of(response))


# ---------------------------------------------------------------------------
# Sourcing im Web: nur öffentliche Stellengesuche / aktiv Jobsuchende
# ---------------------------------------------------------------------------
SOURCING_SYSTEM = f"""Du bist Jarvis, Sourcing-Spezialist für Gesundheitspersonal in der Schweiz.

{REQUIREMENTS_TEXT}

Deine Aufgabe: Finde im öffentlichen Web Personen, die SELBST aktiv nach einer Stelle suchen
(z.B. öffentliche Stellengesuche, Inserate "suche Stelle als Pflegefachfrau", öffentlich
gestellte Kandidatenprofile auf Jobportalen, die zur Kontaktaufnahme freigegeben sind).

So gehst du vor (bewährt – genau so suchen):
1. Führe diese Suchen aus (Beruf jeweils passend zum Fokus einsetzen, z.B. Krankenschwester,
   Pflegefachkraft, Altenpflegerin, Gesundheits- und Krankenpflegerin, Pflegefachfrau HF, Arzt):
   - "kleinanzeigen.de Stellengesuche <Beruf> sucht Stelle"
   - "quoka.de Stellengesuche <Beruf> sucht Stelle"
   - "anibis.ch Gesundheitswesen Stellengesuch <Beruf>"
   - "tutti.ch Stellengesuch <Beruf>"
   - "medi-jobs.de Stellengesuche <Bereich>"
   - "<Beruf> sucht neue Stelle Schweiz"
2. Diese Treffer sind oft SAMMELSEITEN mit mehreren Gesuchen. Lies den Inhalt und nimm JEDE einzelne
   Person als eigenen Eintrag auf (Beruf, Ort, Erfahrung, Wunsch, Kontaktweg).
3. Stellenangebote von Arbeitgebern, 24h-Betreuungs-Vermittler und Gesuche, die erkennbar älter als
   12 Monate sind, weglassen. Auszubildende/Hilfskräfte nur aufnehmen, wenn sonst nichts da ist.
4. Kontakt über das Portal (Nachricht an Inserent) reicht: dann ist die Inserats- oder Sammelseiten-URL
   der Kontaktweg. E-Mail-Adressen nur übernehmen, wenn sie öffentlich in der Anzeige stehen.
5. Auch Personen aus Deutschland/Österreich passen (Umzug in die Schweiz ist unser Angebot).

Strikte Regeln:
- Nur Personen, die öffentlich und freiwillig ihre Jobsuche inklusive Kontaktmöglichkeit gepostet haben.
- Keine Profile aus Login-geschützten Netzwerken, keine erratenen Kontaktdaten, keine Telefonnummern
  aus anderen Quellen zusammenführen.
- Bevorzuge Personen, die aktuell in der Schweiz sind.
- Gib für jede Person die exakte Quell-URL an – wenn möglich die EINZELNE Anzeige
  (z.B. kleinanzeigen.de/s-anzeige/…), nicht die Übersichtsseite. Öffne dazu die einzelne Anzeige.
- Übernimm Anzeigentitel wörtlich und eine Telefon-/WhatsApp-Nummer NUR, wenn sie öffentlich in der Anzeige steht.

Antworte am Ende ausschliesslich mit einem JSON-Codeblock. profile_text muss ALLE Angaben aus der Anzeige
enthalten: Berufsbezeichnung/Abschluss wörtlich, Ort mit PLZ und Land, Erfahrung, Alter/Jahrgang, gewünschtes
Pensum, Verfügbarkeit, Datum des Gesuchs, Anzeigentitel, Kontaktweg (Portal/E-Mail/Telefon):
```json
[{{"source_url": "...", "profile_text": "..."}}]
```
Leeres Array, wenn nichts Passendes gefunden wurde."""


LKW_SOURCING_SYSTEM = f"""Du bist Jarvis, Sourcing-Spezialist für LKW-Fahrer in Deutschland.

{LKW_REQUIREMENTS_TEXT}

Finde im öffentlichen Web Personen, die SELBST eine Stelle als LKW-Fahrer/Berufskraftfahrer suchen.
So gehst du vor (genau so suchen, Begriff passend zum Fokus):
- "kleinanzeigen.de Stellengesuche LKW Fahrer CE sucht Arbeit"
- "kleinanzeigen.de Berufskraftfahrer sucht Stelle"
- "quoka.de Stellengesuche Kraftfahrer"
- "markt.de Stellengesuch LKW Fahrer"
- "Kraftfahrer CE sucht neue Herausforderung Fernverkehr"
- "Berufskraftfahrer sucht Job Nahverkehr <Region>"
Sammelseiten in einzelne Personen zerlegen. Stellenangebote von Speditionen/Personaldienstleistern und
Gesuche älter als 12 Monate weglassen. Kontakt über das Portal reicht (Inserats-URL als Kontaktweg).
Keine Login-Profile, keine erratenen Kontaktdaten.
Gib wenn möglich die URL der EINZELNEN Anzeige an (kleinanzeigen.de/s-anzeige/…), nicht die Übersichtsseite,
dazu den Anzeigentitel wörtlich. Telefon-/WhatsApp-Nummer nur, wenn sie öffentlich in der Anzeige steht.

Antworte am Ende ausschliesslich mit einem JSON-Codeblock. profile_text muss ALLE Angaben enthalten:
Führerscheinklasse, Fahrerkarte, Modul 95, ADR, Erfahrung, Verkehrsart, Ort mit PLZ, Datum, Anzeigentitel, Kontaktweg:
```json
[{{"source_url": "...", "profile_text": "..."}}]
```
Leeres Array, wenn nichts Passendes gefunden wurde."""


def is_lkw_focus(focus: str) -> bool:
    return focus.strip().lower().startswith("lkw:")


def find_public_leads(focus: str, max_searches: int | None = None) -> list[dict]:
    """Sucht öffentliche Stellengesuche zu einem Fokus (z.B. 'Pflegefachfrau Psychiatrie Zürich')."""
    messages: list[dict] = [{
        "role": "user",
        "content": (f"Suche aktuell öffentliche Stellengesuche für: {focus[4:].strip()}. Region: Deutschland."
                    if is_lkw_focus(focus) else
                    f"Suche aktuell öffentliche Stellengesuche für: {focus}. "
                    "Region: Schweiz (Deutschschweiz bevorzugt)."),
    }]
    system_prompt = LKW_SOURCING_SYSTEM if is_lkw_focus(focus) else SOURCING_SYSTEM
    tools = [web_search_tool(MODEL, max_searches or WEB_SEARCHES_PER_FOCUS)]

    for _ in range(5):  # pause_turn kann mehrmals vorkommen
        response = create(
            model=MODEL,
            max_tokens=16000,
            system=system_prompt,
            output_config={"effort": EFFORT},
            tools=tools,
            messages=messages,
        )
        if response.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": response.content})
            continue
        break

    if response.stop_reason == "refusal":
        return []
    text = _text_of(response)
    match = re.search(r"```json\s*(.*?)```", text, re.DOTALL)
    raw = match.group(1) if match else text
    try:
        leads = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [l for l in leads if isinstance(l, dict) and l.get("profile_text")]
