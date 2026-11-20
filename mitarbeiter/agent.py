"""Der Arbeitstag des digitalen Mitarbeiters. Wird stündlich von GitHub Actions gestartet.

Ablauf pro Lauf:
 1. Postfach abarbeiten (Bewerbungen, Zustimmungen, Arbeitgeber-Anfragen, Antworten, Abmeldungen)
 2. Erinnerungen an Kandidaten ohne Rückmeldung (einmalig nach 3 Tagen)
 3. Matching: zugestimmte Kandidaten -> Partner-Arbeitgeber (anonymes Profil, automatisch)
 4. Einmal täglich: Bericht an den Inhaber (neue Leute, Treffer, Anrufliste, offene Fragen)

Rechtliche Leitplanken (fest eingebaut):
 - Profile gehen nur an Arbeitgeber, die die Konditionen per E-Mail bestätigt haben (Partner).
 - Persönliche Daten nur nach ausdrücklicher Zustimmung des Kandidaten (JA), und erst beim Kennenlernen.
 - Keine Kaltakquise-Mails: Einrichtungen ohne Partnerstatus landen nur auf der Anrufliste für den Inhaber.
 - ABMELDEN/STOP löscht die Person.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import ki, vorlagen
from .postfach import Gesendet, Postfach, TestPostfach
from .speicher import Speicher

ROOT = Path(__file__).resolve().parent.parent
MAX_MAILS_PRO_LAUF = 40

STICHWORTE = {
    "pflege": ["pflege", "kranken", "gesundheits", "examiniert", "pflegefach"],
    "alten": ["alten", "senioren", "geriatr"],
    "intensiv": ["intensiv", "anästhesie", "anaesthesie"],
    "op": ["op-", "op ", "operations", "ota"],
    "mfa": ["mfa", "medizinische fachangestellte", "arzthelfer", "praxis"],
    "hebamme": ["hebamme", "entbindung"],
    "therapie": ["physio", "ergo", "logopäd"],
}


def jetzt() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def kategorien(text: str) -> set[str]:
    t = text.lower()
    return {k for k, woerter in STICHWORTE.items() if any(w in t for w in woerter)}


def passt(kand: dict, ag: dict) -> bool:
    k_kat = kategorien(kand.get("qualifikation", ""))
    a_kat = kategorien(" ".join(ag.get("positionen", [])))
    if a_kat and k_kat and not (k_kat & a_kat):
        return False
    if not k_kat and a_kat:
        return False
    k_orte = {o.lower() for o in kand.get("orte", [])}
    a_orte = {o.lower() for o in ag.get("orte", [])}
    if not k_orte or not a_orte or any(w in k_orte for w in ("egal", "flexibel", "deutschlandweit")):
        return True
    return any(k in a or a in k for k in k_orte for a in a_orte)


class Mitarbeiter:
    def __init__(self, postfach, speicher: Speicher, inhaber: str, jobs: list[dict] | None = None) -> None:
        self.pf = postfach
        self.sp = speicher
        self.inhaber = inhaber.lower()
        self.jobs = jobs or []
        self.db = speicher.laden()
        self.heute: list[str] = []          # Ereignisse für den Tagesbericht
        self.eskalationen: list[str] = []

    # ------------------------------------------------------------------ Hilfen
    def log(self, text: str) -> None:
        print(text)
        self.heute.append(text)
        self.db["protokoll"].append(f"{jetzt()} {text}")

    def senden(self, an: str, vorlage: tuple[str, str], cc: list[str] | None = None) -> None:
        betreff, text = vorlage
        self.pf.senden(Gesendet(an=an, betreff=betreff, text=text, cc=cc or []))

    def kontext(self, absender: str) -> str:
        if absender in self.db["kandidaten"]:
            k = self.db["kandidaten"][absender]
            return f"kandidat, status={k['status']}, qualifikation={k.get('qualifikation')}"
        if absender in self.db["arbeitgeber"]:
            a = self.db["arbeitgeber"][absender]
            return f"arbeitgeber, status={a['status']}, einrichtung={a.get('einrichtung')}"
        return "unbekannt"

    # ------------------------------------------------------------------ 1. Postfach
    def postfach_abarbeiten(self) -> None:
        for mail in self.pf.neue_mails(MAX_MAILS_PRO_LAUF):
            if mail.message_id in self.db["verarbeitet"]:
                continue
            self.db["verarbeitet"].append(mail.message_id)
            if not mail.absender or mail.absender == self.inhaber:
                continue
            a = ki.analysieren(mail.betreff, mail.text, self.kontext(mail.absender))
            try:
                self.bearbeiten(mail.absender, mail.betreff, mail.text, a)
            except Exception as e:  # noqa: BLE001
                self.eskalationen.append(f"Fehler bei Mail von {mail.absender} ({mail.betreff}): {e}")

    def bearbeiten(self, von: str, betreff: str, text: str, a: ki.Analyse) -> None:
        if a.absage:
            self.db["kandidaten"].pop(von, None)
            self.db["arbeitgeber"].pop(von, None)
            self.senden(von, vorlagen.abgemeldet())
            self.log(f"Abmeldung + Löschung: {von}")
            return

        if a.art == "kandidat_bewerbung" and von not in self.db["kandidaten"]:
            self.db["kandidaten"][von] = {
                "email": von, "name": a.name, "telefon": a.telefon, "qualifikation": a.qualifikation,
                "erfahrung_jahre": a.erfahrung_jahre, "orte": a.orte, "verfuegbar_ab": a.verfuegbar_ab,
                "gehaltswunsch": a.gehaltswunsch, "status": "wartet_auf_zustimmung", "seit": jetzt(),
                "erinnert": False, "id": f"K{len(self.db['kandidaten']) + 1001}",
            }
            if a.zustimmung_weitergabe:
                self.db["kandidaten"][von]["status"] = "aktiv"
                self.senden(von, vorlagen.kandidat_aktiv(a.name))
            else:
                self.senden(von, vorlagen.kandidat_eingang(a.name))
            self.log(f"Neue Bewerbung: {a.qualifikation or '?'} ({', '.join(a.orte) or 'Ort offen'})")
            return

        if von in self.db["kandidaten"]:
            k = self.db["kandidaten"][von]
            for feld in ("telefon", "qualifikation", "verfuegbar_ab", "gehaltswunsch"):
                if getattr(a, feld):
                    k[feld] = getattr(a, feld)
            if a.zustimmung_weitergabe and k["status"] != "aktiv":
                k["status"] = "aktiv"
                self.senden(von, vorlagen.kandidat_aktiv(k.get("name", "")))
                self.log(f"Zustimmung erhalten: {k['id']} {k.get('qualifikation')}")
            elif a.braucht_menschen:
                self.eskalationen.append(f"Kandidat {k['id']} ({von}) fragt: {a.zusammenfassung} | Betreff: {betreff}")
            return

        if a.art == "arbeitgeber_anfrage" and von not in self.db["arbeitgeber"]:
            self.db["arbeitgeber"][von] = {
                "email": von, "name": a.name, "einrichtung": a.einrichtung, "telefon": a.telefon,
                "positionen": a.positionen, "orte": a.orte, "status": "konditionen_gesendet", "seit": jetzt(),
            }
            if a.konditionen_akzeptiert:
                self.db["arbeitgeber"][von]["status"] = "partner"
            else:
                self.senden(von, vorlagen.arbeitgeber_konditionen(a.name, a.einrichtung))
            self.log(f"Arbeitgeber-Anfrage: {a.einrichtung or von} sucht {', '.join(a.positionen) or '?'}")
            return

        if von in self.db["arbeitgeber"]:
            ag = self.db["arbeitgeber"][von]
            if a.positionen:
                ag["positionen"] = sorted(set(ag.get("positionen", [])) | set(a.positionen))
            if a.orte:
                ag["orte"] = sorted(set(ag.get("orte", [])) | set(a.orte))
            if a.konditionen_akzeptiert and ag["status"] != "partner":
                ag["status"] = "partner"
                ag["partner_seit"] = jetzt()
                self.log(f"NEUER PARTNER (Konditionen bestätigt): {ag.get('einrichtung') or von}")
            if a.interesse_an_kandidat:
                self.kennenlernen(von, ag, f"{betreff}\n{text}")
            if a.braucht_menschen and not (a.konditionen_akzeptiert or a.interesse_an_kandidat):
                self.eskalationen.append(f"Arbeitgeber {ag.get('einrichtung') or von}: {a.zusammenfassung} | Betreff: {betreff}")
            return

        self.eskalationen.append(f"Unklare Mail von {von}: {a.zusammenfassung or betreff}")

    def kennenlernen(self, ag_mail: str, ag: dict, text: str) -> None:
        if ag["status"] != "partner":
            self.eskalationen.append(f"{ag.get('einrichtung') or ag_mail} will Kandidaten, hat aber Konditionen nicht bestätigt!")
            return
        ids = set(re.findall(r"K\d{4}", text))
        vorgestellt = [v for v in self.db["vorgestellt"] if v["arbeitgeber"] == ag_mail]
        if not ids and len(vorgestellt) == 1:
            ids = {vorgestellt[0]["kandidat_id"]}
        for kid in ids:
            kand = next((k for k in self.db["kandidaten"].values() if k["id"] == kid and k["status"] == "aktiv"), None)
            if not kand:
                self.eskalationen.append(f"{ag.get('einrichtung')} will {kid}, Kandidat nicht (mehr) verfügbar.")
                continue
            self.senden(kand["email"], vorlagen.vorstellung(ag.get("einrichtung", ""), kand), cc=[ag_mail])
            for v in self.db["vorgestellt"]:
                if v["arbeitgeber"] == ag_mail and v["kandidat_id"] == kid:
                    v["status"] = "kennenlernen"
            self.log(f"$$ KENNENLERNEN vermittelt: {kid} -> {ag.get('einrichtung')} (Einstellung nachverfolgen, Rechnung!)")
        if not ids:
            self.eskalationen.append(f"{ag.get('einrichtung')} hat Interesse, aber unklar an wem – bitte nachfragen.")

    # ------------------------------------------------------------------ 2. Erinnerungen
    def erinnern(self) -> None:
        grenze = datetime.now(timezone.utc) - timedelta(days=3)
        for k in self.db["kandidaten"].values():
            if k["status"] == "wartet_auf_zustimmung" and not k["erinnert"] and datetime.fromisoformat(k["seit"]) < grenze:
                self.senden(k["email"], vorlagen.kandidat_erinnerung(k.get("name", "")))
                k["erinnert"] = True

    # ------------------------------------------------------------------ 3. Matching
    def matching(self) -> None:
        schon = {(v["kandidat_id"], v["arbeitgeber"]) for v in self.db["vorgestellt"]}
        partner = {m: a for m, a in self.db["arbeitgeber"].items() if a["status"] == "partner"}
        for k in self.db["kandidaten"].values():
            if k["status"] != "aktiv":
                continue
            for m, ag in partner.items():
                if (k["id"], m) in schon or not passt(k, ag):
                    continue
                self.senden(m, vorlagen.arbeitgeber_profil(ag.get("einrichtung", ""), k["id"], k))
                self.db["vorgestellt"].append({"kandidat_id": k["id"], "arbeitgeber": m, "datum": jetzt(), "status": "profil_gesendet"})
                self.log(f"Profil {k['id']} an Partner {ag.get('einrichtung') or m} gesendet")

    def anrufliste(self) -> list[str]:
        """Stellen ohne Partner, die zu aktiven Kandidaten passen -> der Inhaber ruft dort an."""
        zeilen = []
        for k in self.db["kandidaten"].values():
            if k["status"] != "aktiv":
                continue
            treffer = [j for j in self.jobs if passt(k, {"positionen": [j.get("beruf", ""), j.get("titel", "")],
                                                         "orte": [j.get("ort", ""), j.get("stadt", "")]})]
            for j in treffer[:3]:
                zeilen.append(f"{k['id']} ({k.get('qualifikation')}) passt zu: {j['arbeitgeber']} – {j['titel']} – {j['ort']} "
                              f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{j['refnr']}")
        return zeilen[:25]

    # ------------------------------------------------------------------ 4. Bericht
    def bericht(self, erzwingen: bool = False) -> None:
        heute = date.today().isoformat()
        offen = self.db.setdefault("offene_punkte", [])
        offen.extend(self.eskalationen)
        self.db.setdefault("tagesereignisse", []).extend(self.heute)
        stunde = int(os.environ.get("BERICHT_STUNDE_UTC", "6"))
        if not erzwingen and (self.db["letzter_bericht"] == heute or datetime.now(timezone.utc).hour < stunde):
            return
        kand = self.db["kandidaten"].values()
        partner = [a for a in self.db["arbeitgeber"].values() if a["status"] == "partner"]
        kennen = [v for v in self.db["vorgestellt"] if v.get("status") == "kennenlernen"]
        teile = [
            f"Tagesbericht {heute}",
            f"Kandidaten aktiv: {sum(k['status'] == 'aktiv' for k in kand)} | warten auf Zustimmung: "
            f"{sum(k['status'] == 'wartet_auf_zustimmung' for k in kand)}",
            f"Partner-Arbeitgeber: {len(partner)} | Profile gesendet: {len(self.db['vorgestellt'])} | Kennenlernen: {len(kennen)}",
            "\n== Was ich erledigt habe ==", *(self.db["tagesereignisse"] or ["(nichts Neues)"]),
            "\n== Bitte DU erledigen (Fragen/Verhandlungen) ==", *(offen or ["(nichts)"]),
            "\n== Anrufliste: Arbeitgeber anrufen, Konditionen anbieten, dann Mail an uns weiterleiten lassen ==",
            *(self.anrufliste() or ["(keine Treffer)"]),
            "\n== Nach Kennenlernen: Einstellung erfragen und Rechnung stellen ==",
            *([f"{v['kandidat_id']} bei {v['arbeitgeber']} seit {v['datum'][:10]}" for v in kennen] or ["(keine)"]),
        ]
        if self.inhaber:
            self.pf.senden(Gesendet(an=self.inhaber, betreff=f"[Mitarbeiter] Tagesbericht {heute}", text="\n".join(teile)))
        print("\n".join(teile))
        self.db["letzter_bericht"] = heute
        self.db["offene_punkte"] = []
        self.db["tagesereignisse"] = []

    # ------------------------------------------------------------------ Arbeitstag
    def arbeitstag(self, bericht_erzwingen: bool = False) -> None:
        self.postfach_abarbeiten()
        self.erinnern()
        self.matching()
        self.bericht(bericht_erzwingen)
        self.sp.speichern(self.db)


def main() -> None:
    jobs_datei = ROOT / "_site" / "jobs.json"
    jobs = json.loads(jobs_datei.read_text(encoding="utf-8")) if jobs_datei.exists() else []
    trocken = "--trocken" in sys.argv or not os.environ.get("MAIL_USER")
    pf = TestPostfach() if trocken else Postfach()
    if trocken:
        print("Trockenlauf: keine Mail-Zugangsdaten (MAIL_USER) – es wird nichts gesendet.")
    sp = Speicher(ROOT / "data" / "crm.enc", os.environ.get("CRM_KEY"))
    if not os.environ.get("CRM_KEY"):
        print("WARNUNG: CRM_KEY fehlt – Daten würden unverschlüsselt gespeichert. Abbruch.")
        if not trocken:
            sys.exit(1)
        sp = Speicher(ROOT / "data" / "crm-test.json", None)
    Mitarbeiter(pf, sp, os.environ.get("INHABER_EMAIL", ""), jobs).arbeitstag("--bericht" in sys.argv)


if __name__ == "__main__":
    main()
