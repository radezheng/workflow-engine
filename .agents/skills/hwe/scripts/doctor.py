#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    repo = Path(__file__).resolve().parents[4]
    source = repo / "src"
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    from hermes_workflow_engine.doctor import doctor_main

    return doctor_main()


if __name__ == "__main__":
    raise SystemExit(main())
