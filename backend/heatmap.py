from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from google.cloud import storage
import numpy as np
import cv2
import os
import logging
import io
from config import *
from database import insert_or_update_video_data, get_video_data

logger = logging.getLogger(__name__)
heatmap_router = APIRouter()

# Inicializar cliente de Google Cloud Storage
storage_client = storage.Client()
original_bucket = storage_client.bucket(ORIGINAL_VIDEOS_BUCKET)
heatmaps_bucket = storage_client.bucket(HEATMAPS_BUCKET)

@heatmap_router.get("/{video_name}")
async def get_heatmap(video_name: str, background_tasks: BackgroundTasks):
    try:
        # Verificar en base de datos
        video_data = get_video_data(video_name)
        if video_data and video_data.get("heatmap_path"):
            return {
                "status": "ready",
                "path": video_data["heatmap_path"]
            }

        # Verificar en GCS
        heatmap_blob = heatmaps_bucket.blob(f"heatmap_{video_name.replace('.mp4', '.png')}")
        if heatmap_blob.exists():
            gcs_path = f"gs://{HEATMAPS_BUCKET}/heatmap_{video_name.replace('.mp4', '.png')}"
            # Actualizar base de datos
            insert_or_update_video_data(video_name, heatmap_path=gcs_path)
            return {
                "status": "ready",
                "path": gcs_path
            }
        
        # Iniciar generación
        background_tasks.add_task(generate_heatmap_background, video_name)
        return {"status": "processing"}

    except Exception as e:
        logger.error(f"Heatmap error: {str(e)}")
        return {"status": "error", "message": str(e)}

@heatmap_router.get("/download/{video_name}")
async def download_heatmap(video_name: str):
    try:
        heatmap_blob_name = f"heatmap_{video_name.replace('.mp4', '.png')}"
        heatmap_blob = heatmaps_bucket.blob(heatmap_blob_name)
        
        if not heatmap_blob.exists():
            raise HTTPException(status_code=404, detail="Heatmap not found")

        # Agregar logs para debug
        logger.info(f"Descargando heatmap: {heatmap_blob_name}")
        
        # Obtener los bytes del heatmap
        heatmap_bytes = heatmap_blob.download_as_bytes()
        
        return StreamingResponse(
            io.BytesIO(heatmap_bytes),
            media_type="image/png",
            headers={
                "Content-Type": "image/png",
                "Cache-Control": "no-cache",
                "Access-Control-Allow-Origin": "*"
            }
        )

    except Exception as e:
        logger.error(f"Error downloading heatmap: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

async def generate_heatmap_background(video_name: str, metadata=None):
    """Generar heatmap basado en metadata de detecciones"""
    temp_video_path = TEMP_DIR / video_name
    temp_heatmap_path = TEMP_DIR / f"heatmap_{video_name.replace('.mp4', '.png')}"
    
    try:
        # Obtener metadata si no fue proporcionada
        if metadata is None:
            video_data = get_video_data(video_name)
            if video_data and video_data.get("metadata"):
                metadata = video_data["metadata"]
            else:
                raise Exception("No metadata available for heatmap generation")

        # Descargar video original si es necesario
        blob = original_bucket.blob(video_name)
        blob.download_to_filename(str(temp_video_path))

        # Abrir video
        cap = cv2.VideoCapture(str(temp_video_path))
        if not cap.isOpened():
            raise Exception("Cannot open video")

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        # Obtener frame del medio para fondo
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames // 2)
        ret, background = cap.read()
        cap.release()

        if not ret:
            raise Exception("Cannot read background frame")

        # Oscurecer fondo
        background = cv2.convertScaleAbs(background, alpha=0.3, beta=0)

        # Crear heatmap
        heatmap_data = np.zeros((height, width), dtype=np.float32)
        
        # Procesar detecciones en lotes
        batch_size = 100
        for i in range(0, len(metadata), batch_size):
            batch = metadata[i:i + batch_size]
            
            for detection in batch:
                for obj in detection.get("objects", []):
                    try:
                        x1, y1, x2, y2 = map(int, obj["coordinates"][0])
                        confidence = float(obj.get("confidence", 1.0))
                        
                        # Validar coordenadas
                        x1 = max(0, min(x1, width-1))
                        x2 = max(0, min(x2, width-1))
                        y1 = max(0, min(y1, height-1))
                        y2 = max(0, min(y2, height-1))
                        
                        if x1 >= x2 or y1 >= y2:
                            continue
                        
                        # Crear máscara gaussiana
                        center_x = (x1 + x2) // 2
                        center_y = (y1 + y2) // 2
                        sigma = max(x2 - x1, y2 - y1) / 4
                        
                        window_size = int(sigma * 3)
                        y_min = max(0, center_y - window_size)
                        y_max = min(height, center_y + window_size)
                        x_min = max(0, center_x - window_size)
                        x_max = min(width, center_x + window_size)
                        
                        y, x = np.ogrid[y_min-center_y:y_max-center_y, x_min-center_x:x_max-center_x]
                        mask = np.exp(-(x*x + y*y) / (2*sigma*sigma))
                        heatmap_data[y_min:y_max, x_min:x_max] += mask * confidence

                    except Exception as e:
                        logger.error(f"Error processing detection: {str(e)}")
                        continue

        if np.max(heatmap_data) > 0:
            # Normalizar y procesar heatmap
            heatmap_data = cv2.normalize(heatmap_data, None, 0, 255, cv2.NORM_MINMAX)
            heatmap_data = heatmap_data.astype(np.uint8)
            heatmap_data[heatmap_data < 50] = 0
            heatmap_colored = cv2.applyColorMap(heatmap_data, cv2.COLORMAP_JET)
            
            # Combinar con fondo
            result = cv2.addWeighted(background, 1, heatmap_colored, 0.7, 0)
            
            # Guardar temporalmente
            cv2.imwrite(str(temp_heatmap_path), result, [cv2.IMWRITE_PNG_COMPRESSION, 9])
            
            # Subir a GCS
            heatmap_blob = heatmaps_bucket.blob(f"heatmap_{video_name.replace('.mp4', '.png')}")
            heatmap_blob.upload_from_filename(str(temp_heatmap_path))
            
            # Actualizar base de datos
            gcs_path = f"gs://{HEATMAPS_BUCKET}/heatmap_{video_name.replace('.mp4', '.png')}"
            insert_or_update_video_data(video_name, heatmap_path=gcs_path)
            
            return str(temp_heatmap_path)
        
        raise Exception("No detections found for heatmap generation")

    except Exception as e:
        logger.error(f"Error generating heatmap: {str(e)}")
        if os.path.exists(str(temp_heatmap_path)):
            os.remove(str(temp_heatmap_path))
        raise e
    finally:
        # Limpiar archivos temporales
        if os.path.exists(str(temp_video_path)):
            os.remove(str(temp_video_path))
