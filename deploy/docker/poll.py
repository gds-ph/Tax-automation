"""One process per background service, bounded retries and clean shutdown."""
import os
import signal
import subprocess
import sys
import threading

stop = threading.Event()
signal.signal(signal.SIGTERM, lambda *_: stop.set())
signal.signal(signal.SIGINT, lambda *_: stop.set())
mode = sys.argv[1]
commands = {
    'receipts': ('check_bir_receipts', 60),
    'cards': ('generate_registration_cards', 900),
}
command, interval = commands[mode]
if mode == 'cards' and not all(os.environ.get(k) for k in ('GDS_BASE_URL', 'GDS_API_KEY', 'GDS_MODEL')):
    raise SystemExit('COR scanner requires GDS_BASE_URL, GDS_API_KEY and GDS_MODEL.')
while not stop.is_set():
    process = subprocess.Popen([sys.executable, 'manage.py', command])
    while process.poll() is None:
        if stop.wait(1):
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            break
    if process.returncode:
        print(f'{command} failed with exit code {process.returncode}; retrying after {interval}s.', flush=True)
    stop.wait(interval)
