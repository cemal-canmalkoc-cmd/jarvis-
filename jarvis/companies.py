"""Arbeitgeber finden: Spitäler, Kliniken, Heime mit offenen Stellen in euren Bereichen."""
from __future__ import annotations

import json
import re

from . import brain, store
from .config import EFFORT, MODEL, REQUIREMENTS_TEXT

SYSTEM = f"""Du bist Jarvis, Business-Development für eine Personalvermittlung im Schweizer Gesundheitswesen.

{REQUIREMENTS_TEXT}

Aufgabe: Finde Schweizer Arbeitgeber (Spitäler, Kliniken, Psychiatrien, Alters- und Pflegeheime,
Reha-Kliniken, Praxen), die AKTUELL Stellen in den obigen Bereichen ausgeschrieben haben.

Für jeden Arbeitgeber:
- name, city (Ort), website
- phone: die öffentlich angegebene Telefonnummer der Personalabteilung/HR oder der Zentrale,
  so wie sie auf der offiziellen Website steht. Niemals raten. Ohne Nummer: null.
- needs: welche Stellen konkret offen sind
- source_url: URL der Stellenanzeige oder Karriereseite
- no_cold_calls: true, wenn die Firma/Anzeige ausdrücklich keine Vermittler / keine Personaldienstleister wünscht

Antworte am Ende ausschliesslich mit einem JSON-Codeblock:
```json
[{{"name": "...", "city": "...", "website": "...", "phone": "...", "needs": "...", "source_url": "...", "no_cold_calls": false}}]
```"""


def find(focus: str, region: str = "Deutschschweiz", max_searches: int = 10) -> dict:
    messages: list[dict] = [{
        "role": "user",
        "content": f"Finde Arbeitgeber mit offenen Stellen für: {focus}. Region: {region}.",
    }]
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches}]
    response = None
    for _ in range(5):
        response = brain.client().beta.messages.create(
            model=MODEL, max_tokens=32000, betas=[brain.FALLBACK_BETA], fallbacks="default",
            system=SYSTEM, output_config={"effort": EFFORT}, tools=tools, messages=messages,
        )
        if response.stop_reason != "pause_turn":
            break
        messages.append({"role": "assistant", "content": response.content})

    if response is None or response.stop_reason == "refusal":
        return {"gefunden": 0, "neu": 0}
    text = "".join(b.text for b in response.content if b.type == "text")
    m = re.search(r"```json\s*(.*?)```", text, re.DOTALL)
    try:
        items = json.loads(m.group(1) if m else text)
    except json.JSONDecodeError:
        return {"gefunden": 0, "neu": 0}

    conn = store.connect()
    new = 0
    for it in items:
        if not isinstance(it, dict) or not it.get("name"):
            continue
        added = store.add_company(conn, **it)
        if added:
            new += 1
            if it.get("no_cold_calls"):
                row = conn.execute("SELECT id FROM companies WHERE name=? AND city IS ?",
                                   (it["name"], it.get("city"))).fetchone()
                if row:
                    store.set_company_status(conn, row["id"], "nicht_anrufen",
                                             "Anzeige: keine Personaldienstleister")
    return {"gefunden": len(items), "neu": new}
