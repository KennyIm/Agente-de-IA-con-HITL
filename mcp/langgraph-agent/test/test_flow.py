from dotenv import load_dotenv
load_dotenv()
from langchain_core.messages import HumanMessage
from graph import app

# Identificador de sesión para el checkpoint
config = {"configurable": {"thread_id": "caso-reclamo-001"}}

# Simulamos el reclamo (el que viene desde n8n)
mensaje_inicial = HumanMessage(
    content="Hola, mi pedido PED-901 llegó con cajas dañadas. Adjunto la factura INV-441 por 1200 USD para que emitan el reintegro."
)

print("\n--- INICIANDO FLUJO DEL AGENTE ---")

# Primera ejecución: debe correr el analista, consultar y pausarse
estado_salida = app.invoke(
    {"messages": [mensaje_inicial], "estado_caso": "EN_REVISION", "monto_evaluado": 0.0, "requiere_aprobacion": False},
    config=config
)

# Revisamos el estado en el punto de pausa
snapshot = app.get_state(config)
print("\n[ESTADO CONGELADO]")
print("Nodo en cola de espera:", snapshot.next)

ultimo_mensaje = snapshot.values["messages"][-1]
if ultimo_mensaje.tool_calls:
    print("\nHerramienta pendiente de autorización:")
    for tc in ultimo_mensaje.tool_calls:
        print(f" -> {tc['name']} con argumentos: {tc['args']}")

print("\n" + "=" * 50)
print("SIMULACIÓN: EL SUPERVISOR HUMANO REVISA EN SLACK")
print("=" * 50)
input("Presiona ENTER para simular la aprobación del supervisor...")

# Reanudamos, pasamos None para continuar desde el checkpoint
print("\nReanudando ejecución del grafo...", flush=True)
app.invoke(None, config=config)

# Verificamos el cierre
snapshot_final = app.get_state(config)
print("\n" + "=" * 50)
print("RESULTADO FINAL Y CIERRE")
print("=" * 50)
print("Estado del caso:", snapshot_final.values.get("estado_caso"))
print("\nRespuesta generada para el cliente:")
print(snapshot_final.values["messages"][-1].content)