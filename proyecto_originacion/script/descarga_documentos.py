import os
import requests
import logging
import datetime
import hashlib
from google.cloud import storage
from google.cloud import bigquery
from urllib.parse import urlparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Tuple
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Configuración
PROJECT_ID = os.getenv("PROJECT_ID", "proyecto-originacion")
BUCKET_NAME = os.getenv("BUCKET_NAME", "inventario_documents")
DATASET_ID = os.getenv("DATASET_ID", "raw_docs_inmueble")
TABLE_ID = os.getenv("TABLE_ID", "stg_docs_inmueble")  # Tabla de BigQuery con las URLs
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "10"))  # Número de workers concurrentes
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "500"))  # Tamaño del batch para procesar

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DocumentProcessor:
    def __init__(self):
        self.bq_client = bigquery.Client(project=PROJECT_ID)
        self.storage_client = storage.Client()
        self.bucket = self.storage_client.bucket(BUCKET_NAME)
        
    def get_documents_from_bigquery(self, offset=0, limit=BATCH_SIZE):
        """Obtiene documentos desde BigQuery con paginación"""
        query = f"""
        SELECT 
            nid,
            business_inmueble_key,
            url_docs_sistem
        FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`
        WHERE url_docs_sistem IS NOT NULL
        LIMIT {limit}
        OFFSET {offset}
        """
        
        return list(self.bq_client.query(query))
    
    def download_document(self, url: str, max_retries: int = 3) -> bytes:
        """Descarga un documento con reintentos"""
        for attempt in range(max_retries):
            try:
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                return response.content
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                logger.warning(f"Intento {attempt + 1} fallido para {url}: {e}")
                time.sleep(2 ** attempt)  # Backoff exponencial
                
    def get_file_extension(self, url: str, content: bytes) -> str:
        """Determina la extensión del archivo basado en URL o contenido"""
        # Intentar obtener extensión de la URL
        parsed_url = urlparse(url)
        path = parsed_url.path
        if '.' in path:
            return path.split('.')[-1].lower()
        
        # Si no hay extensión en URL, inferir del contenido
        # PDF
        if content.startswith(b'%PDF'):
            return 'pdf'
        # JPEG
        if content.startswith(b'\xff\xd8\xff'):
            return 'jpg'
        # PNG
        if content.startswith(b'\x89PNG\r\n\x1a\n'):
            return 'png'
        
        return 'bin'  # Default binario
    
    def generate_filename(self, documento: dict, content: bytes) -> str:
        """Genera un nombre de archivo único para el documento"""
        extension = self.get_file_extension(documento['url_docs_sistem'], content)
        
        # Crear un hash corto del URL para evitar duplicados
        url_hash = hashlib.md5(documento['url_docs_sistem'].encode()).hexdigest()[:8]
        
        # Crear nombre de archivo con business_inmueble_key y nid
        filename = f"{documento['business_inmueble_key']}_{documento['nid']}_{url_hash}.{extension}"
        return filename
    
    def upload_to_gcs(self, nid: str, business_key: str, filename: str, content: bytes) -> str:
        """Sube el documento a Google Cloud Storage"""
        blob_name = f"{business_key}/{nid}/{filename}"
        blob = self.bucket.blob(blob_name)
        
        # Configurar metadata
        timestamp = datetime.datetime.now().isoformat()
        metadata = {
            'nid': nid,
            'business_key': business_key,
            'uploaded_at': timestamp,
            'content_length': str(len(content))
        }
        blob.metadata = metadata
        
        # Subir el archivo
        blob.upload_from_string(content)
        
        return f"gs://{BUCKET_NAME}/{blob_name}"
    
    def process_document(self, documento: dict) -> Dict:
        """Procesa un documento individual"""
        result = {
            'nid': documento['nid'],
            'business_inmueble_key': documento['business_inmueble_key'],
            'url_original': documento['url_docs_sistem'],
            'success': False,
            'error': None,
            'url_docs_gcs': None,
            'processed_at': datetime.datetime.now().isoformat()
        }
        
        try:
            # Descargar documento
            content = self.download_document(documento['url_docs_sistem'])
            
            # Generar nombre de archivo
            filename = self.generate_filename(documento, content)
            
            # Subir a GCS
            gcs_url = self.upload_to_gcs(
                str(documento['nid']),
                documento['business_inmueble_key'],
                filename,
                content
            )
            
            result['success'] = True
            result['url_docs_gcs'] = gcs_url
            
            # Actualizar la tabla con la URL de GCS
            self.update_bigquery_record(documento['nid'], gcs_url)
            
            logger.info(f"Documento procesado exitosamente: {documento['business_inmueble_key']}/{documento['nid']}/{filename}")
            
        except Exception as e:
            result['error'] = str(e)
            logger.error(f"Error procesando documento {documento['url_docs_sistem']}: {e}")
        
        return result
    
    def update_bigquery_record(self, nid: int, gcs_url: str) -> None:
        """Actualiza el registro en BigQuery con la URL de GCS"""
        query = f"""
        UPDATE `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`
        SET 
            url_docs_gcs = '{gcs_url}'
        WHERE nid = {nid}
        """
        
        self.bq_client.query(query).result()
    
    def process_batch(self, offset: int = 0) -> List[Dict]:
        """Procesa un batch de documentos"""
        documentos = self.get_documents_from_bigquery(offset=offset)
        
        if not documentos:
            return []
        
        logger.info(f"Procesando batch con {len(documentos)} documentos desde offset {offset}")
        
        results = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            # Enviar tareas al executor
            future_to_doc = {
                executor.submit(self.process_document, {
                    'nid': doc.nid,
                    'business_inmueble_key': doc.business_inmueble_key,
                    'url_docs_sistem': doc.url_docs_sistem
                }): doc 
                for doc in documentos
            }
            
            # Procesar resultados conforme se completan
            for future in as_completed(future_to_doc):
                result = future.result()
                results.append(result)
        
        return results
    
    def save_results_to_bigquery(self, results: List[Dict], table_suffix: str = "results"):
        """Guarda los resultados del procesamiento en BigQuery"""
        if not results:
            return
        
        table_id = f"{PROJECT_ID}.{DATASET_ID}.document_processing_{table_suffix}"
        
        job_config = bigquery.LoadJobConfig(
            autodetect=True,
            write_disposition="WRITE_APPEND"
        )
        
        job = self.bq_client.load_table_from_json(
            results,
            table_id,
            job_config=job_config
        )
        
        job.result()  # Esperar a que complete
        logger.info(f"Guardados {len(results)} resultados en {table_id}")
    
    def run_full_pipeline(self):
        """Ejecuta el pipeline completo"""
        offset = 0
        total_processed = 0
        total_success = 0
        total_failed = 0
        
        while True:
            # Procesar batch
            results = self.process_batch(offset)
            
            if not results:
                break
            
            # Contar éxitos y fallos
            batch_success = sum(1 for r in results if r['success'])
            batch_failed = sum(1 for r in results if not r['success'])
            
            total_processed += len(results)
            total_success += batch_success
            total_failed += batch_failed
            
            # Guardar resultados
            self.save_results_to_bigquery(results)
            
            logger.info(f"Batch completado: {batch_success} éxitos, {batch_failed} fallos")
            
            # Siguiente batch
            offset += BATCH_SIZE
            
            # Pequeña pausa entre batches
            time.sleep(1)
        
        logger.info(f"""
        Pipeline completado:
        - Total procesados: {total_processed}
        - Éxitos: {total_success}
        - Fallos: {total_failed}
        """)


def main():
    """Función principal"""
    processor = DocumentProcessor()
    
    try:
        processor.run_full_pipeline()
    except Exception as e:
        logger.error(f"Error en el pipeline: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main() 