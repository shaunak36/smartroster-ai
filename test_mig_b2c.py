import tempfile, shutil, os, subprocess, sqlite3
from pathlib import Path

def run_test():
    live_conn = sqlite3.connect('backend/smartroster.db')
    live_ver = live_conn.execute('SELECT version_num FROM alembic_version').fetchone()[0]
    live_conn.close()
    assert live_ver == '9a1b2c3d4e5f', f'Live db at {live_ver}'

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_db = os.path.join(tmpdir, 'test.db')
        shutil.copyfile('backend/smartroster.db', tmp_db)
        env = os.environ.copy()
        env['BACKEND_DATABASE_URL'] = f'sqlite:///{Path(tmp_db).as_posix()}'
        env['PYTHONPATH'] = os.path.abspath('backend')
        
        # 1. smartroster.db is already at 9a1b2c3d4e5f!
        # Check constraints on public_holidays before b2c
        conn = sqlite3.connect(tmp_db)
        print('Before b2c public_holidays sql:\n', conn.execute("SELECT sql FROM sqlite_master WHERE name='public_holidays'").fetchone()[0])
        print('Before b2c rosters sql:\n', conn.execute("SELECT sql FROM sqlite_master WHERE name='rosters'").fetchone()[0])
        conn.close()

        # 2. Upgrade to head (b2c3d4e5f6a7)
        res2 = subprocess.run([os.path.abspath('.\\.venv310\\Scripts\\alembic.exe'), 'upgrade', 'head'], cwd='backend', env=env, capture_output=True, text=True)
        print('Upgrade head returncode:', res2.returncode)
        print('Upgrade head stdout:\n', res2.stdout)
        print('Upgrade head stderr:\n', res2.stderr)
        assert res2.returncode == 0, f'Upgrade failed: {res2.stderr}'

        conn = sqlite3.connect(tmp_db)
        print('After b2c public_holidays sql:\n', conn.execute("SELECT sql FROM sqlite_master WHERE name='public_holidays'").fetchone()[0])
        print('After b2c rosters sql:\n', conn.execute("SELECT sql FROM sqlite_master WHERE name='rosters'").fetchone()[0])
        conn.close()

        # 3. Test downgrade
        res3 = subprocess.run([os.path.abspath('.\\.venv310\\Scripts\\alembic.exe'), 'downgrade', '-1'], cwd='backend', env=env, capture_output=True, text=True)
        print('Downgrade returncode:', res3.returncode)
        assert res3.returncode == 0, f'Downgrade failed: {res3.stderr}'

if __name__ == '__main__':
    run_test()
