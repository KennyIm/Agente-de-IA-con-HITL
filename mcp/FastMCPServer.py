from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

# Inicializar servidor
mcp = MCPServer("EnterpriseOpsServer")

# **************************************************************
#                   Base de datos SIMULACIÓN                   #
# **************************************************************
DB_PEDIDOS = {
    "PED-901": {
        "id": "PED-901",
        "cliente_id": "CLI-554",
        "cliente_email": "carlos.m@empresa.com",
        "estado": "Entregado con observaciones",
        "fecha_entrega": "2026-03-25",
        "origen": "Centro de Distribución Central",
        "destino": "Sucursal Santiago",
        "items": [
            {"sku": "SKU-A1", "descripcion": "Monitor 27 IPS", "cantidad": 5, "precio_unitario": 240.0}
        ],
        "metadata_interna": {"chofer_id": 992, "gps_lat": -33.45, "gps_lon": -70.66}
    }
}

DB_FACTURAS = {
    "INV-441": {
        "id": "INV-441",
        "pedido_id": "PED-901",
        "monto_neto": 1200.0,
        "impuesto": 228.0,
        "monto_total": 1428.0,
        "estado_pago": "Pagado",
        "fecha_emision": "2026-03-20" 
    }
}

DB_COMPENSACIONES = [] #Registo historico de notas de créditos

#************************************************************************
#                            SCHEMAS / DTOs                             #
#************************************************************************

#Filtramos para obtener solo los datos mas relevantes para ahorrar tokens y evitar confusiones al LLM

class PedidosResumen(BaseModel):
    id: str
    cliente_email: str
    estado: str
    fecha_entrega: str
    descripcion_items: str

class FacturarResumen(BaseModel):
    id: str
    pedido_id: str
    monto_neto: float
    monto_total: float
    estado_pago: str

#************************************************************************
#                      TOOLS del protocolo MCP                          #
#************************************************************************

@mcp.tool()
def consultar_pedido(order_id: str) -> dict:
    """Consulta los datos logísticos y de entrega de un pedido mediante su identificador.

    Args:
        order_id: Código único del pedido en formato 'PED-XXX' (ejemplo: 'PED-901'). 
    """

    order_id = order_id.strip().upper()

    if order_id not in DB_PEDIDOS:
        #No lanzamos un error, informamos con claridad que paso
        return{
            "encontrado": False,
            "error": f"El pedido con identificador '{order_id}' no existe en el sistema logístico"
        }

    pedido = DB_PEDIDOS[order_id]

    # DTO limpio (se excluyen campos por ejemplo logs)
    resumen_items = ", ".join(f"{item['cantidad']}x {item['descripcion']}" for item in pedido["items"])

    dto = PedidosResumen(
        id=pedido["id"],
        cliente_email=pedido["cliente_email"],
        estado=pedido["estado"],
        fecha_entrega=pedido["fecha_entrega"],
        descripcion_items=resumen_items
    )

    return {"encontrado": True, "datos": dto.model_dump()}

@mcp.tool()
def verificar_factura(invoice_id: str) -> dict:
    """Verifica el estado contable y montos de una factura comercial.


    Args:
        invoice_id: Código fiscal de la factura en formato 'INV-XXX' (ejemplo: 'INV-441').
    """

    invoice_id = invoice_id.strip().upper()

    if invoice_id not in DB_FACTURAS:
        return{
            "encontrado": False,
            "error": f"La factura '{invoice_id}' no figura en los registros contables."
        }

    factura = DB_FACTURAS[invoice_id]

    dto = FacturarResumen(
        id=factura["id"],
        pedido_id=factura["pedido_id"],
        monto_neto=factura["monto_neto"],
        monto_total=factura["monto_total"],
        estado_pago=factura["estado_pago"]
    )

    return {"encontrado": True, "datos": dto.model_dump()}

@mcp.tool()
def registrar_compensacion(order_id: str, monto: float, motivo: str) -> dict:
    """Registra y emite formalmente una compensación o nota de crédito para un pedido.
    ADVERTENCIA: Esta herramienta tiene efectos secundarios contables.

    Args:
        order_id: Identificador del pedido afectado (ej: 'PED-901').
        monto: Monto en USD a compensar. Debe ser un valor positivo mayor a cero.
        motivo: Justificación comercial o técnica del reintegro.
    """

    order_id = order_id.strip().upper()

    if monto <= 0:
        return{
            "exito": False,
            "error": f"Monto inválido: {monto}. La compensación debe ser mayor a 0 USD."
        }
    if order_id not in DB_PEDIDOS:
        return{
            "exito": False,
            "error": f"No se puede emitir compensación: El pedido '{order_id}' no existe."
        }
    #Verificamos que el monto asociado a la factura sea el mismo para la compensación, para evitar estafas/robos.
    factura_asociada = next((f for f in DB_FACTURAS.values() if f["pedido_id"] == order_id), None)
    if factura_asociada and monto > factura_asociada["monto_total"]:
        return{
            "exito": False,
            "error": f"Monto excede el total facturado ({factura_asociada['monto_total']} USD). Operación rechazada."
        }

    registro = {
        "id_compensacion": f"COMP-{len(DB_COMPENSACIONES) + 1:04d}",
        "order_id": order_id,
        "monto": monto,
        "motivo": motivo,
        "timestamp": datetime.now().isoformat()
    }
    DB_COMPENSACIONES.append(registro)

    return{
        "exito": True,
        "mensaje": "Nota de crédito registrada exitosamente en el sistema.",
        "detalle": registro
    }

#********************************************************************#
#                       ENTRADA PRINCIPAL                            #
#********************************************************************#

if __name__ == "__main__":
    #Inicia el servidor
    mcp.run()



