"""Simuliert einen kompletten Vermittlungsablauf ohne echtes Postfach und ohne KI-Kosten."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["BERICHT_STUNDE_UTC"] = "0"

from mitarbeiter.agent import Mitarbeiter, passt  # noqa: E402
from mitarbeiter.postfach import Mail, TestPostfach  # noqa: E402
from mitarbeiter.speicher import Speicher, neuer_schluessel  # noqa: E402

INHABER = "chef@example.com"


class Ablauf(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.key = neuer_schluessel()
        self.pfad = Path(self.tmp.name) / "crm.enc"
        self.n = 0

    def lauf(self, *mails, jobs=None):
        self.pf = TestPostfach(list(mails))
        m = Mitarbeiter(self.pf, Speicher(self.pfad, self.key), INHABER, jobs or [])
        m.arbeitstag(bericht_erzwingen=True)
        return m

    def mail(self, von, betreff, text):
        self.n += 1
        return Mail(f"<{self.n}@test>", von, betreff, text)

    def an(self, adresse):
        return [g for g in self.pf.ausgang if g.an == adresse]

    def test_kompletter_ablauf(self):
        kand, klinik = "anna@example.com", "hr@klinik.de"
        self.lauf(self.mail(kand, "Neue Bewerbung", "typ: Kandidat\nname: Anna\ntelefon: 0170 123\n"
                            "qualifikation: examinierte Pflegefachkraft\nerfahrung: 5\nwunschort: Köln, Bonn"))
        self.assertIn("JA", self.an(kand)[0].text)

        self.lauf(self.mail(kand, "Re: Ihre Bewerbung", "Ja\n\n> Antworten Sie bitte mit JA"))
        self.assertIn("Danke", self.an(kand)[0].betreff)

        self.lauf(self.mail(klinik, "Anfrage", "typ: Arbeitgeber\neinrichtung: Klinik Köln\nname: Frau Meier\n"
                            "standort: Köln\npositionen: Pflegefachkraft Intensiv"))
        self.assertIn("EINVERSTANDEN", self.an(klinik)[0].text)

        self.lauf(self.mail(klinik, "Re: Konditionen", "Einverstanden."))
        profil = self.an(klinik)
        self.assertEqual(len(profil), 1)
        self.assertIn("K1001", profil[0].betreff)
        self.assertNotIn("Anna", profil[0].text)          # anonym!
        self.assertNotIn("0170", profil[0].text)

        m = self.lauf(self.mail(klinik, "Re: Kandidatenvorschlag K1001", "INTERESSE K1001"))
        intro = self.an(kand)
        self.assertEqual(intro[0].cc, [klinik])
        self.assertIn("0170 123", intro[0].text)
        bericht = self.an(INHABER)[0].text
        self.assertIn("Kennenlernen: 1", bericht)
        self.assertTrue(any("KENNENLERNEN" in e for e in m.db["protokoll"]))

        # Daten liegen verschlüsselt auf der Platte
        self.assertNotIn(b"Anna", self.pfad.read_bytes())

    def test_kein_profil_ohne_zustimmung_oder_partner(self):
        self.lauf(self.mail("b@x.de", "Bewerbung", "typ: Kandidat\nname: B\nqualifikation: Altenpfleger\nwunschort: Berlin"),
                  self.mail("heim@x.de", "Anfrage", "typ: Arbeitgeber\neinrichtung: Heim\nstandort: Berlin\npositionen: Altenpfleger"))
        self.assertEqual([g for g in self.pf.ausgang if "Kandidatenvorschlag" in g.betreff], [])

    def test_abmelden_loescht(self):
        self.lauf(self.mail("c@x.de", "Bewerbung", "typ: Kandidat\nname: C\nqualifikation: MFA\nwunschort: Hamburg"))
        m = self.lauf(self.mail("c@x.de", "Re", "ABMELDEN"))
        self.assertNotIn("c@x.de", m.db["kandidaten"])

    def test_unklare_mail_geht_an_inhaber(self):
        self.lauf(self.mail("x@y.de", "Kooperation?", "Hallo, wir sind eine Agentur ..."))
        self.assertIn("Unklare Mail", self.an(INHABER)[0].text)

    def test_matching_regeln(self):
        k = {"qualifikation": "Pflegefachkraft", "orte": ["Köln"]}
        self.assertTrue(passt(k, {"positionen": ["Gesundheits- und Krankenpfleger"], "orte": ["Köln"]}))
        self.assertFalse(passt(k, {"positionen": ["MFA"], "orte": ["Köln"]}))
        self.assertFalse(passt(k, {"positionen": ["Pflegefachkraft"], "orte": ["München"]}))


if __name__ == "__main__":
    unittest.main()
