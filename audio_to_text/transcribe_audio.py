"""
Gadget para transcribir archivos de audio a texto usando OpenAI Whisper.

Convierte archivos de audio de varios formatos a WAV y luego los transcribe,
guardando la transcripción y la información de segmentos si está disponible.
"""

import argparse
import os
import tempfile
from pathlib import Path
from typing import Dict, Optional, Tuple, Any

import openai
from dotenv import load_dotenv
from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError
import math # Necesario para calcular chunks
import torch # Añadido para pyannote
from pyannote.audio import Pipeline # Añadido para diarización
from itertools import groupby # Para agrupar segmentos del mismo hablante
import operator # Para groupby

# --- Configuración Inicial ---

# Límite de tamaño de archivo para la API de Whisper (en bytes)
# Lo ponemos un poco por debajo de 25MB para seguridad
WHISPER_API_LIMIT_BYTES = 24 * 1024 * 1024

# Cargar variables de entorno (buscará un archivo .env)
load_dotenv()

# Configurar el cliente de OpenAI (asegúrate de tener OPENAI_API_KEY en tu .env)
try:
    client = openai.OpenAI()  # La API key se toma de la variable de entorno OPENAI_API_KEY
except openai.OpenAIError as e:
    print(f"❌ Error al inicializar el cliente de OpenAI: {e}")
    print("Asegúrate de que la variable de entorno OPENAI_API_KEY está configurada correctamente en un archivo .env")
    exit(1) # Salir si no se puede configurar el cliente

# Pipeline de Diarización pyannote.audio
# Necesita un token de Hugging Face en la variable de entorno HF_TOKEN
hf_token = os.getenv("HF_TOKEN")
if not hf_token:
    print("⚠️ Advertencia: Variable de entorno HF_TOKEN no encontrada.")
    print("La descarga del modelo de diarización podría fallar si es privado o requiere aceptación de términos.")
    print("Consigue un token en https://huggingface.co/settings/tokens")
    # Podríamos decidir salir aquí si el token es estrictamente necesario
    # exit(1)
di_pipeline = None
try:
    # Usar GPU si está disponible, si no CPU
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"🤖 Inicializando pipeline de diarización en dispositivo: {device}...")
    # Cambiar al modelo del ejemplo del usuario
    di_pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization", use_auth_token=hf_token)
    di_pipeline.to(device)
    print("✅ Pipeline de diarización inicializado.")
except Exception as e:
    print(f"❌ Error al inicializar el pipeline de diarización: {e}")
    print("Asegúrate de tener conexión a internet y el token HF_TOKEN configurado si es necesario.")
    # Decidir si continuar sin diarización o salir
    # exit(1)


# --- Funciones Auxiliares ---

def convertir_a_wav(ruta_audio_original: Path, dir_temporal: Path) -> Optional[Path]:
    """Convierte un archivo de audio a formato WAV.

    Args:
        ruta_audio_original: Ruta al archivo de audio original.
        dir_temporal: Directorio temporal para guardar el archivo WAV.

    Returns:
        Ruta al archivo WAV convertido o None si hay un error.
    """
    nombre_wav = ruta_audio_original.stem + ".wav"
    ruta_wav_salida = dir_temporal / nombre_wav

    try:
        print(f"⏳ Convirtiendo {ruta_audio_original.name} a WAV...")
        audio = AudioSegment.from_file(ruta_audio_original)
        # Exportar como WAV mono a 16kHz (recomendado para Whisper)
        audio.set_channels(1).set_frame_rate(16000).export(ruta_wav_salida, format="wav")
        print(f"✅ Convertido a WAV: {ruta_wav_salida}")
        return ruta_wav_salida
    except CouldntDecodeError:
        print(f"⚠️ Error al decodificar {ruta_audio_original.name}. ¿Formato no soportado por pydub/ffmpeg?")
        return None
    except FileNotFoundError:
        # pydub depende de ffmpeg, asegurarse que esté instalado y en el PATH
        print(f"❌ Error: ffmpeg no encontrado. Asegúrate de que ffmpeg esté instalado y accesible en el PATH del sistema.")
        return None
    except Exception as e:
        print(f"❌ Error inesperado durante la conversión de {ruta_audio_original.name}: {e}")
        return None

