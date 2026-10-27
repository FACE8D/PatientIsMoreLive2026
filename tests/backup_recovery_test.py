#!/usr/bin/env python3
"""Verify the backup utility produces a restorable SQLite copy with intact records."""
import json, os, sqlite3, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PORT=8769
with tempfile.TemporaryDirectory(prefix='clinic-backup-test-') as td:
    db=Path(td)/'source.sqlite3'; backup=Path(td)/'backup.sqlite3'
    env=os.environ.copy(); env.update(CLINIC_PORT=str(PORT),CLINIC_DB_PATH=str(db),CLINIC_HOST='127.0.0.1',CLINIC_DEMO_MODE='1')
    proc=subprocess.Popen([sys.executable,str(ROOT/'server.py')],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        base=f'http://127.0.0.1:{PORT}'
        for _ in range(100):
            try:
                with urllib.request.urlopen(base+'/api/health',timeout=1) as r:
                    if r.status==200:break
            except Exception: time.sleep(.1)
        else: raise RuntimeError('server startup timeout')
        with sqlite3.connect(db) as con:
            before={row[0]:row[1] for row in con.execute("SELECT name, (SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=t.name) FROM sqlite_master t WHERE type='table'")}
            patients=con.execute('SELECT COUNT(*) FROM patients').fetchone()[0]
            assert patients>=1, f'expected seeded synthetic patients, got {patients}'
        subprocess.run([sys.executable,str(ROOT/'backup_db.py'),'--db',str(db),'--out',str(backup)],cwd=ROOT,check=True,timeout=20)
        with sqlite3.connect(backup) as con:
            integrity=con.execute('PRAGMA integrity_check').fetchone()[0]
            after=con.execute('SELECT COUNT(*) FROM patients').fetchone()[0]
            tables=con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        assert integrity=='ok' and after==patients and tables>=len(before), (integrity,after,patients,tables)
        # Open the copied DB independently and confirm it can be queried, not merely copied.
        restored=Path(td)/'restored.sqlite3'
        with sqlite3.connect(backup) as src, sqlite3.connect(restored) as dst: src.backup(dst)
        with sqlite3.connect(restored) as con:
            assert con.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            assert con.execute('SELECT COUNT(*) FROM patients').fetchone()[0]==patients
        print(f'PASS: backup integrity and restore; patients={patients}, tables={tables}, backup_bytes={backup.stat().st_size}')
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill(); proc.wait()
