"""
Evaluación de la IA de cada dominio (plan 11, hito IA-1).

Un caso por función de IA de los dominios, con el mismo prompt de producción y datos de ejemplo
realistas: explicación de la ficha del recurso, explicación de una alerta de costo, borrador de
excepción de control, post-mortem y resumen semanal. Cada caso verifica lo que debe decir y, con
eval/cifras.py, que **ninguna cifra sea inventada**. Usa el modelo real (gasta tokens):

    cd backend && GEMINI_API_KEY=... python -m eval.dominios [--json resultado.json]
"""

import os
import re
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="eval-dominios-")
os.environ.setdefault("LLM_PROVIDER", "gemini")
os.environ["DATA_DIR"] = TMP

from app import llm  # noqa: E402
from app.ai import guardas, incidentes  # noqa: E402
from app.collectors import semanal  # noqa: E402
from app.core import config  # noqa: E402
from app.dominios.activos import servicio as activos  # noqa: E402
from app.dominios.costos import servicio as costos  # noqa: E402
from app.dominios.riesgo import servicio as riesgo  # noqa: E402
from eval import cifras, resultado  # noqa: E402

FICHA = {"name": "stdatosprod", "provider": "azure", "type": "storage.account", "region": "eastus2", "group": "rg-datos",
         "tags": {"Environment": "prod"}, "missing_tags": ["Project", "ManagedBy"], "in_iac": False, "created_by": "ana@contoso.example",
         "first_seen": "2026-09-02T10:00:00+00:00", "deleted_at": None,
         "classification": {"classification": "Confidencial", "confidentiality": 3, "integrity": 2, "availability": 2},
         "cluster": None, "cost": {"total_30d": 18.42, "currency": "USD", "by_service": [{"service": "Storage", "cost": 16.9}, {"service": "Bandwidth", "cost": 1.52}]},
         "findings": [{"title": "Acceso público a blobs habilitado", "severity": "alta", "status": "abierto",
                       "remediation": "Desactivar allowBlobPublicAccess."}], "incidents": []}

ALERTA = {"alerta": {"tipo": "anomalia", "titulo": "Gasto anómalo en sub-datos el 07-11", "nube": "azure", "dia": "2026-11-07",
                     "monto_usd": 9.84, "referencia_usd": 1.12},
          "por_servicio": [{"clave": "Virtual Machines", "dia": 8.61, "media": 0.2}, {"clave": "Storage", "dia": 1.1, "media": 0.9}],
          "por_recurso": [{"clave": "azure:/subscriptions/1/resourcegroups/rg-ml/providers/microsoft.compute/virtualmachines/vm-gpu-01", "dia": 8.4, "media": 0.0}],
          "recursos_nuevos": [{"nombre": "vm-gpu-01", "tipo": "compute.vm", "creado_por": "luis@contoso.example", "visto": "2026-11-07"}]}

CONTROL = {"marco": "cis-azure-2.0.0", "control": "8.7", "titulo": "Ensure that Private Endpoints are Used for Azure Key Vault",
           "estado": "no_cumple", "evidencia": [{"kind": "rule", "rule_id": "secrets.vault-public-network",
                                                 "title": "Key Vault alcanzable desde red pública", "status": "no_cumple", "active": 1}]}

POSTMORTEM = ("Incidente #31: PodNotReady · boutique · currencyservice. Clúster local-k8s-lab, severidad alta, abierto 2026-11-05T04:18, "
              "cerrado 2026-11-05T04:41 (23 min), cierre: solucionado. Diagnóstico marcado como: correcto.\n"
              "Diagnóstico:\n**Causa probable** (confianza alta): la imagen currencyservice:v9.9.9 no existe en el registro (NotFound), "
              "desplegada en la revisión 9 a las 04:11.\n"
              "Línea de tiempo:\n2026-11-05T04:18 alertmanager: 1 alerta(s): PodNotReady\n2026-11-05T04:19 agente: Diagnóstico con 2 consulta(s).\n"
              "2026-11-05T04:30 ana@contoso.example: Reconocido\n2026-11-05T04:41 alertmanager: La fuente avisó que se resolvió.")

