import os
import tempfile

# Jede Testsitzung bekommt ein eigenes Datenverzeichnis (vor dem Import von jarvis setzen)
os.environ["JARVIS_HOME"] = tempfile.mkdtemp(prefix="jarvis-test-")
os.environ["JARVIS_AUTOPILOT"] = "0"
