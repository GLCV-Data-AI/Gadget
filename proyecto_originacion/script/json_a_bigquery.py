import os
import json
import glob
from google.cloud import bigquery
from google.cloud import storage
import pandas as pd
from datetime import datetime
import logging
import re
import tempfile

# Configuración de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Configuración explícita del proyecto
os.environ["GOOGLE_CLOUD_PROJECT"] = "proyecto-originacion"

# Parámetros de configuración
PROJECT_ID = "proyecto-originacion"
BUCKET_PROCESADO = "cliente-docs-procesado"
DATASET_ID = "cedulas_colombia"
TABLE_ID = "datos_cedulas"
SCHEMA = [
    bigquery.SchemaField("cedula", "STRING"),
    bigquery.SchemaField("nombres", "STRING"),
    bigquery.SchemaField("apellidos", "STRING"),
    bigquery.SchemaField("fecha_nacimiento", "STRING"),  # Cambiado de DATE a STRING
    bigquery.SchemaField("fecha_expedicion", "STRING"),  # Cambiado de DATE a STRING
    bigquery.SchemaField("genero", "STRING"),
    bigquery.SchemaField("lugar_nacimiento", "STRING"),
    bigquery.SchemaField("lugar_expedicion", "STRING"),
    bigquery.SchemaField("estatura", "STRING"),  # Cambiado para manejar valores como "1.76"
    bigquery.SchemaField("rh", "STRING"),
    bigquery.SchemaField("nombre_archivo", "STRING"),
    bigquery.SchemaField("procesado_fecha", "TIMESTAMP"),
]

# Dirección local para guardar temporalmente los archivos
TEMP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "temp")

def descargar_jsons_de_bucket():
    """Descarga todos los archivos JSON procesados del bucket a una carpeta temporal."""
    storage_client = storage.Client(project=PROJECT_ID)
    bucket = storage_client.bucket(BUCKET_PROCESADO)
    
    logging.info(f"Buscando archivos JSON en gs://{BUCKET_PROCESADO}/...")
    
    # Crear directorio temporal si no existe
    os.makedirs(TEMP_DIR, exist_ok=True)
    
    # Lista para almacenar las rutas de los archivos descargados
    archivos_descargados = []
    
    # Recorrer el bucket recursivamente
    for blob in bucket.list_blobs():
        if blob.name.endswith('.json'):
            logging.info(f"Encontrado archivo JSON: {blob.name}")
            # Ruta local donde se guardará el archivo
            ruta_local = os.path.join(TEMP_DIR, os.path.basename(blob.name))
            # Descargar archivo
            blob.download_to_filename(ruta_local)
            archivos_descargados.append(ruta_local)
            logging.info(f"Descargado: {ruta_local}")
    
    logging.info(f"Total de archivos JSON descargados: {len(archivos_descargados)}")
    return archivos_descargados

