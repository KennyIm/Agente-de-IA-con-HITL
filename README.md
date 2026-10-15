# Autonomous Incident Operations & Claims Agent (Enterprise HITL Edition)

Un sistema agéntico autónomo para la gestión y auditoría de reclamos logísticos. Diseñado con **LangGraph**, **FastAPI**, **Google Gemini 3.5 Flash-lite**, **FastMCP**, **n8n** y arquitectura **Human-in-the-Loop (HITL)** asegurada mediante **firmas criptográficas HMAC-SHA256**.

## Arquitectura del Sistema

```
                                  [ Reclamo Cliente / Webhook ]
                                               │
                                               ▼
                                     [ n8n Orchestrator ]
                                               │
                                      (HTTP POST /process)
                                               ▼
                                     [ FastAPI Microservice ]
                                               │
                                      (LangGraph Agent Loop)
                                               │
                         ┌─────────────────────┴─────────────────────┐
                [ Monto =< 500$ USD ]                      [ Monto > 500$ USD ]
                         │                                           │
          (Ejecuta Tool de inmediato)                       (Freno de Riesgo)
                         │                                           │
                [ Estado: RESOLVED ]                    (Guarda Checkpoint en SQLite)
                                                                     │
                                                           (Genera Token HMAC-SHA256)
                                                                     │
                                                           [ Alerta a Supervisión ]
                                                                     │
                                                      ┌──────────────┴──────────────┐
                                               [ Aprobar ]                   [ Rechazar ]
                                                      │                             │
                                            (POST /resume + Token)        (POST /resume + Token)
                                                      │                             │
                                              (Firma Válida)                (Firma Válida)
                                                      │                             │
                                            [ Tool COMP-0001 ]           [ Bypass Tool + Carta ]

```

## Tech Stack

