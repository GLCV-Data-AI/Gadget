#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Módulo para descargar videos y audio de YouTube.

Este script permite descargar videos y/o pistas de audio desde YouTube
utilizando la biblioteca pytube.
"""

import os
import sys
from typing import Optional
from enum import Enum

import typer
from rich.console import Console
from rich.progress import Progress, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn
# from pytube import YouTube # Comentado para usar pytubefix
# from pytube.exceptions import PytubeError # Las excepciones parecen venir del mismo lugar
from pytubefix import YouTube # Usamos pytubefix para la funcionalidad principal
# from pytubefix.exceptions import PytubeError # Incorrecto
from pytube.exceptions import PytubeError # Usamos pytube original para las excepciones

console = Console()
app = typer.Typer(help="Herramienta para descargar videos y audio de YouTube")

class FormatoDescarga(str, Enum):
    """Tipos de formato para descargar contenido."""
    VIDEO = "video"
    AUDIO = "audio"
    AMBOS = "ambos"

@app.command()
def descargar(
    url: str = typer.Argument(..., help="URL del video de YouTube"),
    formato: FormatoDescarga = typer.Option(
        FormatoDescarga.VIDEO, "--formato", "-f", 
        help="Formato a descargar: video, audio o ambos"
    ),
    calidad: Optional[str] = typer.Option(
        None, "--calidad", "-c",
        help="Calidad del video (alta, media, baja) o resolución específica (720p, 1080p, etc.)"
    ),
    directorio_salida: str = typer.Option(
        "descargas", "--salida", "-s",
        help="Directorio donde se guardarán los archivos"
    )
):
    """Descarga videos y/o audio de YouTube según las opciones especificadas."""
    try:
        # Crear el directorio de salida si no existe
        if not os.path.exists(directorio_salida):
            os.makedirs(directorio_salida)
            console.print(f"[green]Creado directorio: {directorio_salida}[/green]")
        
        # Iniciar obtención de información
        with console.status(f"[bold blue]Obteniendo información del video: {url}[/bold blue]"):
            yt = YouTube(url) # Sin callback por ahora
        
        console.print(f"[bold green]Video encontrado:[/bold green] {yt.title}")
        console.print(f"[bold]Autor:[/bold] {yt.author}")
        console.print(f"[bold]Duración:[/bold] {yt.length // 60} minutos {yt.length % 60} segundos")
        
        # Descargar según el formato solicitado
        if formato in [FormatoDescarga.VIDEO, FormatoDescarga.AMBOS]:
            # --- Descarga de Video --- 
            stream = None
            with console.status("[bold yellow]Buscando stream de video..."):
                if calidad:
                    if calidad == "alta":
                        stream = yt.streams.get_highest_resolution()
                    elif calidad == "baja":
                        stream = yt.streams.get_lowest_resolution()
                    elif "p" in calidad:  # Si es una resolución específica como "720p"
                        stream = yt.streams.filter(res=calidad, progressive=True, file_extension="mp4").first() # Priorizar progresivo si se especifica calidad
                        if not stream:
                           stream = yt.streams.filter(res=calidad, file_extension="mp4").first() # Fallback no progresivo
                    else:
                        # Si la calidad no es reconocida, usar la más alta
                        stream = yt.streams.get_highest_resolution()
                else:
                    stream = yt.streams.get_highest_resolution()
            
            if not stream:
                console.print(f"[bold red]No se encontró stream de video para la calidad especificada ({calidad or 'más alta'}).[/bold red]")
            else:
                # Limpiar nombre de archivo para evitar problemas
                nombre_archivo_limpio = "".join(c for c in yt.title if c.isalnum() or c in (' ', '.', '_')).rstrip()
                nombre_archivo_video = f"{nombre_archivo_limpio}.{stream.mime_type.split('/')[-1]}"
                ruta_completa_video = os.path.join(directorio_salida, nombre_archivo_video)
                
                console.print(f"[blue]Descargando video ({stream.resolution}, {stream.filesize_mb:.2f} MB) a {ruta_completa_video}...[/blue]")
                try:
                    # Usar el método de descarga directo
                    stream.download(output_path=directorio_salida, filename=nombre_archivo_video)
                    console.print(f"[bold green]✓[/bold green] Video descargado: {os.path.basename(ruta_completa_video)}")
                except Exception as e:
                    console.print(f"[bold red]Error descargando video:[/bold red] {e}")
                    # Opcional: Limpiar archivo parcial si existe
                    # if os.path.exists(ruta_completa_video):
                    #     os.remove(ruta_completa_video)
        
        if formato in [FormatoDescarga.AUDIO, FormatoDescarga.AMBOS]:
             # --- Descarga de Audio --- 
            stream = None
            with console.status("[bold yellow]Buscando stream de audio..."):
                 stream = yt.streams.get_audio_only()
            
            if not stream:
                console.print("[bold red]No se encontró stream de audio.[/bold red]")
            else:
                 # Limpiar nombre de archivo para evitar problemas
                nombre_archivo_limpio = "".join(c for c in yt.title if c.isalnum() or c in (' ', '.', '_')).rstrip()
                nombre_temporal_audio = f"{nombre_archivo_limpio}_audio_temp.{stream.mime_type.split('/')[-1]}"
                ruta_temporal_audio = os.path.join(directorio_salida, nombre_temporal_audio)
                nombre_final_audio = f"{nombre_archivo_limpio}.mp3"
                ruta_final_audio = os.path.join(directorio_salida, nombre_final_audio)

                console.print(f"[blue]Descargando audio ({stream.abr}, {stream.filesize_mb:.2f} MB) a {ruta_final_audio}...[/blue]")
                try:
                    # Descarga directa al archivo temporal
                    stream.download(output_path=directorio_salida, filename=nombre_temporal_audio)

                    # Renombrar a formato mp3 si la descarga fue exitosa
                    if os.path.exists(ruta_final_audio):
                        os.remove(ruta_final_audio) 
                    os.rename(ruta_temporal_audio, ruta_final_audio)
                    console.print(f"[bold green]✓[/bold green] Audio descargado: {os.path.basename(ruta_final_audio)}")

                except Exception as e:
                    console.print(f"[bold red]Error descargando audio:[/bold red] {e}")
                    # Limpiar archivo temporal si existe
                    if os.path.exists(ruta_temporal_audio):
                        os.remove(ruta_temporal_audio)

        console.print("[bold green]¡Proceso de descarga finalizado![/bold green]")
        
    except PytubeError as e:
        console.print(f"[bold red]Error de pytube:[/bold red] {str(e)}")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {str(e)}")

if __name__ == "__main__":
    app()
