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
import random

# Cargar variables de entorno
load_dotenv()

# Configuración
PROJECT_ID = os.getenv("PROJECT_ID", "proyecto-originacion")
BUCKET_NAME = os.getenv("BUCKET_NAME", "inventario_documents")
DATASET_ID = os.getenv("DATASET_ID", "raw_docs_inmueble")
TABLE_ID = os.getenv("TABLE_ID", "stg_docs_inmueble")  
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "5"))  
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "50"))  

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DocumentProcessor:
    def __init__(self):
        self.bq_client = bigquery.Client(project=PROJECT_ID)
        # Crear cliente de storage especificando el proyecto explícitamente
        self.storage_client = storage.Client(project=PROJECT_ID)
        
        # Obtener el bucket correctamente (sin crear subcarpetas)
        try:
            # Usar get_bucket en lugar de bucket para evitar problemas
            self.bucket = self.storage_client.get_bucket(BUCKET_NAME)
            logger.info(f"Bucket {BUCKET_NAME} obtenido exitosamente")
        except Exception as e:
            logger.error(f"Error obteniendo bucket {BUCKET_NAME}: {e}")
            raise
        
    def get_documents_from_bigquery(self, offset=0, limit=BATCH_SIZE):
        """Obtiene documentos desde BigQuery con paginación"""
        query = f"""
        SELECT 
            nid,
            business_inmueble_key,
            url_docs_sistem,
            docs_tipe  
        FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`
        WHERE url_docs_sistem IS NOT NULL
        AND url_docs_sistem != ''
        AND tipo_inventario IN ('En Inventario')
        AND (url_docs_gcs IS NULL OR url_docs_gcs = '')
        AND (gcs_url IS NULL OR gcs_url = '')
        LIMIT {limit}
        OFFSET {offset}
        """
        
        return list(self.bq_client.query(query))
    
    def download_document(self, url: str, max_retries: int = 3) -> bytes:
        """Descarga un documento con reintentos y validación"""
        for attempt in range(max_retries):
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                
                response = requests.get(url, timeout=60, allow_redirects=True, headers=headers)
                
                if response.status_code == 401:
                    raise Exception(f"URL expirada o no autorizada (401)")
                
                response.raise_for_status()
                content = response.content
                
                if len(content) < 100:
                    logger.warning(f"Archivo muy pequeño ({len(content)} bytes)")
                
                if content.startswith(b'<') or b'401 Unauthorized' in content[:1000]:
                    raise Exception(f"Se recibió HTML de error")
                
                logger.info(f"Documento descargado exitosamente: {len(content)} bytes")
                return content
                
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                logger.warning(f"Intento {attempt + 1} fallido: {e}")
                time.sleep(2 ** attempt)
                
    def get_file_extension(self, url: str, content: bytes) -> str:
        """Determina la extensión del archivo"""
        parsed_url = urlparse(url)
        path = parsed_url.path
        if '.' in path:
            ext = path.split('.')[-1].lower()
            if '?' in ext:
                ext = ext.split('?')[0]
            return ext
        
        if content.startswith(b'%PDF'):
            return 'pdf'
        elif content.startswith(b'\xff\xd8\xff'):
            return 'jpg'
        elif content.startswith(b'\x89PNG\r\n\x1a\n'):
            return 'png'
        
        return 'bin'
    
    def generate_filename(self, documento: dict, content: bytes) -> str:
        """Genera un nombre de archivo único"""
        extension = self.get_file_extension(documento['url_docs_sistem'], content)
        url_hash = hashlib.md5(documento['url_docs_sistem'].encode()).hexdigest()[:8]
        docs_tipe = documento.get('docs_tipe', 'documento')
        
        # Formato: docs_tipe_business_key_nid_hash.extension
        filename = f"{docs_tipe}_{documento['business_inmueble_key']}_{documento['nid']}_{url_hash}.{extension}"
        
        # Limpiar caracteres especiales
        filename = filename.replace(' ', '_').replace('/', '_').replace('\\', '_')
        
        return filename
    
    def upload_to_gcs(self, nid: str, business_key: str, filename: str, content: bytes) -> str:
        """Sube el documento a GCS con el content-type correcto"""
        # Solo nid/filename, sin carpetas adicionales
        blob_path = f"{nid}/{filename}"
        
        try:
            # Crear blob directamente en el bucket
            blob = self.bucket.blob(blob_path)
            
            # Configurar metadata
            metadata = {
                'nid': str(nid),
                'business_key': business_key,
                'uploaded_at': datetime.datetime.now().isoformat(),
                'content_length': str(len(content))
            }
            blob.metadata = metadata
            
            # IMPORTANTE: Determinar el content-type correcto basado en la extensión
            if filename.lower().endswith('.pdf'):
                content_type = 'application/pdf'
            elif filename.lower().endswith(('.jpg', '.jpeg')):
                content_type = 'image/jpeg'
            elif filename.lower().endswith('.png'):
                content_type = 'image/png'
            elif filename.lower().endswith('.doc'):
                content_type = 'application/msword'
            elif filename.lower().endswith('.docx'):
                content_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            else:
                content_type = 'application/octet-stream'
            
            # Subir el archivo con el content-type correcto
            logger.info(f"Subiendo archivo a: {blob_path} con content-type: {content_type}")
            blob.upload_from_string(content, content_type=content_type)
            
            # Verificar que se subió
            blob.reload()
            if blob.exists():
                gcs_url = f"gs://{BUCKET_NAME}/{blob_path}"
                logger.info(f"✅ Archivo subido exitosamente: {gcs_url}")
                logger.info(f"   Content-Type: {blob.content_type}")
                logger.info(f"   Tamaño: {blob.size} bytes")
                return gcs_url
            else:
                raise Exception("El archivo no se encontró después de subir")
                
        except Exception as e:
            logger.error(f"❌ Error subiendo archivo: {e}")
            raise
    
    def update_bigquery_record(self, nid: int, gcs_url: str, max_retries: int = 5) -> None:
        """Actualiza el registro en BigQuery con la URL de GCS"""
        
        for attempt in range(max_retries):
            try:
                query = f"""
                UPDATE `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`
                SET 
                    url_docs_gcs = @gcs_url,
                    gcs_url = @gcs_url
                WHERE nid = @nid
                """
                
                job_config = bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter("gcs_url", "STRING", gcs_url),
                        bigquery.ScalarQueryParameter("nid", "INT64", nid)
                    ]
                )
                
                query_job = self.bq_client.query(query, job_config=job_config)
                query_job.result()
                
                logger.info(f"BigQuery actualizado para nid {nid}")
                break
                
            except Exception as e:
                if "concurrent update" in str(e).lower() and attempt < max_retries - 1:
                    wait_time = (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(f"Error de concurrencia, reintentando en {wait_time:.2f}s...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Error actualizando BigQuery: {e}")
                    raise
    
    def process_document(self, documento: dict) -> Dict:
        """Procesa un documento individual"""
        result = {
            'nid': documento['nid'],
            'business_inmueble_key': documento['business_inmueble_key'],
            'url_original': documento['url_docs_sistem'],
            'docs_tipe': documento.get('docs_tipe', 'documento'),
            'success': False,
            'error': None,
            'url_docs_gcs': None,
            'processed_at': datetime.datetime.now().isoformat()
        }
        
        try:
            # Descargar documento
            content = self.download_document(documento['url_docs_sistem'])
            
            if len(content) == 0:
                raise Exception("Archivo vacío")
            
            # Generar nombre de archivo
            filename = self.generate_filename(documento, content)
            
            # Subir a GCS con content-type correcto
            gcs_url = self.upload_to_gcs(
                str(documento['nid']),
                documento['business_inmueble_key'],
                filename,
                content
            )
            
            # Actualizar BigQuery
            self.update_bigquery_record(documento['nid'], gcs_url)
            
            result['success'] = True
            result['url_docs_gcs'] = gcs_url
            
            logger.info(f"Documento procesado completamente: {documento['nid']}/{filename}")
                
        except Exception as e:
            result['error'] = str(e)
            logger.error(f"Error procesando documento: {e}")
        
        return result
    
    def process_batch(self, offset: int = 0) -> List[Dict]:
        """Procesa un batch de documentos"""
        documentos = self.get_documents_from_bigquery(offset=offset)
        
        if not documentos:
            return []
        
        logger.info(f"Procesando batch con {len(documentos)} documentos desde offset {offset}")
        
        results = []
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_doc = {
                executor.submit(self.process_document, {
                    'nid': doc.nid,
                    'business_inmueble_key': doc.business_inmueble_key,
                    'url_docs_sistem': doc.url_docs_sistem,
                    'docs_tipe': getattr(doc, 'docs_tipe', 'documento')
                }): doc 
                for doc in documentos
            }
            
            for future in as_completed(future_to_doc):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    logger.error(f"Error en future: {e}")
                    doc = future_to_doc[future]
                    results.append({
                        'nid': doc.nid,
                        'business_inmueble_key': doc.business_inmueble_key,
                        'url_original': doc.url_docs_sistem,
                        'success': False,
                        'error': str(e),
                        'processed_at': datetime.datetime.now().isoformat()
                    })
        
        time.sleep(2)
        return results
    
    def save_results_to_bigquery(self, results: List[Dict], table_suffix: str = "results"):
        """Guarda los resultados del procesamiento en BigQuery"""
        if not results:
            return
        
        table_id = f"{PROJECT_ID}.{DATASET_ID}.document_processing_{table_suffix}"
        
        table_schema = [
            bigquery.SchemaField("nid", "INTEGER"),
            bigquery.SchemaField("business_inmueble_key", "STRING"),
            bigquery.SchemaField("url_original", "STRING"),
            bigquery.SchemaField("docs_tipe", "STRING"),
            bigquery.SchemaField("success", "BOOLEAN"),
            bigquery.SchemaField("error", "STRING"),
            bigquery.SchemaField("url_docs_gcs", "STRING"),
            bigquery.SchemaField("processed_at", "TIMESTAMP"),
        ]
        
        table = bigquery.Table(table_id, schema=table_schema)
        table = self.bq_client.create_table(table, exists_ok=True)
        
        job_config = bigquery.LoadJobConfig(
            schema=table_schema,
            write_disposition="WRITE_APPEND"
        )
        
        job = self.bq_client.load_table_from_json(
            results,
            table_id,
            job_config=job_config
        )
        
        job.result()
        logger.info(f"Guardados {len(results)} resultados en {table_id}")
    
    def run_full_pipeline(self):
        """Ejecuta el pipeline completo"""
        offset = 0
        total_processed = 0
        total_success = 0
        total_failed = 0
        
        while True:
            try:
                results = self.process_batch(offset)
                
                if not results:
                    break
                
                batch_success = sum(1 for r in results if r['success'])
                batch_failed = sum(1 for r in results if not r['success'])
                
                total_processed += len(results)
                total_success += batch_success
                total_failed += batch_failed
                
                self.save_results_to_bigquery(results)
                
                logger.info(f"Batch completado: {batch_success} éxitos, {batch_failed} fallos")
                logger.info(f"Total acumulado: {total_success} éxitos, {total_failed} fallos")
                
                offset += BATCH_SIZE
                time.sleep(3)
                
            except Exception as e:
                logger.error(f"Error en batch: {e}")
                offset += BATCH_SIZE
                time.sleep(5)
        
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