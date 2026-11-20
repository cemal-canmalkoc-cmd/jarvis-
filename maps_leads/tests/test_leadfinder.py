import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import leadfinder as lf


def test_scoring_ranks_no_website_highest():
    leads = {l.name: lf.score_lead(l) for l in lf.demo_leads()}
    assert leads["Salon Bella"].score > leads["Haarwerk Müller"].score > leads["Barber King"].score
    assert "keine Website" in leads["Salon Bella"].probleme
    assert leads["Barber King"].score == 0


def test_demo_run_exports_files():
    with tempfile.TemporaryDirectory() as d:
        assert lf.main(["--demo", "--out", d]) == 0
        csv_text = (Path(d) / "leads.csv").read_text(encoding="utf-8")
        assert "Salon Bella" in csv_text and "Barber King" not in csv_text
        assert "Salon Bella" in (Path(d) / "anschreiben.md").read_text(encoding="utf-8")