* **Agente IA & Orquestación de Grafo:** [LangGraph](https://github.com/langchain-ai/langgraph), [LangChain](https://github.com/langchain-ai/langchain).

* **Modelo LLM:** Google Gemini 3.5 Flash-lite (`gemini-3.5-flash-lite`).

* **Microservicio REST:** FastAPI, Uvicorn, Pydantic v2.

* **Persistencia de Sesión:** SQLite Checkpointer (`langgraph-checkpoint-sqlite`).

* **Seguridad Criptográfica:** HMAC-SHA256 (`hmac`, `hashlib`).

* **Orquestador Workflow & Webhooks:** [n8n](https://n8n.io/).

* **Servidor MCP / Backend Simulado:** FastMCP (Integración ERP/WMS para órdenes `PED-901` y facturas `INV-441`).

* **Contenedorización:** Docker & Docker Compose.

## Características Principales

1. **Investigación Autónoma con MCP Tools:**
   El agente consulta automáticamente el estado logístico del pedido (`consultar_pedido`) y la validez financiera de la factura (`verificar_factura`) mediante el protocolo FastMCP antes de tomar decisiones.

2. **Control de Riesgo Financiero (Human-in-the-Loop):**
   Cualquier compensación que supere los $500$ USD activa un freno determinista (`interrupt_before=["revision_humana"]`), congelando la sesión y evitando la ejecución no autorizada en la base de datos contable.

3. **Persistencia de Estado Duradera:**
   Uso de `SqliteSaver` (`checkpoints.db`) para congelar y reanudar sesiones. Las disputas pendientes de revisión humana sobreviven a reinicios de servidor o fallas eléctricas.

4. **Flujo de Respuesta Bivalente (Aprobación vs Rechazo):**

   * **Aprobación:** Reanuda el grafo, ejecuta `registrar_compensacion` y emite la nota de crédito (`COMP-XXXX`).

   * **Rechazo:** Desvía la ejecución omitiendo las herramientas financieras y utiliza a Gemini de forma aislada para redactar una carta de denegación cordial y justificada.

5. **Seguridad Criptográfica HMAC-SHA256:**
   Cada solicitud de aprobación genera un token HMAC firmado único para ese `thread_id`. Cualquier intento de manipulación en la URL o adivinación de parámetros devuelve un error `403 FORBIDDEN`.

## Estructura del Proyecto

```
.
├── mcp/
│   └── FastMCPServer.py             # Herramientas MCP y base de datos simulada del ERP/WMS
│       │
│       langgraph-agent/
│       ├── test/
│       │   └── test_flow.py          # Script de pruebas por consola para el flujo agéntico
│       ├── api.py                    # Servicio FastAPI con endpoints REST (/process y /resume) + HMAC
│       ├── Dockerfile                # Configuración de compilación para la API del agente
│       └── graph.py                  # Definición del grafo LangGraph, nodos, aristas y SqliteSaver
├── n8n/
│   └── MCP_Logistico_N8N.json        # Workflow exportado de n8n para orquestación y callbacks
├── .env                              # Variables de entorno del proyecto
├── .env.example                      # Plantilla con variables requeridas
├── .gitignore                        # Archivos excluidos de control de versiones
├── checkpoints.db                    # Base de datos SQLite para persistencia del grafo
├── compose.yml                       # Stack completo de Docker Compose
├── README.md                         # Documentación principal del proyecto
├── requirements.txt                  # Dependencias de Python
└── searxng-settings.yml              # Configuración del motor de búsqueda SearXNG

```

## Guía de Despliegue Rápido

### 1. Requisitos Previos

* Docker y Docker Compose instalados.

* Una API Key de Google Gemini ([Google AI Studio](https://aistudio.google.com/)).

### 2. Configurar Variables de Entorno

Crea un archivo `.env` en la raíz del proyecto:

```
GOOGLE_API_KEY=TU-API-KEY

HMAC_SECRET_KEY=TU-HMAC-KEY

N8N_VERSION=2.42.6
N8N_SANDBOX_VERSION=1.6.0
N8N_RUNNERS_AUTH_TOKEN=TU-AUTH-TOKEN-KEY

SANDBOX_API_KEYS=TU-API-KEY
SANDBOX_API_RUNNER_REGISTRATION_TOKEN=TU-TOKEN
SANDBOX_API_RUNNER_API_KEY=TU-API-KEY

N8N_SANDBOX_SERVICE_API_KEY=TU-API-KEY(DEBE SER LA MISMA QUE SANDBOX_API_KEYS)

SEARXNG_SECRET=TU-SECRET-CODE
N8N_INSTANCE_AI_SEARXNG_URL=http://searxng:8080

```

### 3. Levantar el Stack con Docker Compose

```
docker-compose up --build -d

```

Servicios desplegados:

* **FastAPI Microservice:** `http://localhost:8000` (Swagger UI en `/docs`).

* **n8n Orchestrator:** `http://localhost:5678`.

* **Mailpit (Servidor SMTP de prueba):** `http://localhost:8025`.

## Especificación de la API

### `POST /api/v1/incidents/process`

Inicia la auditoría del reclamo logístico.

* **Payload:**

  ```
  {
    "mensaje": "Hola, mi pedido PED-901 llegó con las cajas dañadas. Solicito reintegro de la factura INV-441 por 1200 USD.",
    "cliente_email": "carlos.m@empresa.com",
    "thread_id": "caso-demo-001"
  }
  
  ```

* **Respuesta (Caso** $> 500$ **USD - Requiere Aprobación):**

  ```
  {
    "status": "REQUIRES_APPROVAL",
    "thread_id": "caso-demo-001",
    "cliente_email": "carlos.m@empresa.com",
    "nodo_en_espera": "revision_humana",
    "accion_critica": {
      "nombre": "registrar_compensacion",
      "argumentos": { "monto": 1200, "order_id": "PED-901", "motivo": "Cajas dañadas..." }
    },
    "token": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "mensaje": "El monto excede el límite autónomo. Notificando a supervisión."
  }
  
  ```

### `POST /api/v1/incidents/{thread_id}/resume`

Reanuda la ejecución tras la intervención del supervisor.

* **Payload (Aprobación Legítima):**

  ```
  {
    "aprobado": true,
    "motivo": "Daño verificado en almacén",
    "token": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  }
  
  ```

* **Payload (Rechazo):**

  ```
  {
    "aprobado": false,
    "motivo": "No presentó evidencias fotográficas del empaque",
    "token": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  }
  
  ```

## Seguridad y Autenticación HMAC

Para prevenir ataques de manipulación de parámetros URL en los enlaces enviados a supervisores, la API requiere la firma HMAC-SHA256:

$$
\text{Token} = \text{HMAC-SHA256}(\text{HMAC\_SECRET\_KEY}, \text{"approve\_incident:"} + \text{thread\_id})
$$

La verificación se realiza en tiempo constante mediante `hmac.compare_digest` para mitigar ataques de temporización.