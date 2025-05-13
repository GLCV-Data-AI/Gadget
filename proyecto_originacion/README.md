# Procesador de Documentos

Script para descargar documentos desde URLs almacenadas en BigQuery y cargarlos a Google Cloud Storage.

## Configuración

1. Crea un archivo `.env` en el directorio principal del proyecto con el siguiente contenido:

```
PROJECT_ID=proyecto-originacion
BUCKET_NAME=inventario_documents
DATASET_ID=raw_docs_inmueble
TABLE_ID=stg_docs_inmueble
MAX_WORKERS=10
BATCH_SIZE=500
```

2. Activa el entorno virtual e instala las dependencias:

```bash
# Activar el entorno virtual (Windows)
.venv\Scripts\activate

# Instalar dependencias
pip install -r requirements.txt
```

3. Asegúrate de tener las credenciales de Google Cloud configuradas:
   - Usar GOOGLE_APPLICATION_CREDENTIALS
   - O autenticarse con `gcloud auth application-default login`

## Estructura de la tabla BigQuery

El script espera una tabla en BigQuery con al menos los siguientes campos:

- `nid`: Identificador único del documento
- `business_inmueble_key`: Clave del inmueble
- `url_docs_sistem`: URL del documento a descargar
- `gcs_url`: Campo para almacenar la URL de GCS (puede estar vacío inicialmente)
- `updated_at`: Campo para el timestamp de actualización

## Ejecución

```bash
python script/descarga_documentos.py
```

## Flujo de trabajo

1. El script consulta documentos en BigQuery cuya URL no está vacía y que aún no tienen una URL de GCS.
2. Descarga cada documento utilizando la URL proporcionada.
3. Sube el documento a GCS, organizándolo por inmueble y documento.
4. Actualiza el registro en BigQuery con la URL de GCS y un timestamp.
5. Guarda los resultados de procesamiento en una tabla separada para análisis. 