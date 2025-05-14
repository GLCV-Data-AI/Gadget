from google.cloud import documentai_v1 as documentai
from google.cloud.documentai_v1.types import BatchProcessRequest
from google.cloud.documentai_v1.types import GcsDocument, GcsDocuments, BatchDocumentsInputConfig
from google.cloud import storage
import mimetypes
import datetime
import time
import os

# Configurar explícitamente el proyecto para este script
# Esto no afectará la configuración global de gcloud
os.environ["GOOGLE_CLOUD_PROJECT"] = "proyecto-originacion"

PROJECT_ID = "proyecto-originacion"
LOCATION = "us"
PROCESSOR_ID = "e373090f1de98aaa"
INPUT_BUCKET = "cliente-docs"
OUTPUT_BUCKET = "cliente-docs-procesado"
# 991 documentos necesitarán un timeout mayor
TIMEOUT_SEGUNDOS = 1800  # 30 minutos

# Formatos de archivo compatibles con Document AI
FORMATOS_COMPATIBLES = [
    ".pdf", ".jpeg", ".jpg", ".png"
]

def get_mime_type(filename):
    """Determina el tipo MIME basado en la extensión del archivo."""
    ext = filename.lower().split('.')[-1]
    if ext == "pdf":
        return "application/pdf"
    elif ext in ["jpeg", "jpg"]:
        return "image/jpeg"
    elif ext == "png":
        return "image/png"
    else:
        return "application/octet-stream"

def mostrar_tiempo_estimado(num_documentos):
    """Muestra un tiempo estimado de procesamiento basado en el número de documentos."""
    # Estimación aproximada: ~3 segundos por documento en promedio
    segundos_estimados = num_documentos * 3
    tiempo_estimado = datetime.timedelta(seconds=segundos_estimados)
    return tiempo_estimado

# Ruta del procesador
processor_name = f"projects/{PROJECT_ID}/locations/{LOCATION}/processors/{PROCESSOR_ID}"

# Inicializar cliente especificando explícitamente el proyecto y endpoint
client = documentai.DocumentProcessorServiceClient(
    client_options={"api_endpoint": f"{LOCATION}-documentai.googleapis.com"}
)

print(f"🔍 Escaneando bucket '{INPUT_BUCKET}' en busca de documentos...")
inicio_tiempo = time.time()

# Obtener lista de archivos del bucket de entrada usando el proyecto específico
storage_client = storage.Client(project=PROJECT_ID)
blobs = storage_client.bucket(INPUT_BUCKET).list_blobs()

# Filtrar archivos por formatos compatibles
documentos_a_procesar = []
for blob in blobs:
    # Verificar si el archivo tiene una extensión compatible
    if any(blob.name.lower().endswith(ext) for ext in FORMATOS_COMPATIBLES):
        mime_type = get_mime_type(blob.name)
        documentos_a_procesar.append(
            GcsDocument(gcs_uri=f"gs://{INPUT_BUCKET}/{blob.name}", mime_type=mime_type)
        )

# Verificar si hay documentos para procesar
if not documentos_a_procesar:
    print("⚠️ No se encontraron documentos en formatos compatibles para procesar.")
    exit(0)

# Mostrar resumen de documentos
total_docs = len(documentos_a_procesar)
print(f"📊 Resumen de documentos a procesar:")
print(f"   - Total: {total_docs} documentos")
print(f"   - Proyecto: {PROJECT_ID}")

# Contar por tipo
tipos = {}
for doc in documentos_a_procesar:
    mime = doc.mime_type
    tipos[mime] = tipos.get(mime, 0) + 1

for mime, cantidad in tipos.items():
    print(f"   - {mime}: {cantidad} archivos")

# Mostrar estimación de tiempo
tiempo_est = mostrar_tiempo_estimado(total_docs)
print(f"⏱️ Tiempo estimado de procesamiento: {tiempo_est}")
print(f"⚙️ Timeout configurado: {datetime.timedelta(seconds=TIMEOUT_SEGUNDOS)}")

# Crear input config
gcs_documents = GcsDocuments(documents=documentos_a_procesar)
input_config = BatchDocumentsInputConfig(gcs_documents=gcs_documents)

# Crear request
request = BatchProcessRequest(
    name=processor_name,
    input_documents=input_config,
    document_output_config={
        "gcs_output_config": {
            "gcs_uri": f"gs://{OUTPUT_BUCKET}/"
        }
    }
)

# Ejecutar procesamiento
print("\n🚀 Iniciando procesamiento por lotes...")
print(f"   Hora de inicio: {datetime.datetime.now().strftime('%H:%M:%S')}")
operation = client.batch_process_documents(request=request)

print("⏳ Procesando documentos... (esto puede tardar varios minutos)")
print("   Puedes monitorear el progreso en la consola de Google Cloud Platform.")
print("   El proceso continuará en segundo plano incluso si este script termina.")

try:
    # Esperar a que termine la operación
    operation.result(timeout=TIMEOUT_SEGUNDOS)
    tiempo_total = time.time() - inicio_tiempo
    print(f"✅ Procesamiento completado en {tiempo_total:.1f} segundos")
    print(f"   ({tiempo_total/60:.1f} minutos)")
    print(f"📁 Documentos procesados y guardados en gs://{OUTPUT_BUCKET}/")
except Exception as e:
    print(f"⚠️ La operación está en progreso, pero el script ha excedido el tiempo de espera: {e}")
    print(f"   La operación de Document AI continuará en segundo plano.")
    print(f"   ID de la operación: {operation.operation.name}")
    print(f"   Puedes verificar el estado en la consola de Google Cloud Platform.")
    print(f"   Los resultados se guardarán en gs://{OUTPUT_BUCKET}/ cuando termine.") 