"""Dispatcher de entrypoint pro cron do Railway.

Os dois workers (sync_agendor, sync_botconversa) compartilham o mesmo
railway.json/startCommand — cada serviço no Railway define sua própria
variável WORKER pra escolher qual roda. Evita precisar de config-as-code
por serviço só pra trocar o comando de start.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

WORKER = os.environ.get("WORKER", "sync_agendor")

if WORKER == "sync_agendor":
    from workers.sync_agendor import rodar
elif WORKER == "sync_botconversa":
    from workers.sync_botconversa import rodar
else:
    print(f"WORKER desconhecido: {WORKER!r} (esperado 'sync_agendor' ou 'sync_botconversa')", file=sys.stderr)
    sys.exit(1)

if __name__ == "__main__":
    rodar()