SEMANA = {"semana": "2026-W45", "desde": "2026-11-02", "hasta": "2026-11-08",
          "costos": {"total_usd": 7.0, "semana_anterior_usd": 3.5, "principales_servicios": [["Virtual Machines", 4.2], ["Storage", 1.9]],
                     "datos_hasta": "2026-11-06"},
          "hallazgos": {"detectados": 3, "resueltos": 1, "abiertos_criticos": 1, "abiertos_altos": 5},
          "incidentes": {"total": 4, "siguen_abiertos": 1, "criticos": 1, "tormentas": 0, "mediana_min_para_resolver": 23,
                         "diagnosticos_marcados": 3, "diagnosticos_correctos": 3, "cerrados_como_ruido": 1},
          "recursos": {"nuevos": 12, "nuevos_fuera_de_terraform": 4, "borrados": 2}, "job": {"ok": 98, "con_error": 1}}

# (nombre, uso, prompt de sistema, datos, patrones que debe contener)
CASOS = [
    ("Activos: explicar la ficha del recurso", "activos.explicar", activos.SISTEMA.format(org="Contoso"), FICHA,
     [r"almacenamiento|storage", r"18[.,]42", r"p[uú]blic", r"Terraform"]),
    ("Costos: explicar una anomalía", "costos.explicar", costos.SISTEMA.format(org="Contoso"), ALERTA,
     [r"vm-gpu-01", r"9[.,]84|8[.,]61"]),
    ("Riesgo: borrador de excepción", "riesgo.excepcion", riesgo.SISTEMA.format(org="Contoso"), CONTROL,
     [r"key ?vault|red p[uú]blica|private endpoint", r"\[completar|mitig"]),
    ("Operación: post-mortem", "incidente.postmortem", incidentes.POSTMORTEM.format(org="Contoso"), POSTMORTEM,
     [r"Resumen", r"L[ií]nea de tiempo", r"Causa", r"Acciones", r"v9\.9\.9"]),
    ("Inicio: resumen semanal", "resumen.semanal", semanal.SISTEMA.format(org="Contoso"), SEMANA,
     [r"7[.,]0|7 USD|\$ ?7", r"Para esta semana"]),
]


def main() -> int:
    if not llm.disponible():
        print("Falta GEMINI_API_KEY.")
        return 2
    casos = []
    for nombre, uso, sistema, datos, esperado in CASOS:
        mensaje = guardas.delimitar(datos)  # como en producción
        try:
            texto = llm.generar(f"eval.{uso}", sistema, mensaje, usuario="eval").texto or ""
        except llm.LLMError as exc:
            texto = f"(error: {exc})"
        faltan = [p for p in esperado if not re.search(p, texto, re.I)]
        inventadas = cifras.inventadas(texto, sistema + "\n" + mensaje)  # el prompt también es dato ("30 días")
        ok = not faltan and not inventadas
        casos.append({"name": nombre, "ok": ok, "invented": inventadas,
                      "reason": None if ok else f"faltan {faltan}; cifras inventadas {inventadas}"})
        print(f"[{'OK' if ok else 'FALLA'}] {nombre}" + ("" if ok else f"\n    {casos[-1]['reason']}") + f"\n    {texto[:240]!r}\n")
    r = resultado.guardar("dominios", casos)
    print(f"Casos correctos: {r['passed']}/{r['cases']} = {r['accuracy']:.0%} · cifras inventadas: {r['invented_numbers']} (objetivo: 90 % y 0)")
    return 0 if r["accuracy"] >= 0.9 and r["invented_numbers"] == 0 else 1


if __name__ == "__main__":
    config.ORG_NAME = "Contoso"
    sys.exit(main())
