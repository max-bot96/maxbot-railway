import subprocess
import threading
import os
import sys
import time
import signal

if not os.environ.get('SITE_URL'):
    domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '')
    if domain:
        os.environ['SITE_URL'] = f"https://{domain}"
        print(f"[STARTUP] SITE_URL auto-set to: {os.environ['SITE_URL']}")

restart_flag = False
gunicorn_proc = None

def run_bot():
    global restart_flag
    print("[STARTUP] Starting Discord bot...")
    print(f"[STARTUP] SITE_URL = {os.environ.get('SITE_URL', 'NOT SET')}")
    try:
        result = subprocess.run([sys.executable, "-u", "main.py"], check=False)
        if result.returncode == 42:
            restart_flag = True
            print("[BOT] Restart requested! (exit code 42)")
    except Exception as e:
        print(f"[ERROR] Bot crashed: {e}")

def run_dashboard():
    global gunicorn_proc
    print("[STARTUP] Starting Dashboard...")
    port = os.environ.get('PORT', 5001)
    try:
        gunicorn_proc = subprocess.Popen([
            sys.executable, "-u", "-m", "gunicorn", "app:app",
            "--bind", f"0.0.0.0:{port}",
            "--timeout", "120"
        ])
        gunicorn_proc.wait()
    except Exception as e:
        print(f"[ERROR] Dashboard crashed: {e}")

if __name__ == "__main__":
    print("=" * 50)
    print("  MAX BOT - Starting on Railway...")
    print("=" * 50)

    while True:
        restart_flag = False
        bot_thread = threading.Thread(target=run_bot, daemon=True)
        bot_thread.start()
        run_dashboard()

        if restart_flag:
            if gunicorn_proc and gunicorn_proc.poll() is None:
                try:
                    gunicorn_proc.terminate()
                    gunicorn_proc.wait(timeout=5)
                except:
                    gunicorn_proc.kill()
            print("[RESTART] Restarting in 2 seconds...")
            time.sleep(2)
            os.execv(sys.executable, [sys.executable] + sys.argv)
        else:
            break
