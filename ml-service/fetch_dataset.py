"""Resolve the Kaggle dataset without vendoring it.

The dataset is not committed to this repository: it carries Kaggle's terms, and
a 37 MB CSV does not belong in version control. This script locates it, records
where it came from and what it hashed to, and writes that provenance next to the
experiment artifacts so a result can be tied to a specific file.

Run::

    python fetch_dataset.py
    python fetch_dataset.py --csv /explicit/path/human_vital_signs_dataset_2024.csv
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vitalsync_ml.kaggle_audit import locate_csv  # noqa: E402

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"

EXPECTED_ROWS = 200_020
EXPECTED_COLUMNS = 17


def sha256(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Resolve and fingerprint the dataset")
    ap.add_argument("--csv", default=None)
    ap.add_argument("--out", default=str(ARTIFACTS / "dataset_provenance.json"))
    args = ap.parse_args(argv)

    csv = locate_csv(args.csv)
    if csv is None:
        print(
            "Dataset not found.\n"
            "  Option 1: pip install kagglehub && python -c \"import kagglehub;"
            "kagglehub.dataset_download('nasirayub2/human-vital-sign-dataset')\"\n"
            "  Option 2: set VITALSYNC_KAGGLE_CSV to the CSV path\n"
            "  Option 3: pass --csv /path/to/human_vital_signs_dataset_2024.csv\n"
            "\nTrack A (the dataset audit) needs this file. Track B is fully "
            "synthetic and runs without it.",
            file=sys.stderr,
        )
        return 2

    import pandas as pd

    df = pd.read_csv(csv)
    digest = sha256(csv)

    provenance = {
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        "kaggle_ref": "nasirayub2/human-vital-sign-dataset",
        "kaggle_url": "https://www.kaggle.com/datasets/nasirayub2/human-vital-sign-dataset",
        "resolved_path": str(csv),
        "sha256": digest,
        "bytes": csv.stat().st_size,
        "rows": int(df.shape[0]),
        "columns": int(df.shape[1]),
        "column_names": list(df.columns),
        "label_column": "Risk Category",
        "label_values": {k: int(v) for k, v in df["Risk Category"].value_counts().items()},
        "matches_expected_shape": bool(
            df.shape[0] == EXPECTED_ROWS and df.shape[1] == EXPECTED_COLUMNS),
        "licence_note": (
            "Redistribution is governed by the Kaggle dataset terms. The file is "
            "deliberately not vendored in this repository; this record exists so "
            "a published result can be tied to a specific file."
        ),
        "audit_note": (
            "This dataset's Risk Category label is a deterministic rule over "
            "heart rate and BMI. See artifacts/audit.json and docs/MASTER_PLAN.md "
            "section 0 before using it to train anything."
        ),
    }

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(provenance, indent=2))

    print(f"resolved : {csv}")
    print(f"sha256   : {digest}")
    print(f"shape    : {df.shape[0]:,} x {df.shape[1]}")
    if not provenance["matches_expected_shape"]:
        print(f"WARNING  : expected {EXPECTED_ROWS:,} x {EXPECTED_COLUMNS}; "
              f"a different version may change the audit result.", file=sys.stderr)
    print(f"[ok] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
