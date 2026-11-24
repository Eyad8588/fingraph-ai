"""Upload every file in samples/docs through the real ingestion pipeline and wait until processed.

    uv run python scripts/load_samples.py            # uses the running app's data directory
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fingraph.api import App  # noqa: E402
from fingraph.ingest import DuplicateFile  # noqa: E402

core = App()
core.ingestor.start()
t0 = time.time()
for f in sorted((Path(__file__).resolve().parent.parent / "samples" / "docs").iterdir()):
    try:
        core.ingestor.submit(f.name, f.read_bytes())
        print("queued", f.name)
    except DuplicateFile:
        print("skip (already uploaded)", f.name)
core.ingestor.wait_idle(1800)
for d in core.store.list_documents(100):
    print(f"{d['status']:8} {d['processing_ms'] or 0:6} ms  {d['doc_type'] or '':16} {d['filename']}  {d['error'] or ''}")
print(f"done in {time.time() - t0:.1f}s")