# Función para transcribir un archivo WAV (puede ser un chunk o un turno de hablante)
# Ahora también necesita saber si debe dividir por tamaño.
def _transcribir_wav_con_chunking_opcional(
    ruta_archivo_wav: Path,
    dir_temporal_chunks: Path,
    forzar_chunking: bool = False
) -> Optional[Dict[str, Any]]:
    """Transcribe un archivo WAV, dividiéndolo en chunks si es necesario o si se fuerza.

    Usado tanto para archivos completos como para segmentos de hablante.

    Args:
        ruta_archivo_wav: Ruta al archivo WAV a transcribir.
        dir_temporal_chunks: Directorio para chunks si son necesarios.
        forzar_chunking: Si es True, siempre intentará dividir (útil si la entrada ya es grande).

    Returns:
        Diccionario combinado con la transcripción y detalles, o None si falla.
    """
    file_size = ruta_archivo_wav.stat().st_size
    print(f"     Tamaño a transcribir: {file_size / (1024*1024):.2f} MB")

    # Transcribir directamente si es pequeño y no se fuerza el chunking
    if not forzar_chunking and file_size <= WHISPER_API_LIMIT_BYTES:
        print(f"     🗣️ Transcribiendo directamente (por debajo del límite)...")
        return _transcribir_chunk_whisper(ruta_archivo_wav)

    # --- Lógica de Chunking (si es grande o se fuerza) ---
    print(f"     ⚠️ Realizando chunking (tamaño {file_size / (1024*1024):.2f} MB supera límite o forzado)...")
    try:
        audio = AudioSegment.from_wav(ruta_archivo_wav)
    except Exception as e:
        print(f"     ❌ Error al cargar WAV para chunking {ruta_archivo_wav.name}: {e}")
        return None

    total_duration_ms = len(audio)
    # Si forzamos chunking en un archivo pequeño, hacemos un solo chunk
    num_chunks = 1
    if file_size > WHISPER_API_LIMIT_BYTES:
         num_chunks = math.ceil(file_size / WHISPER_API_LIMIT_BYTES)

    chunk_duration_ms = math.floor(total_duration_ms / num_chunks)
    # Evitar chunks de duración 0 si el archivo es muy corto y se fuerza chunking
    if chunk_duration_ms == 0 and num_chunks == 1:
        chunk_duration_ms = total_duration_ms

    if chunk_duration_ms <= 0:
         print(f"     ⚠️ Duración de chunk calculada inválida ({chunk_duration_ms}ms), saltando transcripción.")
         return None

    print(f"     Dividiendo en {num_chunks} chunks de ~{chunk_duration_ms / 1000:.1f} segundos c/u...")

    all_text = ""
    all_segments = []
    last_successful_lang = 'unknown'

    for i in range(num_chunks):
        start_ms = i * chunk_duration_ms
        end_ms = (i + 1) * chunk_duration_ms if i < num_chunks - 1 else total_duration_ms
        # Asegurar que no creemos segmentos vacíos
        if start_ms >= end_ms:
            continue
        chunk_audio = audio[start_ms:end_ms]

        chunk_filename = dir_temporal_chunks / f"{ruta_archivo_wav.stem}_chunk_{i+1}.wav"
        try:
            chunk_audio.export(chunk_filename, format="wav")
        except Exception as e:
            print(f"     ❌ Error al exportar chunk {i+1}: {e}")
            continue

        chunk_result = _transcribir_chunk_whisper(chunk_filename)

        if chunk_result:
            all_text += chunk_result.get('text', '') + " "
            last_successful_lang = chunk_result.get('language', last_successful_lang)
            chunk_start_time_s = start_ms / 1000.0
            if 'segments' in chunk_result:
                for seg in chunk_result['segments']:
                    adjusted_seg = seg.copy()
                    adjusted_seg['start'] = chunk_start_time_s + seg.get('start', 0)
                    adjusted_seg['end'] = chunk_start_time_s + seg.get('end', 0)
                    all_segments.append(adjusted_seg)
        else:
            print(f"     ⚠️ No se pudo transcribir el chunk {i+1}. Se omitirá.")

        try:
            chunk_filename.unlink()
        except OSError as e:
            print(f"     ⚠️ No se pudo borrar el archivo temporal del chunk: {e}")

    if not all_text:
        print(f"     ❌ No se pudo transcribir ningún chunk.")
        return None

    combined_result = {
        "text": all_text.strip(),
        "segments": all_segments,
        "language": last_successful_lang
    }
    print(f"     ✅ Transcripción combinada de chunks completada.")
    return combined_result

