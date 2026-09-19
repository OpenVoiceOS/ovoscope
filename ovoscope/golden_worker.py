"""One locale of a golden run, in its own process.

:func:`ovoscope.golden_minicroft.run_rows_per_locale` starts this module
once per locale. The parent writes the job file and reads the result file;
this module boots the MiniCroft, runs the locale's rows and exits. The
process exit is what frees the model memory of an m2v boot.

Usage: ``python -m ovoscope.golden_worker <job.json> <out.json>``.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _factory(preset):
    """The stand-in ``minicroft_factory`` a test names, or ``None``."""
    from ovoscope.golden_minicroft import WORKER_FACTORY_ENV
    ref = os.environ.get(WORKER_FACTORY_ENV)
    if not ref:
        return None
    import importlib
    module, _, attribute = ref.partition(":")
    return getattr(importlib.import_module(module), attribute)(preset)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print("usage: python -m ovoscope.golden_worker <job.json> <out.json>",
              file=sys.stderr)
        return 2
    job = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    out = Path(argv[1])

    from ovoscope.golden import GoldenRow
    from ovoscope.golden_minicroft import run_rows

    rows = [GoldenRow(**row) for row in job["rows"]]
    try:
        results = run_rows(rows, job["skill_id"], Path(job["checkout"]),
                           pipeline=job["pipeline"], preset=job["preset"],
                           timeout=job["timeout"],
                           minicroft_factory=_factory(job["preset"]))
    except Exception as exc:
        out.write_text(json.dumps({
            "error_type": type(exc).__name__,
            "error": f"{type(exc).__name__}: {exc}",
        }, ensure_ascii=False), encoding="utf-8")
        return 1
    out.write_text(json.dumps(
        {"results": [r.as_dict() for r in results]}, ensure_ascii=False),
        encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit(main())
