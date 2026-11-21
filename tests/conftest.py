import os
import tempfile

# Jede Testsitzung bekommt ein eigenes Datenverzeichnis (vor dem Import von jarvis setzen)
os.environ["JARVIS_HOME"] = tempfile.mkdtemp(prefix="jarvis-test-")
os.environ["JARVIS_AUTOPILOT"] = "0"
os.environ["JARVIS_ASK_DAILY"] = "0"  # ältere Tests prüfen die 5-Tage-Freigabe; tägliches Fragen hat eigene Tests
