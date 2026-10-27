#!/usr/bin/env python3
"""Create a consistent SQLite backup using SQLite's online backup API."""
import argparse
import os
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = Path(os.environ.get('CLINIC_DB_PATH', ROOT / 'data' / 'clinic.db'))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=DEFAULT_DB, help='SQLite source path')
    parser.add_argument('--out', type=Path, help='Backup path (default: backups/clinic-UTC_TIMESTAMP.sqlite3)')
    args = parser.parse_args()
    src = args.db.resolve()
    if not src.exists():
        parser.error(f'Database does not exist: {src}')
    dst = args.out.resolve() if args.out else ROOT / 'backups' / f'clinic-{datetime.utcnow():%Y%m%dT%H%M%SZ}.sqlite3'
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src == dst:
        parser.error('Source and destination must be different files')
    try:
        with sqlite3.connect(f'file:{src}?mode=ro', uri=True, timeout=30) as source:
            with sqlite3.connect(dst, timeout=30) as target:
                source.backup(target)
                check = target.execute('PRAGMA integrity_check').fetchone()[0]
                if check != 'ok':
                    raise RuntimeError(f'Backup integrity check failed: {check}')
        print(f'Backup created: {dst}')
        print(f'Size: {dst.stat().st_size} bytes; integrity_check: ok')
    except Exception:
        try: dst.unlink(missing_ok=True)
        except OSError: pass
        raise

if __name__ == '__main__':
    main()