def extraer_campos_cedula(ruta_json):
    """Extrae los campos relevantes de un JSON de Document AI."""
    with open(ruta_json, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Inicializar diccionario de resultados
    resultado = {
        "cedula": "",
        "nombres": "",
        "apellidos": "",
        "fecha_nacimiento": "",
        "fecha_expedicion": "",
        "genero": "",
        "lugar_nacimiento": "",
        "lugar_expedicion": "",
        "estatura": "",
        "rh": "",
        "nombre_archivo": os.path.basename(ruta_json),
        "procesado_fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # Estructura alternativa - entidades en el nivel superior
    if 'entities' in data:
        entidades = data['entities']
        
        # Recorrer todas las entidades y mapear a nuestros campos
        for entidad in entidades:
            # Asegurarse de que la entidad tiene un tipo y un valor
            if 'type' in entidad and 'mentionText' in entidad:
                tipo = entidad['type'].lower()
                valor = entidad.get('mentionText', '')
                
                # Mapear tipos de entidades a nuestros campos
                if tipo == 'cedula':
                    resultado['cedula'] = str(valor)
                elif tipo == 'nombres':
                    resultado['nombres'] = valor
                elif tipo == 'apellidos':
                    resultado['apellidos'] = valor
                elif tipo == 'fecha_nacimiento':
                    resultado['fecha_nacimiento'] = valor  # Guardar como string
                elif tipo == 'fecha_expedicion':
                    resultado['fecha_expedicion'] = valor  # Guardar como string
                elif tipo == 'genero':
                    resultado['genero'] = valor
                elif tipo == 'lugar_nacimiento' or tipo == 'lugar_naciminto':
                    resultado['lugar_nacimiento'] = valor
                elif tipo == 'lugar_expedicion':
                    resultado['lugar_expedicion'] = valor
                elif tipo == 'estatura':
                    resultado['estatura'] = str(valor)  # Convertir a string
                elif tipo == 'rh':
                    resultado['rh'] = valor
    
    # Estructura original - entidades dentro de document
    elif 'document' in data and 'entities' in data['document']:
        entidades = data['document']['entities']
        
        # Recorrer todas las entidades y mapear a nuestros campos
        for entidad in entidades:
            # Asegurarse de que la entidad tiene un tipo y un valor normalizado
            if 'type' in entidad:
                tipo = entidad['type'].lower()
                # Intentar diferentes campos donde puede estar el valor
                valor = None
                if 'normalizedValue' in entidad and 'text' in entidad['normalizedValue']:
                    valor = entidad['normalizedValue']['text']
                elif 'text' in entidad:
                    valor = entidad['text']
                elif 'mentionText' in entidad:
                    valor = entidad['mentionText']
                
                if valor is None:
                    continue
                
                # Mapear tipos de entidades a nuestros campos
                if tipo == 'cedula':
                    # Asegurar que la cédula es una cadena de texto
                    resultado['cedula'] = str(valor).strip()
                elif tipo == 'nombres':
                    resultado['nombres'] = valor
                elif tipo == 'apellidos':
                    resultado['apellidos'] = valor
                elif tipo == 'fecha_nacimiento':
                    # Ya no intentamos parsear como fecha, guardamos como string
                    resultado['fecha_nacimiento'] = valor
                elif tipo == 'fecha_expedicion':
                    # Ya no intentamos parsear como fecha, guardamos como string
                    resultado['fecha_expedicion'] = valor
                elif tipo == 'genero':
                    resultado['genero'] = valor
                elif tipo == 'lugar_nacimiento' or tipo == 'lugar_naciminto':
                    resultado['lugar_nacimiento'] = valor
                elif tipo == 'lugar_expedicion':
                    resultado['lugar_expedicion'] = valor
                elif tipo == 'estatura':
                    # Asegurar que la estatura es una cadena de texto
                    resultado['estatura'] = str(valor).strip()
                elif tipo == 'rh':
                    resultado['rh'] = valor
    
    # Preprocesamiento adicional
    # Limpiar cédula (eliminar puntos)
    if resultado['cedula']:
        resultado['cedula'] = resultado['cedula'].replace('.', '').replace(',', '')
    
    # Extraer lugar de expedición de la fecha si está combinado
    if resultado['fecha_expedicion'] and ' ' in resultado['fecha_expedicion'] and not resultado['lugar_expedicion']:
        partes = resultado['fecha_expedicion'].split(' ')
        if len(partes) > 1:
            # Asumir que la primera parte es la fecha y el resto es el lugar
            resultado['fecha_expedicion'] = partes[0]
            resultado['lugar_expedicion'] = ' '.join(partes[1:])
    
    # Asegurar que ningún valor sea None (convertir a string vacío si es None)
    for key in resultado:
        if resultado[key] is None:
            resultado[key] = ""
    
    return resultado

def cargar_a_bigquery(registros):
    """Carga los registros a BigQuery desde un archivo JSON temporal."""
    if not registros:
        logging.warning("No hay registros para cargar a BigQuery.")
        return
    
    # Crear cliente BigQuery
    client = bigquery.Client(project=PROJECT_ID)
    
    # Verificar si existe el dataset
    try:
        dataset_ref = client.dataset(DATASET_ID)
        client.get_dataset(dataset_ref)
        logging.info(f"Dataset {DATASET_ID} ya existe.")
    except Exception:
        # Crear dataset si no existe
        dataset = bigquery.Dataset(f"{PROJECT_ID}.{DATASET_ID}")
        dataset.location = "us"
        dataset = client.create_dataset(dataset)
        logging.info(f"Dataset {DATASET_ID} creado.")
    
    # Referencia a la tabla
    tabla_ref = dataset_ref.table(TABLE_ID)
    
    # Preguntar al usuario si quiere eliminar la tabla existente
    try:
        tabla_existente = client.get_table(tabla_ref)
        logging.info(f"La tabla {TABLE_ID} ya existe con esquema:")
        for campo in tabla_existente.schema:
            logging.info(f"  - {campo.name}: {campo.field_type}")
        
        respuesta = input("La tabla ya existe. ¿Deseas eliminarla y crear una nueva? (s/n): ")
        if respuesta.lower() == 's':
            client.delete_table(tabla_ref)
            logging.info(f"Tabla {TABLE_ID} eliminada.")
            
            # Crear tabla con nuevo esquema
            tabla = bigquery.Table(tabla_ref, schema=SCHEMA)
            tabla = client.create_table(tabla)
            logging.info(f"Tabla {TABLE_ID} creada con nuevo esquema.")
        else:
            logging.info("Se usará la tabla existente. Asegúrate de que los datos sean compatibles.")
    except Exception:
        # Crear tabla si no existe
        tabla = bigquery.Table(tabla_ref, schema=SCHEMA)
        tabla = client.create_table(tabla)
        logging.info(f"Tabla {TABLE_ID} creada.")
    
    # Crear un archivo JSON temporal
    fd, temp_path = tempfile.mkstemp(suffix='.json')
    try:
        with os.fdopen(fd, 'w') as temp_file:
            for registro in registros:
                # Escribir cada registro como una línea JSON (newline-delimited JSON)
                temp_file.write(json.dumps(registro) + '\n')
        
        # Configurar opciones de carga
        job_config = bigquery.LoadJobConfig(
            schema=SCHEMA,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        )
        
        # Abrir el archivo en modo binario para cargarlo
        with open(temp_path, "rb") as source_file:
            # Iniciar el trabajo de carga
            job = client.load_table_from_file(
                source_file, tabla_ref, job_config=job_config
            )
            
            # Esperar a que complete el trabajo
            job.result()
        
        logging.info(f"Cargados {len(registros)} registros a {PROJECT_ID}.{DATASET_ID}.{TABLE_ID}")
    
    except Exception as e:
        logging.error(f"Error al cargar datos a BigQuery: {e}")
        raise
    
    finally:
        # Eliminar el archivo temporal
        try:
            os.remove(temp_path)
        except:
            pass

def procesar_archivo_local(ruta_json):
    """Procesa un único archivo JSON local."""
    try:
        registro = extraer_campos_cedula(ruta_json)
        logging.info(f"Procesado archivo local: {ruta_json}")
        return registro
    except Exception as e:
        logging.error(f"Error procesando archivo local {ruta_json}: {e}")
        return None

def main():
    """Función principal."""
    logging.info("Iniciando procesamiento de documentos JSON a BigQuery...")
    
    # Comprobar si hay un archivo específico para procesar
    archivo_muestra = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "muestra.json")
    if os.path.exists(archivo_muestra):
        # Procesar archivo de muestra
        logging.info(f"Encontrado archivo de muestra: {archivo_muestra}")
        registro = procesar_archivo_local(archivo_muestra)
        if registro:
            logging.info("Datos extraídos del archivo de muestra:")
            for k, v in registro.items():
                if k != "procesado_fecha":
                    logging.info(f"  - {k}: {v}")
            
            # Preguntar si cargar a BigQuery
            respuesta = input("¿Deseas cargar esta muestra a BigQuery? (s/n): ")
            if respuesta.lower() == 's':
                cargar_a_bigquery([registro])
    
    # Proceder con el procesamiento normal
    respuesta = input("¿Deseas procesar todos los archivos del bucket? (s/n): ")
    if respuesta.lower() != 's':
        logging.info("Procesamiento de bucket cancelado por el usuario.")
        return
    
    # Paso 1: Descargar archivos JSON del bucket
    archivos_descargados = descargar_jsons_de_bucket()
    
    if not archivos_descargados:
        logging.warning("No se encontraron archivos JSON para procesar.")
        return
    
    # Paso 2: Procesar cada archivo JSON
    registros = []
    for archivo in archivos_descargados:
        try:
            registro = extraer_campos_cedula(archivo)
            registros.append(registro)
        except Exception as e:
            logging.error(f"Error procesando {archivo}: {e}")
    
    # Paso 3: Cargar datos a BigQuery
    cargar_a_bigquery(registros)
    
    # Paso 4: Limpiar archivos temporales (opcional)
    for archivo in archivos_descargados:
        try:
            os.remove(archivo)
        except Exception as e:
            logging.warning(f"No se pudo eliminar archivo temporal {archivo}: {e}")
    
    logging.info("Procesamiento completado.")

if __name__ == "__main__":
    main() 