#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Módulo para recortar archivos de video y audio.

Este script permite recortar segmentos de archivos multimedia
utilizando la biblioteca moviepy.
"""

import os
from typing import List, Tuple
import typer
from rich.console import Console
from moviepy.editor import VideoFileClip, AudioFileClip, concatenate_videoclips, concatenate_audioclips

console = Console()
app = typer.Typer(help="Herramienta para recortar videos y audio")

def parsear_tiempo(tiempo_str: str) -> float:
    """Convierte un string de tiempo HH:MM:SS.ms o MM:SS.ms o SS.ms a segundos."""
    partes = tiempo_str.split(':')
    segundos = 0.0
    multiplicador = 1
    for parte in reversed(partes):
        try:
            segundos += float(parte) * multiplicador
            multiplicador *= 60
        except ValueError:
            raise typer.BadParameter(f"Formato de tiempo inválido: '{tiempo_str}'. Use HH:MM:SS.ms, MM:SS.ms o SS.ms.")
    return segundos

def parsear_rangos(rangos_str: List[str]) -> List[Tuple[float, float]]:
    """Convierte una lista de strings 'inicio-fin' en tuplas de segundos."""
    rangos_segundos = []
    for rango in rangos_str:
        try:
            inicio_str, fin_str = rango.split('-')
            inicio = parsear_tiempo(inicio_str.strip())
            fin = parsear_tiempo(fin_str.strip())
            if inicio >= fin:
                raise typer.BadParameter(f"El tiempo de inicio ({inicio_str}) debe ser menor que el tiempo de fin ({fin_str}) en el rango '{rango}'.")
            rangos_segundos.append((inicio, fin))
        except ValueError:
            raise typer.BadParameter(f"Formato de rango inválido: '{rango}'. Use 'inicio-fin'. Ejemplo: '00:10-00:25.5'.")
        except Exception as e:
             raise typer.BadParameter(f"Error procesando el rango '{rango}': {e}")
    return rangos_segundos

@app.command()
def recortar(
    archivo_entrada: str = typer.Argument(..., help="Ruta al archivo de video o audio a recortar.", exists=True, file_okay=True, dir_okay=False, readable=True),
    rangos: List[str] = typer.Argument(..., help="Lista de rangos de tiempo a extraer en formato 'inicio-fin'. Ejemplo: '0:10-0:25.5' '1:30-1:45'"),
    archivo_salida: str = typer.Option("recorte", "--salida", "-s", help="Nombre base para los archivos de salida (sin extensión)."),
    directorio_salida: str = typer.Option(
        "/home/kaslu/data_modeler/GLCV-Data-AI-Solutions/Gadget/youtube_downloader/recortes_cut",
        "--dir", "-d", 
        help="Directorio donde guardar los archivos recortados.", 
        file_okay=False, dir_okay=True, writable=True
    ),
    unir_clips: bool = typer.Option(False, "--unir", "-u", help="Unir todos los clips recortados en un solo archivo de salida.")
):
    """Recorta segmentos de un archivo de video o audio según los rangos especificados."""
    
    console.print(f"[bold blue]Procesando archivo:[/bold blue] {archivo_entrada}")
    
    try:
        rangos_parseados = parsear_rangos(rangos)
        console.print(f"[bold]Rangos a extraer (en segundos):[/bold] {rangos_parseados}")
    except typer.BadParameter as e:
        console.print(f"[bold red]Error en los rangos:[/bold red] {e}")
        raise typer.Exit(code=1)
    
    # Crear directorio de salida si no existe
    if not os.path.exists(directorio_salida):
        os.makedirs(directorio_salida)
        console.print(f"[green]Creado directorio de salida:[/green] {directorio_salida}")
        
    base_salida, ext_entrada = os.path.splitext(os.path.basename(archivo_entrada))
    ext_entrada = ext_entrada.lower()
    es_video = ext_entrada in [".mp4", ".avi", ".mov", ".mkv", ".webm"]
    es_audio = ext_entrada in [".mp3", ".wav", ".ogg", ".aac", ".m4a"]
    
    if not es_video and not es_audio:
        console.print(f"[bold red]Error:[/bold red] Formato de archivo no soportado: {ext_entrada}")
        raise typer.Exit(code=1)
        
    clips_recortados = []
    
    try:
        with console.status("[bold yellow]Cargando archivo y extrayendo clips...", spinner="dots") as status:
            if es_video:
                clip_principal = VideoFileClip(archivo_entrada)
                ClipClass = VideoFileClip
                concatenate_func = concatenate_videoclips
                extension_salida = ".mp4" # Default a mp4 para video
            else: # es_audio
                clip_principal = AudioFileClip(archivo_entrada)
                ClipClass = AudioFileClip
                concatenate_func = concatenate_audioclips
                extension_salida = ".mp3" # Default a mp3 para audio
            
            duracion_total = clip_principal.duration
            console.print(f"[bold]Duración total del archivo:[/bold] {duracion_total:.2f} segundos")
            
            for i, (inicio, fin) in enumerate(rangos_parseados):
                if fin > duracion_total:
                    console.print(f"[yellow]Advertencia:[/yellow] El tiempo de fin ({fin:.2f}s) para el rango {i+1} excede la duración del archivo ({duracion_total:.2f}s). Se recortará hasta el final.")
                    fin = duracion_total
                if inicio >= duracion_total:
                     console.print(f"[yellow]Advertencia:[/yellow] El tiempo de inicio ({inicio:.2f}s) para el rango {i+1} es mayor o igual a la duración del archivo ({duracion_total:.2f}s). Omitiendo este rango.")
                     continue
                
                status.update(f"[bold yellow]Extrayendo clip {i+1}/{len(rangos_parseados)} ({inicio:.2f}s - {fin:.2f}s)...")
                subclip = clip_principal.subclip(inicio, fin)
                clips_recortados.append(subclip)
                
                if not unir_clips:
                    nombre_clip_salida = f"{archivo_salida}_clip_{i+1}{extension_salida}"
                    ruta_clip_salida = os.path.join(directorio_salida, nombre_clip_salida)
                    status.update(f"[bold yellow]Guardando clip {i+1}: {nombre_clip_salida}...")
                    if es_video:
                        subclip.write_videofile(ruta_clip_salida, codec="libx264", audio_codec="aac")
                    else:
                         subclip.write_audiofile(ruta_clip_salida)
                    console.print(f"[green]✓ Clip guardado:[/green] {ruta_clip_salida}")
        
        if unir_clips and clips_recortados:
            with console.status("[bold yellow]Uniendo clips...", spinner="dots") as status:
                clip_final = concatenate_func(clips_recortados)
                nombre_clip_final = f"{archivo_salida}_unido{extension_salida}"
                ruta_clip_final = os.path.join(directorio_salida, nombre_clip_final)
                status.update(f"[bold yellow]Guardando archivo unido: {nombre_clip_final}...")
                if es_video:
                    clip_final.write_videofile(ruta_clip_final, codec="libx264", audio_codec="aac")
                else:
                    clip_final.write_audiofile(ruta_clip_final)
                console.print(f"[green]✓ Archivo unido guardado:[/green] {ruta_clip_final}")
                
        # Liberar recursos
        clip_principal.close()
        for clip in clips_recortados:
            clip.close()
            
        console.print("[bold green]¡Proceso de recorte completado con éxito![/bold green]")
        
    except Exception as e:
        console.print(f"[bold red]Error durante el procesamiento:[/bold red] {e}")
        import traceback
        traceback.print_exc()
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app() 