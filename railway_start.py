import subprocess
import threading
import os
import sys

if not os.environ.get('SITE_URL'):
    domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '')
    if domain:
        os.environ['SITE_URL'] = f"https://{domain}"
        print(f"[STARTUP] SITE_URL auto-set to: {os.environ['SITE_URL']}")

def run_bot():
    print("[STARTUP] Starting Discord bot...")
    print(f"[STARTUP] SITE_URL = {os.environ.get('SITE_URL', 'NOT SET')}")
    try:
        subprocess.run([sys.executable, "-u", "main.py"], check=False)
    except Exception as e:
        print(f"[ERROR] Bot crashed: {e}")

def run_dashboard():
    print("[STARTUP] Starting Dashboard...")
    port = os.environ.get('PORT', 5001)
    try:
        subprocess.run([
            sys.executable, "-u", "-m", "gunicorn", "app:app",
            "--bind", f"0.0.0.0:{port}",
            "--timeout", "120"
        ], check=False)
    except Exception as e:
        print(f"[ERROR] Dashboard crashed: {e}")

if __name__ == "__main__":
    print("=" * 50)
    print("  MAX BOT - Starting on Railway...")
    print("=" * 50)
    
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    run_dashboard()
