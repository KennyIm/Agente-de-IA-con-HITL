import os
import hmac
import hashlib
import uuid
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from dotenv import load_dotenv

# Importamos la app compilada de LangGraph
from graph import app
load_dotenv()

SECRET_KEY = os.getenv("HMAC_SECRET_KEY")

server = FastAPI(
    title="Enterprise Incident Operations API",
    version="1.2.0"
)

#+*+ FUNCIONES DE SEGURIDAD +*+#
def generar_token_aprobacion(thread_id: str) -> str:
    """Genera un hash único firmado para un thread_id específico."""
    mensaje = f"approve_incident:{thread_id}".encode("utf-8")
    return hmac.new(SECRET_KEY.encode("utf-8"), mensaje, hashlib.sha256).hexdigest()

def verificar_token_aprobacion(thread_id: str, token_recibido: str) -> bool:
    """Valida que el token coincida exactamente con la firma esperada."""
    if not token_recibido:
        return False
    token_esperado = generar_token_aprobacion(thread_id)
    return hmac.compare_digest(token_esperado, token_recibido)
    # compare_digest evita timing attacks


# Esquemas entradas y salidas
class ReclamoInput(BaseModel):
    mensaje: str
    cliente_email: str | None = "cliente@empresa.com"
    thread_id: str | None = None # Si no viene, generamos uno nuevo

class AprobacionInput(BaseModel):
    aprobado: bool
    cliente_email: str | None = "cliente@empresa.com"
    motivo: str | None = "Aprobado por supervisor"
    token: str

@server.post("/api/v1/incidents/process")
def procesar_incidente(datos: ReclamoInput):
    """Inicia el análisis autónomo de una disputa entrante."""
    # Se asigna o recuperamos el id de la sesión
    session_id = datos.thread_id or f"inc-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": session_id}}

    mensaje_usuario = HumanMessage(content=datos.mensaje)

    # Ejecutamos el agente hasta que termine o se congele
    app.invoke(
        {
            "messages": [mensaje_usuario],
            "monto_evaluado": 0.0,
            "requiere_aprobacion": False,
            "estado_caso": "EN_REVISION",
            "cliente_email": datos.cliente_email
        },
        config=config
    )

    # Inspeccionamos si el grafo quedó pausado
    snapshot = app.get_state(config)

    # Si hay nodos en cola de espera, se activó el punto de freno
    if snapshot.next:
        ultimo_mensaje = snapshot.values["messages"][-1]
        herramienta_pendiente = None
        if ultimo_mensaje.tool_calls:
            tc = ultimo_mensaje.tool_calls[0]
            herramienta_pendiente = {"nombre": tc["name"], "argumentos": tc["args"]}

        # Generamos el token para este thread_id
        token_seguridad = generar_token_aprobacion(session_id)
        return{
            "status": "REQUIRES_APPROVAL",
            "thread_id": session_id,
            "cliente_email": snapshot.values.get("cliente_email"),
            "nodo_en_espera": snapshot.next[0],
            "accion_critica": herramienta_pendiente,
            "token": token_seguridad,
            "mensaje": "El monto excede el límite autónomo. Notificando a supervisión."
        }

    # Si terminó sin pausas
    contenido = snapshot.values["messages"][-1].content
    texto = contenido[0]["text"] if isinstance(contenido, list) else str(contenido)
    return {
        "status": "RESOLVED",
        "thread_id": session_id,
        "cliente_email": snapshot.values.get("cliente_email"),
        "respuesta": texto
    }

@server.post("/api/v1/incidents/{thread_id}/resume")
def reanudar_incidente(thread_id: str, aprobacion: AprobacionInput):
    """Reanuda la ejecución tras la decisión del supervisor."""

    if not verificar_token_aprobacion(thread_id, aprobacion.token):
        raise HTTPException(
            status_code=403,
            detail="ACCESO DENEGADO: El token de seguridad es inválido o ha sido manipulado."
        )

    config = {"configurable": {"thread_id": thread_id}}
    snapshot = app.get_state(config)

    if not snapshot.values:
        raise HTTPException(status_code=404, detail="Sesión no encontrada en el checkpointer.")

    if not snapshot.next:
        return{"status": "ALREADY_COMPLETED", "message": "Este caso ya finalizó."}

    if not aprobacion.aprobado:
        mensaje_rechazo = HumanMessage(
            content=f"DECISIÓN DEL SUPERVISOR: RECHAZADO. Motivo: {aprobacion.motivo}"
        )
        # Inyectamos el motivo del rechazo en el historial y cambiamos el estado a RECHAZADO
        app.update_state(
            config,
            {
                "messages": [mensaje_rechazo],
                "estado_caso": "RECHAZADO"
            },
            as_node="revision_humana" # Actualizamos el estado desde el nodo congelado
        )

        # Reanudamos la ejecución
        app.invoke(None, config=config)

        snapshot_final = app.get_state(config)
        contenido = snapshot_final.values["messages"][-1].content
        texto_limpio = contenido[0]["text"] if isinstance(contenido, list) and contenido else str(contenido)

        return{
            "status": "REJECTED_BY_SUPERVISOR",
            "thread_id": thread_id,
            "cliente_email": snapshot_final.values.get("cliente_email", ""),
            "respuesta": texto_limpio
        }

    # Reanudamos pasando None para que avance desde el checkpoint
    app.invoke(None, config=config)

    snapshot_final = app.get_state(config)
    
    # Extraemos el texto limpio (evita el [object Object])
    contenido = snapshot_final.values["messages"][-1].content
    if isinstance(contenido, list) and len(contenido) > 0:
        texto_limpio = contenido[0].get("text", "")
    else:
        texto_limpio = str(contenido)

    return { 
        "status": "RESOLVED_AFTER_APPROVAL",
        "thread_id": thread_id,
        "cliente_email": snapshot_final.values.get("cliente_email", ""),
        "respuesta": texto_limpio
    }