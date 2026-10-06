"""
RiskService — Cruza los hallazgos de seguridad con el gasto de lo expuesto.

SecOps y FinOps no se conocian: el panel de seguridad ordenaba por severidad y
ahi terminaba, de modo que una cuenta de almacenamiento publica de 2.000 USD al
mes y una de 3 USD se veian igual de urgentes. La severidad dice *que tan
alcanzable* es algo; el gasto dice *cuanto vale*. Con las dos se puede decir por
donde empezar, que es lo que un panel de riesgo tiene que responder.

Como se combinan
----------------
La severidad manda y el dinero desempata. No al reves: un hallazgo critico
barato sigue siendo mas urgente que uno alto y caro, porque el costo es un
indicador del valor del activo, no de la probabilidad de que lo exploten.

Que se cuenta como "gasto expuesto"
-----------------------------------
El agregado se calcula **por recurso y no por hallazgo**: un mismo storage puede
aparecer en dos reglas, y sumar su costo dos veces inflaria la cifra. Cada
recurso aporta una sola vez, con su severidad mas alta.

Honestidad sobre lo que no se puede medir
-----------------------------------------
Dos casos, y ninguno se rellena con ceros:

* **Sin cobertura de costo.** El Service Principal no tiene el gasto de todas
  las suscripciones. Un recurso sin factura NO vale cero: vale *desconocido*.
  Se marca `unavailable` y se cuenta aparte, para que nadie lea "0 USD" como
  "no importa".
* **Costo no atribuible al hallazgo.** Una regla de NSG abierta no cuesta nada
  por si misma; lo que vale dinero son las maquinas que hay detras, y ese
  vinculo no se puede establecer de forma fiable desde Resource Graph. Esos
  hallazgos se marcan `not_applicable` y se ordenan solo por severidad, en vez
  de aparecer como si valieran cero.
"""

from typing import Any, Dict, List, Optional

from app.services import cost_service as cost_module

# Orden de severidad, el mismo que usa SecOpsService.
SEVERIDAD_ORDEN = {"critica": 0, "alta": 1, "media": 2, "info": 3}

# Tipos de hallazgo donde el recurso senalado ES el activo que vale dinero. En
# los demas —una regla de NSG, un recurso en estado fallido— el costo esta en
# otra parte y atribuirselo al hallazgo seria inventar.
TIPOS_CON_ACTIVO = {"storage", "keyvault", "sql", "https", "disco"}


