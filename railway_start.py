import subprocess
import threading
import os
import sys
import time

if not os.environ.get('SITE_URL'):
    domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '')
    if domain:
        os.environ['SITE_URL'] = f"https://{domain}"
        print(f"[STARTUP] SITE_URL auto-set to: {os.environ['SITE_URL']}")

gunicorn_proc = None

def run_migrations():
    print("[MIGRATE] Running alembic upgrade head...", flush=True)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "db/alembic.ini", "upgrade", "head"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"[MIGRATE] ✅ {result.stdout.strip()}", flush=True)
    else:
        print(f"[MIGRATE] ❌ {result.stderr.strip()}", flush=True)

def run_seed():
    print("[SEED] Running database seed...", flush=True)
    result = subprocess.run([sys.executable, "-u", "db/seed.py"], capture_output=True, text=True)
    for line in result.stdout.strip().split("\n"):
        if line.strip():
            print(f"[SEED] {line.strip()}", flush=True)
    if result.returncode != 0:
        for line in result.stderr.strip().split("\n"):
            if line.strip():
                print(f"[SEED] ❌ {line.strip()}", flush=True)

def run_bot():
    print("[STARTUP] Starting Discord bot...", flush=True)
    print(f"[STARTUP] SITE_URL = {os.environ.get('SITE_URL', 'NOT SET')}", flush=True)
    run_migrations()
    run_seed()
    subprocess.run([sys.executable, "-u", "main.py"], check=False)
    print("[BOT] Bot process ended!", flush=True)

def run_dashboard():
    global gunicorn_proc
    print("[STARTUP] Starting Dashboard...", flush=True)
    port = os.environ.get('PORT', 5001)
    gunicorn_proc = subprocess.Popen([
        sys.executable, "-u", "-m", "gunicorn", "app:app",
        "--bind", f"0.0.0.0:{port}",
        "--timeout", "120"
    ])

if __name__ == "__main__":
    print("=" * 50)
    print("  MAX BOT - Starting on Railway...")
    print("=" * 50)

    while True:
        bot_thread = threading.Thread(target=run_bot, daemon=True)
        bot_thread.start()

        dashboard_thread = threading.Thread(target=run_dashboard, daemon=True)
        dashboard_thread.start()

        bot_thread.join()

        print("[BOT] Bot died — restarting in 3 seconds...", flush=True)
        if gunicorn_proc and gunicorn_proc.poll() is None:
            gunicorn_proc.terminate()
            try:
                gunicorn_proc.wait(timeout=5)
            except:
                gunicorn_proc.kill()
        time.sleep(3)
        os.execv(sys.executable, [sys.executable] + sys.argv)