# Función auxiliar para transcribir UN chunk (la llamada real a la API)
# (Sin cambios respecto a la versión anterior)
def _transcribir_chunk_whisper(ruta_chunk_wav: Path) -> Optional[Dict[str, Any]]:
    """Llama a la API de Whisper para un único archivo WAV."""
    print(f"      🗣️ Enviando {ruta_chunk_wav.name} ({ruta_chunk_wav.stat().st_size / (1024*1024):.2f} MB) a Whisper...")
    try:
        with open(ruta_chunk_wav, "rb") as audio_file:
            # Añadir parámetros como en tu ejemplo si los necesitas (language, temperature)
            respuesta = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
                language="es", # Forzar español como en tu ejemplo
                temperature=0.3 # Usar temperatura como en tu ejemplo
            )
        print(f"      ✅ Chunk {ruta_chunk_wav.name} transcrito.")
        return respuesta.dict()
    except openai.APIError as e:
        # Manejar específicamente el error 413 si aún ocurriera
        if "413" in str(e):
             print(f"      ❌ Error 413: El chunk {ruta_chunk_wav.name} ({ruta_chunk_wav.stat().st_size} bytes) aún supera el límite de tamaño.")
        else:
             print(f"      ❌ Error de API OpenAI al transcribir chunk {ruta_chunk_wav.name}: {e}")
        return None
    except Exception as e:
        print(f"      ❌ Error inesperado al transcribir chunk {ruta_chunk_wav.name}: {e}")
        return None

def diarizar_audio(ruta_archivo_wav: Path) -> Optional[Any]:
    """Realiza la diarización de hablantes en un archivo WAV.

    Args:
        ruta_archivo_wav: Ruta al archivo WAV.

    Returns:
        Objeto de anotaciones de pyannote con los segmentos de hablante,
        o None si el pipeline no está disponible o falla.
    """
    if di_pipeline is None:
        print("⏭️ Saltando diarización: pipeline no inicializado.")
        return None

    print(f"👥 Diarizando {ruta_archivo_wav.name}...")
    try:
        diarization_result = di_pipeline(str(ruta_archivo_wav))
        print(f"✅ Diarización completada para {ruta_archivo_wav.name}")
        return diarization_result
    except Exception as e:
        print(f"❌ Error durante la diarización de {ruta_archivo_wav.name}: {e}")
        return None

def guardar_transcripcion(
    texto_diarizado: str, # Ahora recibe el texto ya formateado
    ruta_salida_base: Path,
    # guardar_json ya no es relevante para el formato TXT
) -> None:
    """Guarda la transcripción diarizada y formateada en un archivo TXT.

    Args:
        texto_diarizado: String multilínea con el formato SPEAKER_XX: texto.
        ruta_salida_base: Ruta base para el archivo de salida (sin extensión).
    """
    ruta_salida = ruta_salida_base.with_suffix(".diarized.txt")
    try:
        # Usar encoding latin-1 con ignore como en tu ejemplo por si acaso
        with open(ruta_salida, "w", encoding="latin-1", errors="ignore") as f:
            f.write(texto_diarizado)
        print(f"💾 Transcripción TXT diarizada guardada en: {ruta_salida}")
    except Exception as e:
        print(f"❌ Error al guardar el archivo TXT diarizado {ruta_salida}: {e}")


# --- Función Principal ---

