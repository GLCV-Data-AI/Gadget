from google.cloud import storage
import logging
from datetime import datetime

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def fix_all_pdf_content_types(project_id, bucket_name):
    """Corregir content-type de TODOS los PDFs en el bucket"""
    
    storage_client = storage.Client(project=project_id)
    bucket = storage_client.bucket(bucket_name)
    
    fixed_count = 0
    total_pdfs = 0
    already_correct = 0
    
    logger.info(f"Iniciando corrección de Content-Type en bucket: {bucket_name}")
    start_time = datetime.now()
    
    # Iterar sobre TODOS los archivos
    for blob in bucket.list_blobs():
        if blob.name.endswith('.pdf'):
            total_pdfs += 1
            
            # Recargar metadata
            blob.reload()
            
            # Verificar content-type actual
            current_type = blob.content_type
            
            if current_type != 'application/pdf':
                logger.info(f"Corrigiendo: {blob.name} (tipo actual: {current_type})")
                
                # Actualizar content-type
                blob.content_type = 'application/pdf'
                blob.patch()
                
                fixed_count += 1
                
                # Log cada 100 archivos corregidos
                if fixed_count % 100 == 0:
                    logger.info(f"Progreso: {fixed_count} archivos corregidos...")
            else:
                already_correct += 1
                
            # Log cada 500 archivos procesados
            if total_pdfs % 500 == 0:
                logger.info(f"Procesados: {total_pdfs} archivos PDF...")
    
    end_time = datetime.now()
    duration = end_time - start_time
    
    logger.info(f"\n{'='*50}")
    logger.info(f"RESUMEN DE CORRECCIÓN")
    logger.info(f"{'='*50}")
    logger.info(f"Total PDFs procesados: {total_pdfs}")
    logger.info(f"Archivos corregidos: {fixed_count}")
    logger.info(f"Ya correctos: {already_correct}")
    logger.info(f"Tiempo total: {duration}")
    logger.info(f"{'='*50}")
    
    return fixed_count, total_pdfs

def verify_random_pdfs(project_id, bucket_name, sample_size=5):
    """Verificar algunos PDFs aleatorios después de la corrección"""
    
    storage_client = storage.Client(project=project_id)
    bucket = storage_client.bucket(bucket_name)
    
    logger.info(f"\nVerificando {sample_size} archivos PDF aleatorios...")
    
    count = 0
    for blob in bucket.list_blobs():
        if blob.name.endswith('.pdf') and count < sample_size:
            blob.reload()
            logger.info(f"Archivo: {blob.name}")
            logger.info(f"  Content-Type: {blob.content_type}")
            logger.info(f"  Tamaño: {blob.size:,} bytes")
            count += 1
            
            if blob.content_type != 'application/pdf':
                logger.warning(f"  ⚠️ TODAVÍA INCORRECTO!")

# Script principal
if __name__ == "__main__":
    PROJECT_ID = "proyecto-originacion"
    BUCKET_NAME = "inventario_documents"
    
    # Corregir todos los PDFs
    fixed, total = fix_all_pdf_content_types(PROJECT_ID, BUCKET_NAME)
    
    # Si se corrigieron archivos, verificar algunos
    if fixed > 0:
        verify_random_pdfs(PROJECT_ID, BUCKET_NAME)
    
    logger.info("\n✅ Proceso completado. Ahora deberías poder ver los PDFs en el navegador.")