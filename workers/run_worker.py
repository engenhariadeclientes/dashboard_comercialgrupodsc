"""Dispatcher de entrypoint pro cron do Railway.

Os workers (sync_agendor, sync_botconversa, prospeccao_google) compartilham o
mesmo railway.json/startCommand — cada serviço no Railway define sua própria
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
elif WORKER == "prospeccao_google":
    from workers.prospeccao_google import rodar
else:
    print(
        f"WORKER desconhecido: {WORKER!r} (esperado 'sync_agendor', 'sync_botconversa' ou 'prospeccao_google')",
        file=sys.stderr,
    )
    sys.exit(1)

if __name__ == "__main__":
    rodar()
