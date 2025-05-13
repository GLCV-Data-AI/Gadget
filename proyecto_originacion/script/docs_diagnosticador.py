from google.cloud import storage
from google.cloud import bigquery
import requests
import os
import logging
from datetime import datetime

class PipefyGCSRepair:
    def __init__(self, project_id, bucket_name, dataset_id, table_id, pipefy_api_key):
        self.project_id = project_id
        self.bucket_name = bucket_name
        self.dataset_id = dataset_id
        self.table_id = table_id
        self.pipefy_api_key = pipefy_api_key
        
        # Clientes
        self.storage_client = storage.Client(project=project_id)
        self.bucket = self.storage_client.bucket(bucket_name)
        self.bq_client = bigquery.Client(project=project_id)
        
        # Configurar logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)
    
    def diagnose_bucket_files(self):
        """Diagnosticar archivos en el bucket"""
        blobs = self.bucket.list_blobs(prefix="inventario_documents/")
        
        report = {
            'total': 0,
            'valid_pdfs': 0,
            'empty_files': 0,
            'error_pages': 0,
            'unknown': 0,
            'details': []
        }
        
        for blob in blobs:
            if not blob.name.endswith('/'):  # Ignorar carpetas
                report['total'] += 1
                
                # Analizar archivo
                try:
                    # Obtener primeros bytes
                    content_sample = blob.download_as_bytes(start=0, end=1024)
                    
                    file_info = {
                        'name': blob.name,
                        'size': blob.size,
                        'type': 'unknown',
                        'valid': False
                    }
                    
                    if blob.size == 0:
                        file_info['type'] = 'empty'
                        report['empty_files'] += 1
                    elif content_sample.startswith(b'%PDF'):
                        file_info['type'] = 'pdf'
                        file_info['valid'] = True
                        report['valid_pdfs'] += 1
                    elif content_sample.startswith(b'<') or b'401' in content_sample:
                        file_info['type'] = 'error_page'
                        report['error_pages'] += 1
                    else:
                        report['unknown'] += 1
                    
                    report['details'].append(file_info)
                    
                except Exception as e:
                    self.logger.error(f"Error analizando {blob.name}: {e}")
        
        return report
    
    def get_fresh_url_from_pipefy(self, card_id, field_id):
        """Obtener URL actualizada desde Pipefy"""
        headers = {
            "Authorization": f"Bearer {self.pipefy_api_key}",
            "Content-Type": "application/json"
        }
        
        query = """
        query GetCardAttachments($cardId: ID!) {
            card(id: $cardId) {
                attachments {
                    url
                    name
                }
                fields {
                    name
                    value
                    field {
                        id
                        type
                    }
                }
            }
        }
        """
        
        try:
            response = requests.post(
                "https://api.pipefy.com/graphql",
                headers=headers,
                json={
                    "query": query,
                    "variables": {"cardId": str(card_id)}
                }
            )
            
            result = response.json()
            if 'errors' not in result:
                card = result['data']['card']
                
                # Buscar en campos
                for field in card.get('fields', []):
                    if field['field']['id'] == field_id and field['field']['type'] == 'attachment':
                        try:
                            files = json.loads(field['value'])
                            if files and len(files) > 0:
                                return files[0]['url']
                        except:
                            pass
                
                # Buscar en attachments
                for att in card.get('attachments', []):
                    return att['url']
            
        except Exception as e:
            self.logger.error(f"Error obteniendo URL fresca: {e}")
        
        return None
    
    def repair_invalid_files(self, dry_run=True):
        """Reparar archivos inválidos obteniendo nuevas URLs"""
        # Primero, diagnosticar
        report = self.diagnose_bucket_files()
        
        print(f"\n📊 Diagnóstico del bucket:")
        print(f"Total archivos: {report['total']}")
        print(f"PDFs válidos: {report['valid_pdfs']}")
        print(f"Archivos vacíos: {report['empty_files']}")
        print(f"Páginas de error: {report['error_pages']}")
        print(f"Desconocidos: {report['unknown']}")
        
        if dry_run:
            print("\n🔍 Modo DRY RUN - Solo mostrando lo que se haría")
        
        # Obtener información de BigQuery para archivos inválidos
        invalid_files = [f for f in report['details'] if not f['valid']]
        
        for file_info in invalid_files:
            try:
                # Extraer IDs del nombre del archivo
                parts = file_info['name'].split('/')
                if len(parts) >= 2:
                    filename_parts = parts[-1].split('_')
                    if len(filename_parts) >= 2:
                        card_id = filename_parts[0]
                        field_id = filename_parts[1]
                        
                        print(f"\n📄 Procesando: {file_info['name']}")
                        print(f"   Card ID: {card_id}, Field ID: {field_id}")
                        
                        if not dry_run:
                            # Obtener nueva URL
                            new_url = self.get_fresh_url_from_pipefy(card_id, field_id)
                            
                            if new_url:
                                print(f"   ✅ Nueva URL obtenida")
                                
                                # Descargar archivo correcto
                                response = requests.get(new_url, timeout=60)
                                if response.status_code == 200 and response.content.startswith(b'%PDF'):
                                    # Subir archivo correcto
                                    blob = self.bucket.blob(file_info['name'])
                                    blob.upload_from_string(
                                        response.content,
                                        content_type='application/pdf'
                                    )
                                    print(f"   ✅ Archivo reparado correctamente")
                                else:
                                    print(f"   ❌ La nueva URL tampoco es válida")
                            else:
                                print(f"   ❌ No se pudo obtener nueva URL")
                        else:
                            print(f"   [DRY RUN] Se obtendría nueva URL y se reemplazaría el archivo")
                
            except Exception as e:
                self.logger.error(f"Error procesando {file_info['name']}: {e}")
    
    def clean_error_files(self, dry_run=True):
        """Limpiar archivos que son páginas de error"""
        report = self.diagnose_bucket_files()
        error_files = [f for f in report['details'] if f['type'] == 'error_page']
        
        print(f"\n🗑️ Archivos de error encontrados: {len(error_files)}")
        
        for file_info in error_files:
            print(f"   {file_info['name']} ({file_info['size']} bytes)")
            
            if not dry_run:
                blob = self.bucket.blob(file_info['name'])
                blob.delete()
                print(f"   ✅ Eliminado")
            else:
                print(f"   [DRY RUN] Se eliminaría este archivo")

# Uso del script
if __name__ == "__main__":
    # Configuración
    PROJECT_ID = "tu-proyecto"
    BUCKET_NAME = "tu-bucket"
    DATASET_ID = "tu-dataset"
    TABLE_ID = "tu-tabla"
    PIPEFY_API_KEY = "tu-api-key"
    
    # Crear instancia
    repair = PipefyGCSRepair(
        PROJECT_ID,
        BUCKET_NAME,
        DATASET_ID,
        TABLE_ID,
        PIPEFY_API_KEY
    )
    
    # 1. Diagnosticar bucket
    print("=== DIAGNÓSTICO DEL BUCKET ===")
    report = repair.diagnose_bucket_files()
    
    # 2. Reparar archivos (primero en dry run)
    print("\n=== REPARACIÓN DE ARCHIVOS ===")
    repair.repair_invalid_files(dry_run=True)
    
    # 3. Si todo se ve bien, ejecutar reparación real
    # repair.repair_invalid_files(dry_run=False)
    
    # 4. Limpiar archivos de error
    # repair.clean_error_files(dry_run=False)