def procesar_directorio(
    dir_entrada: Path,
    dir_salida: Path,
    # formato_salida_json ya no se usa para TXT
) -> None:
    """Procesa archivos de audio: convierte a WAV, diariza, transcribe por turno.
    """
    if not dir_entrada.is_dir():
        print(f"❌ Error: El directorio de entrada '{dir_entrada}' no existe.")
        return

    dir_salida.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        dir_temporal_base = Path(tmpdir)
        print(f"📂 Usando directorio temporal base: {dir_temporal_base}")

        archivos_audio = list(dir_entrada.glob("*.*"))
        if not archivos_audio:
            print(f"⚠️ No se encontraron archivos en '{dir_entrada}'.")
            return

        for ruta_audio in archivos_audio:
            if not ruta_audio.is_file(): continue

            print(f"\n--- Procesando: {ruta_audio.name} ---")
            nombre_base_salida = dir_salida / ruta_audio.stem
            texto_diarizado_final = ""

            # --- 1. Convertir a WAV ---
            dir_temporal_wav = dir_temporal_base / "wav"
            dir_temporal_wav.mkdir(exist_ok=True)
            ruta_wav = convertir_a_wav(ruta_audio, dir_temporal_wav)
            if not ruta_wav:
                print(f"⏭️ Saltando archivo {ruta_audio.name} (error conversión)." )
                continue

            # Cargar el audio WAV completo para poder extraer segmentos
            try:
                audio_completo = AudioSegment.from_wav(ruta_wav)
            except Exception as e:
                 print(f"❌ Error al cargar WAV {ruta_wav.name} para segmentar: {e}")
                 print(f"⏭️ Saltando archivo {ruta_audio.name}." )
                 continue

            # --- 2. Diarizar --- 
            diarization_info = diarizar_audio(ruta_wav)
            if diarization_info is None:
                print(f"⚠️ No se pudo diarizar {ruta_audio.name}. Se transcribirá sin hablantes.")
                # Transcribir el archivo completo sin diarización
                dir_temporal_chunks_full = dir_temporal_base / "chunks_full"
                dir_temporal_chunks_full.mkdir(exist_ok=True)
                resultado_completo = _transcribir_wav_con_chunking_opcional(ruta_wav, dir_temporal_chunks_full, forzar_chunking=True)
                if resultado_completo and resultado_completo.get("text"):
                     texto_diarizado_final = f"SPEAKER_?: {resultado_completo['text']}\n"
                else:
                     print(f"❌ Falló también la transcripción completa de {ruta_audio.name}.")
                     texto_diarizado_final = "SPEAKER_?: [Error en transcripción completa]\n"

            else:
                # --- 3. Iterar turnos diarizados y transcribir cada uno --- 
                print(f"   Iterando sobre {len(list(diarization_info.itertracks(yield_label=True)))} turnos de hablante...")
                dir_temporal_turnos = dir_temporal_base / "turn_chunks"
                dir_temporal_turnos.mkdir(exist_ok=True)

                for i, (turn, _, speaker) in enumerate(diarization_info.itertracks(yield_label=True)):
                    start_s, end_s = turn.start, turn.end
                    start_ms, end_ms = int(start_s * 1000), int(end_s * 1000)
                    duracion_ms = end_ms - start_ms

                    print(f"   Procesando Turno {i+1}: {speaker} [{start_s:.2f}s - {end_s:.2f}s] ({duracion_ms/1000:.1f}s)")

                    # Saltar turnos muy cortos como en tu ejemplo
                    if duracion_ms < 100: # Menos de 0.1 segundos
                        print(f"      ⏭️ Saltando turno {i+1} (demasiado corto: {duracion_ms}ms)")
                        continue

                    # Extraer segmento del turno
                    try:
                        segmento_turno = audio_completo[start_ms:end_ms]
                    except Exception as e:
                        print(f"      ❌ Error al extraer audio del turno {i+1}: {e}")
                        continue

                    # Guardar segmento del turno en archivo temporal
                    ruta_turno_wav = dir_temporal_turnos / f"{ruta_wav.stem}_turn_{i+1}.wav"
                    try:
                        segmento_turno.export(ruta_turno_wav, format="wav")
                    except Exception as e:
                         print(f"      ❌ Error al exportar WAV del turno {i+1}: {e}")
                         continue

                    # Transcribir el WAV del turno (con chunking opcional si el turno es largo)
                    dir_temporal_chunks_turno = dir_temporal_base / "turn_subchunks"
                    dir_temporal_chunks_turno.mkdir(exist_ok=True)
                    resultado_transcripcion = _transcribir_wav_con_chunking_opcional(
                        ruta_turno_wav, dir_temporal_chunks_turno
                    )

                    if resultado_transcripcion and resultado_transcripcion.get("text"):
                        texto_transcrito = resultado_transcripcion["text"]
                        texto_diarizado_final += f"{speaker}: {texto_transcrito}\n"
                    else:
                        print(f"      ⚠️ No se pudo transcribir el turno {i+1}. Se omitirá.")
                        # Podríamos añadir un placeholder si quisiéramos
                        # texto_diarizado_final += f"{speaker}: [Error en transcripción turno {i+1}]\n"

                    # Limpiar WAV del turno
                    try:
                        ruta_turno_wav.unlink()
                    except OSError as e:
                         print(f"     ⚠️ No se pudo borrar el archivo temporal del turno: {e}")

            # --- 4. Guardar resultado final --- 
            if texto_diarizado_final:
                 guardar_transcripcion(texto_diarizado_final, nombre_base_salida)
            else:
                 print(f"❌ No se generó texto final para {ruta_audio.name}.")

    print("🏁 Proceso completado.")


# --- Punto de Entrada ---

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Transcribe y diariza archivos de audio de la carpeta 'audio/'.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    # El argumento JSON ya no es relevante para la salida TXT diarizada
    # parser.add_argument(
    #     "--json",
    #     action="store_true",
    #     help="Guardar la salida detallada en formato JSON en lugar de TXT formateado."
    # )
    parser.add_argument(
        "-o", "--directorio_salida",
        type=Path,
        default=Path("/home/kaslu/data_modeler/GLCV-Data-AI-Solutions/Gadget/audio_to_text/text"),
        help="Ruta al directorio donde se guardarán las transcripciones diarizadas (.txt)."
    )
    # ... (resto del __main__ sin cambios, incluyendo la validación de ffmpeg)
    args = parser.parse_args()
    directorio_entrada_fijo = Path("/home/kaslu/data_modeler/GLCV-Data-AI-Solutions/Gadget/audio_to_text/audio")
    # ... (creación directorio entrada)
    # ... (validación ffmpeg)

    procesar_directorio(
        dir_entrada=directorio_entrada_fijo,
        dir_salida=args.directorio_salida,
        # formato_salida_json=args.json # Eliminado
    )