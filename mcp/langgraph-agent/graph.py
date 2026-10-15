from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())
import os
import sqlite3
from typing import Annotated, Literal
from typing_extensions import TypedDict

from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.sqlite import SqliteSaver

from FastMCPServer import consultar_pedido, verificar_factura, registrar_compensacion

#*******************************************************#
#                STATE (estado compartido)              #
#*******************************************************#

class IncidentState(TypedDict):
    # 'add_messages' asegura que cada nuevo mensaje se agregue a la lista "historial"
    messages: Annotated[list, add_messages]
    monto_evaluado: float
    requiere_aprobacion: bool
    estado_caso: str  # EN_REVISION, PENDIENTE_HUMANO, APROBADO, RECHAZADO
    cliente_email: str

#*******************************************************#
#         Vinculación del modelo y herramientas         #
#*******************************************************#
tools = [consultar_pedido, verificar_factura, registrar_compensacion]
herramientas_dict = {t.__name__: t for t in tools}

llm = ChatGoogleGenerativeAI(model="gemini-3.5-flash-lite", temperature=0)
llm_con_herramientas = llm.bind_tools(tools)

SYSTEM_PROMPT = """Eres el Agente de Operaciones y Disputas de la empresa.
Tu labor es auditar reclamos de pedidos y facturación.

Reglas obligatorias:
1. SIEMPRE consulta el pedido con 'consultar_pedido' y la factura con 'verificar_factura' antes de tomar decisiones.
2. Si el pedido tuvo problemas y el reclamo es legítimo, solicita 'registrar_compensacion'.
3. Si el monto a compensar supera los 500 USD, debes advertir que se requiere aprobación gerencial.
"""

#**********************************************************#
#             NODOS (Funciones puras de ejecución)         #
#**********************************************************#
def nodo_analista(state: IncidentState) -> dict:
    """El LLM evalúa el contexto y decide si responde o llama a herramientas."""
    mensajes = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    respuesta = llm_con_herramientas.invoke(mensajes)
    return {"messages": [respuesta]}

def nodo_ejecutar_herramientas(state: IncidentState) -> dict:
    """Ejecuta las herramientas buscando el último mensaje con llamadas pendientes."""
    # Buscamos en el historial el mensaje con las herramientas
    mensaje_con_tools = None
    for msg in reversed(state["messages"]):
        if getattr(msg, "tool_calls", None):
            mensaje_con_tools = msg
            break

    # Si no hay ninguna llamada a herramienta pendiente, devolvemos la lista vacía.
    if not mensaje_con_tools:
        return {"messages": []}

    mensajes_herramientas = []

    for tool_call in mensaje_con_tools.tool_calls:
        nombre = tool_call["name"]
        args = tool_call["args"]

        funcion = herramientas_dict.get(nombre)
        if funcion:
            resultado = funcion(**args)
        else:
            resultado = {"error": f"Herramienta '{nombre}' no disponible"}

        mensajes_herramientas.append(
            ToolMessage(
                tool_call_id=tool_call["id"],
                content=str(resultado)
            )
        )

    return {"messages": mensajes_herramientas}

def nodo_revision_humana(state: IncidentState) -> dict:
    """Nodo al que se llega cuando se detecta una operación de alto riesgo."""
    return {
        "requiere_aprobacion": True,
        "estado_caso": "PENDIENTE_HUMANO"
    }

def nodo_procesar_rechazo(state: IncidentState) -> dict:
    """Redacta la respuesta formal al cliente explicando el motivo del rechazo.
    Utilizaremos el LLM básico para evitar la ejecución de alguna acción financiera."""
    prompt_rechazo = SystemMessage(
        content=(
            "La solicitud de compensación ha sido RECHAZADA por la gerencia/supervisor."
            "Redacta una respuesta formal, profesional y empática hacia el cliente"
            "explicando los motivos basándote en la última observación del supervisor"
            "NO menciones códigos de herramientas ni prometas pagos."
        )
    )

    respuesta = llm.invoke(state["messages"] + [prompt_rechazo])

    return{
        "messages": [respuesta],
        "estado_caso": "RECHAZADO"
    }

#***********************************************#
#         Enrutamiento condicional (edges)      #
#***********************************************#
def enrutar_tras_revision(state: IncidentState) -> Literal["ejecutar_herramientas", "procesar_rechazo"]:
    """Decide el camino una vez que el supervisor interviene."""
    if state.get("estado_caso") == "RECHAZADO":
        return "procesar_rechazo"
    return "ejecutar_herramientas"

def enrutar_decision(state: IncidentState) -> Literal["ejecutar_herramientas", "revision_humana", "procesar_rechazo", "fin"]:

    # Evaluamos primero si el estado cambió a RECHAZADO
    if state.get("estado_caso") == "RECHAZADO":
        return "procesar_rechazo"
    
    ultimo_mensaje = state["messages"][-1]

    # Si el LLM no llamó a ninguna herramienta, significa que dio su respuesta final
    if not ultimo_mensaje.tool_calls:
        return "fin"

    # Revisamos si intento registrar su compensación de alto valor (mayor a 500 usd)
    for tc in ultimo_mensaje.tool_calls:
        if tc["name"] == "registrar_compensacion":
            monto = tc["args"].get("monto", 0.0)
            if monto > 500.0:
                return "revision_humana"

    # Para consultas de pedido, facturas o compensaciones bajas
    return "ejecutar_herramientas"


#***********************************************#
#             Construcción del grafo            #
#***********************************************#

builder = StateGraph(IncidentState)

builder.add_node("analista", nodo_analista)
builder.add_node("ejecutar_herramientas", nodo_ejecutar_herramientas)
builder.add_node("revision_humana", nodo_revision_humana)
builder.add_node("procesar_rechazo", nodo_procesar_rechazo)

builder.add_edge(START, "analista")

builder.add_conditional_edges(
    "analista",
    enrutar_decision,
    {
        "ejecutar_herramientas": "ejecutar_herramientas",
        "revision_humana": "revision_humana",
        "procesar_rechazo": "procesar_rechazo",
        "fin": END
    }
)

# Tras ejecutar herramientas seguras, volvemos al analista para que interprete los datos devueltos
builder.add_edge("ejecutar_herramientas", "analista")

# Si el supervisor autoriza, continuaremos desde aqui
builder.add_conditional_edges(
    "revision_humana", 
    enrutar_tras_revision, 
    {
        "ejecutar_herramientas": "ejecutar_herramientas",
        "procesar_rechazo": "procesar_rechazo"
    }
)

# Checkpoint en memoria para retomar la sesión por thread_id
conn = sqlite3.connect("checkpoints.db", check_same_thread=False)
memoria = SqliteSaver(conn)
## -Agregamos Sqlite para generar una db (guardar el reclamo y recuperarlo)- ##

app = builder.compile(
    checkpointer=memoria,
    interrupt_before=["revision_humana"] #Freno automático
)