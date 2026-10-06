
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from typing import Dict, Any, Optional
from app.schemas.inventory import *
from app.schemas.k8s import *
from app.schemas.requests import *
from app.core import config
from app.core.container import get_services
from app.services.bot_auth import BOT_AUTH_ENABLED, BotAuthError, validate_bot_token
import os
import requests
from pydantic import BaseModel


router = APIRouter(tags=['teams'])

@router.post("/api/integration/test-webhook")
def test_webhook(req: WebhookTestRequest):
    """Sends a real, context-aware DevOps/FinOps/SecOps status alert to a Teams Webhook."""
    try:
        # Get actual stats to populate the webhook message with real numbers
        stats = get_services()[0].get_summary_stats()
        
        # Build payload based on alert type
        if req.alert_type == "finops":
            title = "💰 Alerta FinOps: Oportunidades de Ahorro Cloud Detectadas"
            color = "10B981"  # Emerald Success Green
            facts = [
                {"name": "Total Ahorro Mensual Estimado", "value": f"${stats.get('estimated_monthly_savings', 0.0):.2f} USD/mes"},
                {"name": "Discos Huérfanos (Unattached)", "value": f"{stats.get('orphaned_disks', 0)} discos"},
                {"name": "IPs Públicas Libres (Unassociated)", "value": f"{stats.get('orphaned_ips', 0)} direcciones IP"},
                {"name": "Interfaces de Red Huérfanas (NICs)", "value": f"{stats.get('orphaned_nics', 0)} NICs"},
                {"name": "Gobernanza de Tags", "value": f"{stats.get('tag_compliance_percentage', 0.0)}% de cumplimiento"}
            ]
            subtitle = "Reporte en tiempo real de desperdicio financiero en Azure"
        elif req.alert_type == "secops":
            title = "🚨 Alerta SecOps: Postura de Seguridad Cloud Comprometida"
            # Las cifras salen del mismo reporte que muestra el panel; antes las
            # dos ultimas filas llevaban numeros escritos a mano.
            superficie = get_services()[6].build_report().get("attack_surface_summary", {})
            color = "EF4444"  # Crimson Red
            facts = [
                {"name": "NSGs Expuestos a Internet", "value": f"{stats.get('exposed_nsgs', 0)} reglas de acceso admin (Port 22/3389/*)"},
                {"name": "Recursos en Estado Fallido", "value": f"{stats.get('failed_resources', 0)} recursos en Failed State"},
                {"name": "Storage Accounts con Acceso Público", "value": f"{superficie.get('public_storage_accounts', 0)} cuentas expuestas (Blob público habilitado)"},
                {"name": "Key Vaults sin Private Endpoints", "value": f"{superficie.get('exposed_keyvaults', 0)} bóvedas accesibles desde internet pública"}
            ]
            subtitle = "Reporte en tiempo real de vulnerabilidades y exposición de red"
        else:
            title = "📊 Reporte de Estado Cloud: Azure Inventory DevOps Intelligence"
            color = "6366F1"  # Violeta de la plataforma
            facts = [
                {"name": "Total Recursos Azure Descubiertos", "value": f"{stats.get('total_resources', 0)} recursos"},
                {"name": "Cumplimiento Global de Tags", "value": f"{stats.get('tag_compliance_percentage', 0.0)}%"},
                {"name": "Recursos Creados Fuera de IaC/Terraform", "value": f"{stats.get('portal_managed', 0)} recursos (Shadow IT)"},
                {"name": "Ahorro Mensual Potencial", "value": f"${stats.get('estimated_monthly_savings', 0.0):.2f} USD"}
            ]
            subtitle = "Resumen de gobernanza de infraestructura y visibilidad"

        # Office 365 Connector Webhook Schema
        payload = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": color,
            "summary": title,
            "title": title,
            "sections": [{
                "activityTitle": "Azure Inventory AI Bot Service",
                "activitySubtitle": subtitle,
                "activityImage": "https://img.icons8.com/color/96/azure-infrastructure.png",
                "facts": facts,
                "markdown": True
            }],
            "potentialAction": [{
                "@type": "OpenUri",
                "name": "Ver Panel de Control",
                "targets": [{"os": "default", "uri": config.FRONTEND_URL}]
            }]
        }
        
        # Post to Teams
        res = requests.post(req.webhook_url, json=payload, headers={"Content-Type": "application/json"}, timeout=12)
        if res.status_code in [200, 201, 202]:
            return {"status": "success", "message": "Alerta de prueba enviada con éxito a Microsoft Teams."}
        else:
            raise HTTPException(
                status_code=res.status_code, 
                detail=f"Teams respondió con código {res.status_code}: {res.text}"
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def get_microsoft_oauth_token() -> Optional[str]:
    """Retrieves an access token from Microsoft Identity Platform for Bot Framework."""
    client_id = os.getenv("AZURE_CLIENT_ID")
    client_secret = os.getenv("AZURE_CLIENT_SECRET")
    tenant_id = os.getenv("AZURE_TENANT_ID")
    
    if not client_id or not client_secret or not tenant_id:
        print("⚠️ Missing AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, or AZURE_TENANT_ID in Web App settings.")
        return None
        
    # Tenant-specific endpoint required for SingleTenant bots
    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://api.botframework.com/.default"
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    try:
        response = requests.post(url, data=payload, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json().get("access_token")
        else:
            print(f"❌ Microsoft Token OAuth error: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"❌ Exception fetching Microsoft Token: {e}")
        return None

def send_reply_to_teams(activity: Dict[str, Any], reply_text: str):
    """Sends the response back to the Microsoft Teams Service URL asynchronously."""
    service_url = activity.get("serviceUrl")
    conversation_id = activity.get("conversation", {}).get("id")
    activity_id = activity.get("id")
    
    if not service_url or not conversation_id or not activity_id:
        print("⚠️ Incomplete activity parameters to reply (missing serviceUrl, conversation ID, or activity ID).")
        return
        
    # 1. Fetch Auth Token
    access_token = get_microsoft_oauth_token()
    if not access_token:
        print("❌ Skip posting reply: Unable to obtain Microsoft Auth token.")
        return
        
    # 2. Build the reply endpoint URL
    url = f"{service_url.rstrip('/')}/v3/conversations/{conversation_id}/activities/{activity_id}"
    
    # 3. Build Bot Framework Activity Payload
    reply_activity = {
        "type": "message",
        "text": reply_text,
        "recipient": activity.get("from"),
        "from": activity.get("recipient"),
        "conversation": activity.get("conversation"),
        "replyToId": activity_id
    }
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    try:
        res = requests.post(url, json=reply_activity, headers=headers, timeout=15)
        print(f"📬 Sent reply to Teams SCM. Status: {res.status_code} - {res.text}")
    except Exception as e:
        print(f"❌ Exception sending post reply to Teams: {e}")


@router.post("/api/teams/webhook")
def teams_webhook(
    request: Request, activity: Dict[str, Any], background_tasks: BackgroundTasks
):
    """
    Microsoft Teams Integration Webhook.
    Conforms to Microsoft Bot Framework SDK Schema.

    La ruta esta fuera del middleware de Entra ID porque quien la invoca es el
    servicio de Bot Framework y no una persona con token de usuario. La
    autenticacion la aporta el JWT que Bot Framework firma en cada peticion;
    sin validarlo, el endpoint entregaria el inventario de la organizacion a
    cualquiera que conozca la URL. Ver services/bot_auth.py.
    """
    if BOT_AUTH_ENABLED:
        try:
            validate_bot_token(
                request.headers.get("Authorization", ""),
                service_url=activity.get("serviceUrl"),
            )
        except BotAuthError as exc:
            print(f"Actividad de Teams rechazada: {exc}")
            raise HTTPException(status_code=401, detail=str(exc))

    activity_type = activity.get("type", "")
    
    if activity_type == "message":
        text = activity.get("text", "")
        # Remove mention formatting if present
        clean_text = re.sub(r'<at>.*?</at>', '', text).strip()
        
        # Process query
        response = get_services()[0].ask(clean_text)
        
        # Send reply in the background to avoid locking Teams SCM client
        background_tasks.add_task(send_reply_to_teams, activity, response["answer"])
        
        # Save session reference in background to remember the channel/chat ID for proactive reports
        service_url = activity.get("serviceUrl")
        conversation_id = activity.get("conversation", {}).get("id")
        if service_url and conversation_id:
            try:
                import json
                session_file = config.DATA_DIR / "teams_session.json"
                with open(session_file, "w") as sf:
                    json.dump({"serviceUrl": service_url, "conversationId": conversation_id}, sf)
            except Exception as e:
                print(f"Error saving teams session reference: {e}")
        
    return {"status": "accepted"}

# --- Recommendations Lifecycle Endpoints ---

class RecommendationActionRequest(BaseModel):
    status: str
    user: str
    notes: Optional[str] = None
    expiration_days: Optional[int] = None


