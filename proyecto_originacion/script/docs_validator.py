from google.cloud import storage
import requests
import json
import logging

class GCSFileValidator:
    def __init__(self, bucket_name, project_id):
        self.bucket_name = bucket_name
        self.storage_client = storage.Client(project=project_id)
        self.bucket = self.storage_client.bucket(bucket_name)
        
    def check_file_integrity(self, file_path):
        """Verificar integridad del archivo en GCS"""
        blob = self.bucket.blob(file_path)
        
        # Verificar si existe
        if not blob.exists():
            print(f"❌ Archivo no existe: {file_path}")
            return False
            
        # Obtener metadatos
        blob.reload()
        size = blob.size
        content_type = blob.content_type
        
        print(f"📄 Archivo: {file_path}")
        print(f"   Tamaño: {size} bytes")
        print(f"   Tipo: {content_type}")
        
        # Verificar tamaño
        if size == 0:
            print("   ⚠️ Archivo vacío")
            return False
        
        # Descargar primeros bytes para verificar
        start_bytes = blob.download_as_bytes(start=0, end=min(1024, size))
        
        # Verificar si es PDF
        if start_bytes.startswith(b'%PDF'):
            print("   ✅ Es un archivo PDF válido")
            return True
        
        # Verificar si es HTML (error)
        if start_bytes.startswith(b'<!DOCTYPE') or start_bytes.startswith(b'<html'):
            print("   ❌ Es HTML (probablemente una página de error)")
            # Intentar leer el contenido del error
            try:
                error_content = blob.download_as_text()
                print(f"   Contenido del error: {error_content[:200]}...")
            except:
                pass
            return False
        
        # Verificar si es JSON (error)
        try:
            error_json = json.loads(start_bytes)
            print(f"   ❌ Es JSON de error: {error_json}")
            return False
        except:
            pass
            
        print("   ⚠️ Formato desconocido")
        return False
    
    def validate_all_pdfs(self, prefix="inventario_documents/"):
        """Validar todos los PDFs en una carpeta"""
        blobs = self.bucket.list_blobs(prefix=prefix)
        
        total = 0
        valid = 0
        invalid = 0
        
        for blob in blobs:
            if blob.name.endswith('.pdf'):
                total += 1
                if self.check_file_integrity(blob.name):
                    valid += 1
                else:
                    invalid += 1
                print("-" * 50)
        
        print(f"\nResumen:")
        print(f"Total archivos PDF: {total}")
        print(f"Válidos: {valid}")
        print(f"Inválidos: {invalid}")
        
        return valid, invalid

# Función mejorada para descargar con validación
def download_with_validation(url, gcs_path, bucket, max_retries=3):
    """Descargar archivo con validación y reintentos"""
    
    for attempt in range(max_retries):
        try:
            # Descargar archivo
            response = requests.get(url, timeout=60, stream=True)
            
            # Verificar respuesta
            if response.status_code == 401:
                logging.error(f"❌ URL expirada (401): {url}")
                return False, "URL expirada"
            
            response.raise_for_status()
            
            # Verificar content-type
            content_type = response.headers.get('content-type', '')
            if 'application/pdf' not in content_type.lower():
                logging.warning(f"⚠️ Content-type no es PDF: {content_type}")
            
            # Descargar contenido
            content = response.content
            
            # Verificar que es PDF
            if not content.startswith(b'%PDF'):
                logging.error(f"❌ El contenido no es PDF válido")
                return False, "No es PDF"
            
            # Subir a GCS
            blob = bucket.blob(gcs_path)
            blob.upload_from_string(
                content,
                content_type='application/pdf'
            )
            
            logging.info(f"✅ Archivo subido correctamente: {gcs_path}")
            return True, "OK"
            
        except requests.exceptions.Timeout:
            logging.error(f"⏱️ Timeout en intento {attempt + 1}")
            if attempt == max_retries - 1:
                return False, "Timeout"
        except Exception as e:
            logging.error(f"❌ Error en intento {attempt + 1}: {e}")
            if attempt == max_retries - 1:
                return False, str(e)
    
    return False, "Máximo de reintentos alcanzado"

# Uso
if __name__ == "__main__":
    # Configuración
    PROJECT_ID = "proyecto-originacion"
    BUCKET_NAME = "inventario_documents"
    
    # Validar archivos existentes
    validator = GCSFileValidator(BUCKET_NAME, PROJECT_ID)
    validator.validate_all_pdfs()