#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Script para cargar documentos desde una carpeta local al bucket de GCS cliente-docs.
Este script prioriza archivos PDF sobre JPEG cuando hay duplicados y solo carga 
archivos sin sufijos (_1, _2, etc).
"""

import os
import re
from typing import Dict, List, Tuple
from google.cloud import storage
import logging

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constantes
ORIGEN_DIR = r"C:\Users\HABI\GLCV-DATAAI\Gadget\cedula_pdf_scan\data"
BUCKET_NOMBRE = "cliente-docs"
PROYECTO = "proyecto-originacion"  # Asumiendo el nombre del proyecto basado en la URL

def obtener_archivos_filtrados() -> Dict[str, str]:
    """
    Obtiene una lista de archivos filtrados según los requisitos.
    
    Returns:
        Dict[str, str]: Diccionario con ID como clave y ruta de archivo como valor
    """
    archivos = os.listdir(ORIGEN_DIR)
    logger.info(f"Se encontraron {len(archivos)} archivos en el directorio origen")
    
    # Patrón para extraer el ID base y el sufijo
    patron = re.compile(r"^(\d+)(?:_(\d+))?\.(\w+)$")
    
    # Agrupar archivos por ID base
    archivos_por_id: Dict[str, List[Tuple[str, str, str]]] = {}
    
    for archivo in archivos:
        coincidencia = patron.match(archivo)
        if coincidencia:
            id_base, sufijo, extension = coincidencia.groups()
            if id_base not in archivos_por_id:
                archivos_por_id[id_base] = []
            archivos_por_id[id_base].append((archivo, sufijo, extension))
    
    # Seleccionar el mejor archivo para cada ID
    archivos_seleccionados = {}
    
    for id_base, variantes in archivos_por_id.items():
        # Primero intentamos encontrar un archivo sin sufijo
        archivo_sin_sufijo = None
        archivo_pdf_sin_sufijo = None
        
        for nombre, sufijo, extension in variantes:
            if sufijo is None:  # Sin sufijo
                if extension.lower() == "pdf":
                    archivo_pdf_sin_sufijo = nombre
                else:
                    archivo_sin_sufijo = nombre
        
        # Priorizar PDF sin sufijo, luego cualquier archivo sin sufijo
        if archivo_pdf_sin_sufijo:
            archivos_seleccionados[id_base] = archivo_pdf_sin_sufijo
        elif archivo_sin_sufijo:
            archivos_seleccionados[id_base] = archivo_sin_sufijo
    
    logger.info(f"Se seleccionaron {len(archivos_seleccionados)} archivos únicos para cargar")
    return {id_base: os.path.join(ORIGEN_DIR, archivo) for id_base, archivo in archivos_seleccionados.items()}

def cargar_a_bucket(archivos: Dict[str, str]) -> None:
    """
    Carga los archivos seleccionados al bucket de GCS.
    
    Args:
        archivos (Dict[str, str]): Diccionario con ID como clave y ruta de archivo como valor
    """
    cliente = storage.Client(project=PROYECTO)
    bucket = cliente.bucket(BUCKET_NOMBRE)
    
    logger.info(f"Conectando al bucket {BUCKET_NOMBRE}")
    
    for id_base, ruta_archivo in archivos.items():
        nombre_archivo = os.path.basename(ruta_archivo)
        blob = bucket.blob(nombre_archivo)
        
        try:
            blob.upload_from_filename(ruta_archivo)
            logger.info(f"✅ Archivo {nombre_archivo} cargado exitosamente")
        except Exception as e:
            logger.error(f"❌ Error al cargar {nombre_archivo}: {str(e)}")

def main() -> None:
    """Función principal que ejecuta el proceso de carga"""
    logger.info("Iniciando el proceso de carga de documentos al bucket")
    
    try:
        archivos = obtener_archivos_filtrados()
        
        if not archivos:
            logger.warning("No se encontraron archivos que cumplan con los criterios")
            return
        
        cargar_a_bucket(archivos)
        logger.info("Proceso de carga completado")
    except Exception as e:
        logger.error(f"Error en el proceso: {str(e)}")

if __name__ == "__main__":
    main()