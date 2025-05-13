-- Crear la tabla si no existe
CREATE TABLE IF NOT EXISTS `proyecto-originacion.raw_docs_inmueble.stg_docs_inmueble` (
  nid INTEGER NOT NULL,
  business_inmueble_key STRING NOT NULL,
  url_docs_sistem STRING,
  docs_tipe STRING,
  url_docs_gcs STRING,
  gcs_url STRING,
  updated_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
);

-- Agregar columnas si no existen
ALTER TABLE `proyecto-originacion.raw_docs_inmueble.stg_docs_inmueble`
ADD COLUMN IF NOT EXISTS gcs_url STRING,
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;

-- Crear tabla para resultados de procesamiento
CREATE TABLE IF NOT EXISTS `proyecto-originacion.raw_docs_inmueble.document_processing_results` (
  nid INTEGER,
  business_inmueble_key STRING,
  url_original STRING,
  success BOOLEAN,
  error STRING,
  gcs_url STRING,
  processed_at TIMESTAMP
); 