class RiskService:
    """Prioriza los hallazgos de seguridad por severidad y por gasto expuesto."""

    def __init__(self, secops, cost):
        self.secops = secops
        self.cost = cost

    def build_report(self, subscription_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        subs = [s for s in (subscription_ids or []) if s]

        reporte = self.secops.build_report(subs)
        hallazgos = list(reporte.get("findings") or [])

        # Sin scope explicito ("todas las suscripciones") el costo se busca en las
        # suscripciones de los propios hallazgos. Antes se omitia la consulta y
        # la exposicion decia "sin gasto facturado" aunque FinOps lo tuviera.
        if not subs:
            subs = sorted({
                cost_module.subscription_of(h.get("id")) for h in hallazgos
            } - {""})

        datos_costo: Dict[str, Any] = {}
        try:
            if subs:
                # `costs_for` sirve de lo que ya dejo la precarga en segundo
                # plano; ver services/cost_service.py.
                datos_costo = self.cost.costs_for(subs)
        except Exception as exc:
            print(f"[RiskService] No se pudo obtener el gasto expuesto: {exc}")

        cobertura = datos_costo.get("coverage") or {}
        cubiertas = {str(s).lower() for s in cobertura.get("covered", [])}
        mapa = datos_costo.get("costs") or {}
        ventana = datos_costo.get("window_days") or cost_module.DEFAULT_WINDOW_DAYS
        moneda = datos_costo.get("currency") or "USD"

        enriquecidos = [
            self._enriquecer(h, mapa, cubiertas, ventana) for h in hallazgos
        ]
        enriquecidos.sort(key=self._clave_de_orden)

        exposicion = self._exposicion_por_recurso(enriquecidos)
        resumen = self._resumen_por_severidad(exposicion)

        medidos = [e for e in exposicion.values() if e["cost_basis"] == "actual"]
        sin_medir = [e for e in exposicion.values() if e["cost_basis"] == "unavailable"]

        return {
            "findings": enriquecidos,
            "severity_summary": reporte.get("severity_summary", {}),
            "exposure_by_severity": resumen,
            "top_exposure": sorted(
                (e for e in exposicion.values() if e["cost_basis"] == "actual"),
                key=lambda e: (-e["monthly_cost_usd"], SEVERIDAD_ORDEN.get(e["severidad"], 9)),
            )[:15],
            "totals": {
                "findings": len(enriquecidos),
                "affected_resources": len(exposicion),
                "measured_resources": len(medidos),
                "unmeasured_resources": len(sin_medir),
                "monthly_usd_at_risk": round(sum(e["monthly_cost_usd"] for e in medidos), 2),
                "currency": moneda,
                "window_days": ventana,
            },
            "coverage": {
                "status": datos_costo.get("status", "unavailable"),
                "covered_count": len(cubiertas),
                "uncovered_count": len(cobertura.get("denied", []))
                + len(cobertura.get("failed", [])),
                "message": self._mensaje_de_cobertura(len(cubiertas), cobertura, len(sin_medir)),
            },
        }

    # ------------------------------------------------------------------

    def _enriquecer(
        self,
        hallazgo: Dict[str, Any],
        mapa: Dict[str, float],
        cubiertas: set,
        ventana: int,
    ) -> Dict[str, Any]:
        """Anota un hallazgo con el gasto del recurso al que senala."""
        resource_id = str(hallazgo.get("id") or "").lower()
        tipo = hallazgo.get("tipo")

        if tipo not in TIPOS_CON_ACTIVO:
            # El costo existe, pero no es de este recurso: una regla de NSG no
            # factura, y el recurso fallido puede no haber llegado a crearse.
            return {**hallazgo, "monthly_cost_usd": 0.0, "cost_basis": "not_applicable"}

        if cost_module.subscription_of(resource_id) not in cubiertas:
            # Sin factura no se sabe cuanto vale. No es cero.
            return {**hallazgo, "monthly_cost_usd": 0.0, "cost_basis": "unavailable"}

        facturado = mapa.get(resource_id)
        mensual = (
            cost_module.monthly_from_window(facturado, ventana)
            if facturado is not None else 0.0
        )
        return {**hallazgo, "monthly_cost_usd": mensual, "cost_basis": "actual"}

    @staticmethod
    def _clave_de_orden(hallazgo: Dict[str, Any]):
        """
        Severidad primero, dinero despues.

        Dentro de una misma severidad hay tres grupos, en este orden:

        1. Los que tienen gasto facturado mayor que cero, de mas caro a mas
           barato. Es el desempate que motivo todo el modulo.
        2. Los que no se pueden valorar: sin cobertura de costo, o hallazgos
           cuyo costo no es atribuible al recurso senalado, como una regla de
           NSG. Valen desconocido.
        3. Los medidos en cero, que son los unicos de los que consta que no
           cuestan nada.

        Que el grupo 3 vaya despues del 2 importa: dejar los no valorables al
        final los pondria por debajo de un Key Vault facturado en 0.29 USD, y
        una regla de administracion abierta a internet no es menos urgente que
        eso solo porque no sepamos ponerle precio. Tratar "desconocido" como
        cero es justo el error que este modulo evita en todas partes.

        El desempate final es el nombre, para que el orden sea estable entre
        consultas y la lista no baile sola al recargar el panel.
        """
        severidad = SEVERIDAD_ORDEN.get(hallazgo.get("severidad"), 9)
        costo = hallazgo.get("monthly_cost_usd", 0.0)
        medido = hallazgo.get("cost_basis") == "actual"

        if medido and costo > 0:
            grupo = 0
        elif not medido:
            grupo = 1
        else:
            grupo = 2

        return (severidad, grupo, -costo, str(hallazgo.get("name") or ""))

    @staticmethod
    def _exposicion_por_recurso(hallazgos: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """
        Agrupa por recurso, quedandose con su severidad mas alta.

        Un mismo storage puede violar dos reglas; su gasto se cuenta una vez.
        """
        por_recurso: Dict[str, Dict[str, Any]] = {}
        for h in hallazgos:
            resource_id = str(h.get("id") or "").lower()
            if not resource_id or h.get("cost_basis") == "not_applicable":
                continue

            actual = por_recurso.get(resource_id)
            severidad = h.get("severidad", "media")
            if actual is None:
                por_recurso[resource_id] = {
                    "id": h.get("id"),
                    "name": h.get("name"),
                    "tipo": h.get("tipo"),
                    "severidad": severidad,
                    "monthly_cost_usd": h.get("monthly_cost_usd", 0.0),
                    "cost_basis": h.get("cost_basis"),
                    "hallazgos": 1,
                }
                continue

            actual["hallazgos"] += 1
            if SEVERIDAD_ORDEN.get(severidad, 9) < SEVERIDAD_ORDEN.get(actual["severidad"], 9):
                actual["severidad"] = severidad
        return por_recurso

    @staticmethod
    def _resumen_por_severidad(exposicion: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        resumen: Dict[str, Any] = {}
        for entrada in exposicion.values():
            fila = resumen.setdefault(
                entrada["severidad"],
                {"resources": 0, "monthly_usd": 0.0, "measured": 0, "unmeasured": 0},
            )
            fila["resources"] += 1
            if entrada["cost_basis"] == "actual":
                fila["measured"] += 1
                fila["monthly_usd"] = round(fila["monthly_usd"] + entrada["monthly_cost_usd"], 2)
            else:
                fila["unmeasured"] += 1
        return resumen

    @staticmethod
    def _mensaje_de_cobertura(cubiertas: int, cobertura: Dict[str, Any], sin_medir: int) -> str:
        sin_cubrir = len(cobertura.get("denied", [])) + len(cobertura.get("failed", []))
        if not cubiertas:
            return (
                "No hay gasto facturado disponible, así que los hallazgos van ordenados "
                "solo por severidad."
            )
        if sin_cubrir:
            return (
                f"Gasto facturado sobre {cubiertas} de {cubiertas + sin_cubrir} suscripciones. "
                f"{sin_medir} recurso(s) afectado(s) quedan sin costo conocido: no valen cero, "
                "valen desconocido."
            )
        return (
            f"Gasto facturado sobre las {cubiertas} suscripciones del scope: la exposición "
            "está valorada por completo."
        )
