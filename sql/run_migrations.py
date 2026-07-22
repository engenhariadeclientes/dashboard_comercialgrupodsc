"""Aplica os arquivos .sql desta pasta, em ordem alfabética, contra DATABASE_URL.
Idempotente: registra cada arquivo aplicado em schema_migrations; reexecutar não duplica.
"""
import os
import sys
from pathlib import Path

import psycopg

SQL_DIR = Path(__file__).parent


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL não definida no ambiente.", file=sys.stderr)
        sys.exit(1)

    arquivos = sorted(p for p in SQL_DIR.glob("*.sql"))
    if not arquivos:
        print("Nenhum arquivo .sql encontrado.", file=sys.stderr)
        sys.exit(1)

    with psycopg.connect(database_url, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    arquivo TEXT PRIMARY KEY,
                    aplicado_em TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        conn.commit()

        for arquivo in arquivos:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM schema_migrations WHERE arquivo = %s", (arquivo.name,)
                )
                if cur.fetchone():
                    print(f"[skip] {arquivo.name} (já aplicado)")
                    continue

            sql = arquivo.read_text(encoding="utf-8")
            try:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    cur.execute(
                        "INSERT INTO schema_migrations (arquivo) VALUES (%s)", (arquivo.name,)
                    )
                conn.commit()
                print(f"[ok]   {arquivo.name}")
            except Exception as exc:
                conn.rollback()
                print(f"[erro] {arquivo.name}: {exc}", file=sys.stderr)
                sys.exit(1)


if __name__ == "__main__":
    main()
