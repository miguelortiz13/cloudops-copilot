"""
Publica en el API los resultados de una corrida de evals (los `--json` de cada suite), para
Plataforma → IA. Lo usa el workflow semanal; necesita API_URL y ALERTS_INGEST_TOKEN:

    python -m eval.publicar resultados/*.json
"""

import json
import os
import sys

import requests


def main(rutas) -> int:
    api, token = os.getenv("API_URL", "").rstrip("/"), os.getenv("ALERTS_INGEST_TOKEN", "")
    if not api or not token:
        print("Sin API_URL o ALERTS_INGEST_TOKEN: no se publica.")
        return 0
    suites = []
    for ruta in rutas:
        try:
            with open(ruta, encoding="utf-8") as f:
                suites.append(json.load(f))
        except (OSError, ValueError) as exc:
            print(f"Se omite {ruta}: {exc}")
    cuerpo = {"model": os.getenv("GEMINI_MODEL", "gemini-3.5-flash"), "run": os.getenv("GITHUB_RUN_ID", "local"), "suites": suites}
    r = requests.post(f"{api}/api/ia/evals/ingesta", json=cuerpo, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    print(f"Publicadas {len(suites)} suite(s): HTTP {r.status_code}")
    return 0 if r.status_code < 300 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
