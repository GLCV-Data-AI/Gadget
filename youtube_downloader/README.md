# YouTube Downloader

Herramienta para descargar videos y audio de YouTube utilizando pytube.

## Características

- Descarga de videos en diferentes calidades
- Extracción de audio en formato MP3
- Interfaz de línea de comandos amigable
- Barra de progreso en tiempo real
- Opciones flexibles de configuración

## Instalación

1. Clona este repositorio o descarga los archivos

2. Instala las dependencias:

```bash
pip install -r requirements.txt
```

## Uso

### Forma básica:

```bash
python youtube_downloader.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

### Opciones disponibles:

- `--formato` o `-f`: Formato de descarga (`video`, `audio` o `ambos`)
- `--calidad` o `-c`: Calidad del video (`alta`, `baja` o resoluciones específicas como `720p`, `1080p`)
- `--salida` o `-s`: Directorio de salida para los archivos descargados

### Ejemplos:

Descargar solo audio:
```bash
python youtube_downloader.py "https://www.youtube.com/watch?v=VIDEO_ID" --formato audio
```

Descargar video en alta calidad:
```bash
python youtube_downloader.py "https://www.youtube.com/watch?v=VIDEO_ID" --calidad alta
```

Descargar video y audio en un directorio específico:
```bash
python youtube_downloader.py "https://www.youtube.com/watch?v=VIDEO_ID" --formato ambos --salida "mis_descargas"
```

## Requisitos

- Python 3.7+
- pytube
- typer
- rich

## Video/Audio Trimmer

Herramienta adicional para recortar segmentos de archivos de video o audio.

### Características

- Recorta múltiples segmentos de un archivo en una sola ejecución.
- Permite especificar tiempos de inicio y fin en formato flexible (HH:MM:SS.ms, MM:SS.ms, SS.ms).
- Opción para guardar cada clip recortado por separado.
- Opción para unir todos los clips recortados en un único archivo.
- Soporta formatos comunes de video (mp4, avi, mov, mkv, webm) y audio (mp3, wav, ogg, aac, m4a).

### Uso

```bash
python video_trimmer.py [RUTA_ARCHIVO_ENTRADA] [RANGO1] [RANGO2] ... [OPCIONES]
```

**Argumentos:**

- `RUTA_ARCHIVO_ENTRADA`: Ruta al archivo de video o audio que quieres recortar.
- `RANGO`: Uno o más rangos de tiempo en formato `inicio-fin`. Ejemplos: `0:05-0:15`, `1:10.5-1:22`, `125-130.8`.

**Opciones:**

- `--salida` / `-s`: Nombre base para los archivos de salida (por defecto: "recorte").
    - Si no se une (`--unir` es `False`), los archivos se llamarán `[salida]_clip_1.ext`, `[salida]_clip_2.ext`, etc.
    - Si se une (`--unir` es `True`), el archivo se llamará `[salida]_unido.ext`.
- `--dir` / `-d`: Directorio donde guardar los archivos (por defecto: el directorio actual).
- `--unir` / `-u`: Si se especifica, une todos los clips recortados en un solo archivo.

### Ejemplos:

Recortar dos segmentos de un video y guardarlos por separado:
```bash
python video_trimmer.py mi_video.mp4 0:10-0:25 1:30-1:45 -s mi_video_cortado
# Salida: mi_video_cortado_clip_1.mp4, mi_video_cortado_clip_2.mp4
```

Recortar tres segmentos de un audio y unirlos en un solo archivo:
```bash
python video_trimmer.py mi_audio.mp3 5.5-12 30-40.2 65-70 --unir -s audio_editado -d ./salida_audio
# Salida: ./salida_audio/audio_editado_unido.mp3
```

## Requisitos (Completos)

- Python 3.7+
- pytubefix (para descargar)
- typer
- rich
- moviepy (para recortar)
