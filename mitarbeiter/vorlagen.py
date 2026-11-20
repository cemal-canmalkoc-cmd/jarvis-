"""Alle E-Mail-Texte an einer Stelle – hier anpassen (Firmenname, Honorar, Signatur)."""
import os

FIRMA = os.environ.get("ABSENDER_NAME") or "PflegeJobs Direkt"
HONORAR = os.environ.get("HONORAR_TEXT") or ("18 % des vereinbarten Bruttojahresgehalts (zzgl. MwSt.), fällig bei Arbeitsantritt, "
                                         "mit 3 Monaten kostenloser Nachbesetzung bei Kündigung in der Probezeit")
SIGNATUR = f"\n\nViele Grüße\nIhr Team von {FIRMA}\n(Antworten Sie mit ABMELDEN, wenn Sie keine weiteren Nachrichten wünschen.)"


def kandidat_eingang(name: str) -> tuple[str, str]:
    return ("Ihre Bewerbung – bitte kurz bestätigen", f"""Hallo {name or ''},

vielen Dank für Ihr Interesse! Unsere Vermittlung ist für Sie komplett kostenlos – das Honorar zahlt der Arbeitgeber.

Damit wir Sie Kliniken, Heimen und Praxen vorstellen dürfen, brauchen wir Ihre Zustimmung:
Antworten Sie bitte einfach mit JA.

Dann senden wir Ihr Profil an passende Arbeitgeber und melden uns, sobald jemand Sie kennenlernen möchte.
Ihre Daten geben wir nie ohne diese Zustimmung weiter und löschen sie auf Wunsch jederzeit.{SIGNATUR}""")


def kandidat_erinnerung(name: str) -> tuple[str, str]:
    return ("Kurze Erinnerung: Dürfen wir Sie vorstellen?", f"""Hallo {name or ''},

wir haben passende Stellen für Sie. Damit wir Sie vorstellen dürfen, antworten Sie bitte mit JA.{SIGNATUR}""")


def kandidat_aktiv(name: str) -> tuple[str, str]:
    return ("Danke – wir legen los", f"""Hallo {name or ''},

danke für Ihre Zustimmung. Wir stellen Ihr Profil jetzt passenden Arbeitgebern vor und melden uns, sobald es Interesse gibt.{SIGNATUR}""")


def arbeitgeber_konditionen(name: str, einrichtung: str) -> tuple[str, str]:
    return (f"Personalvermittlung für {einrichtung or 'Ihre Einrichtung'} – Konditionen", f"""Guten Tag {name or ''},

vielen Dank für Ihre Anfrage. So arbeiten wir:
- Wir senden Ihnen anonymisierte Profile vorqualifizierter Fachkräfte, die zu Ihren Stellen passen.
- Sie zahlen nur bei erfolgreicher Einstellung: {HONORAR}.
- Keine Vorkosten, keine Mindestabnahme, jederzeit kündbar.

Wenn Sie einverstanden sind, antworten Sie bitte mit EINVERSTANDEN. Ab dann erhalten Sie automatisch passende Profile.{SIGNATUR}""")


def arbeitgeber_profil(einrichtung: str, profil_id: str, k: dict) -> tuple[str, str]:
    orte = ", ".join(k.get("orte", [])) or "flexibel"
    return (f"Kandidatenvorschlag {profil_id}: {k.get('qualifikation') or 'Fachkraft'}", f"""Guten Tag,

wir haben eine passende Kandidatin bzw. einen passenden Kandidaten für {einrichtung or 'Ihre Einrichtung'}:

  Profil-Nr.:        {profil_id}
  Qualifikation:     {k.get('qualifikation') or '-'}
  Berufserfahrung:   {k.get('erfahrung_jahre') if k.get('erfahrung_jahre') is not None else '-'} Jahre
  Wunschort(e):      {orte}
  Verfügbar ab:      {k.get('verfuegbar_ab') or 'nach Absprache'}
  Gehaltsvorstellung:{' ' + k['gehaltswunsch'] if k.get('gehaltswunsch') else ' auf Anfrage'}

Möchten Sie die Person kennenlernen? Antworten Sie mit INTERESSE {profil_id} – wir stellen dann direkt den Kontakt her.
Es gelten die mit Ihnen vereinbarten Konditionen.{SIGNATUR}""")


def vorstellung(einrichtung: str, k: dict) -> tuple[str, str]:
    return (f"Kennenlernen: {k.get('name')} & {einrichtung}", f"""Guten Tag zusammen,

wie besprochen stellen wir Sie einander vor:

  Kandidat/in:  {k.get('name')} – {k.get('qualifikation')} – Tel. {k.get('telefon') or 'siehe E-Mail'} – {k.get('email')}
  Arbeitgeber:  {einrichtung}

Bitte vereinbaren Sie direkt einen Termin. Sagen Sie uns gern Bescheid, wie es gelaufen ist.
Hinweis an den Arbeitgeber: Es gelten die vereinbarten Konditionen; eine Einstellung bitte kurz an uns melden.{SIGNATUR}""")


def abgemeldet() -> tuple[str, str]:
    return ("Abmeldung bestätigt", f"Sie erhalten keine weiteren Nachrichten von uns. Ihre Daten werden gelöscht.{SIGNATUR}")
