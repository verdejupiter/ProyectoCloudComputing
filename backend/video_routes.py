from fastapi import APIRouter, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse
from google.cloud import storage
import os
import json
import cv2
import numpy as np
import asyncio
import logging
from config import *
from database import insert_or_update_video_data, get_video_data
from ultralytics import YOLO
import subprocess
from heatmap import generate_heatmap_background
import io

logger = logging.getLogger(__name__)
video_router = APIRouter()

# Inicializar cliente de Google Cloud Storage
storage_client = storage.Client()
original_bucket = storage_client.bucket(ORIGINAL_VIDEOS_BUCKET)
processed_bucket = storage_client.bucket(PROCESSED_VIDEOS_BUCKET)
heatmaps_bucket = storage_client.bucket(HEATMAPS_BUCKET)

class ProcessingStatus:
    def __init__(self):
        self.status = {}
        self._lock = asyncio.Lock()

    async def set_progress(self, video_name: str, progress: int, step: str):
        async with self._lock:
            current_status = self.status.get(video_name, {})
            if progress > current_status.get('progress', 0):
                self.status[video_name] = {
                    "status": "processing" if progress < 100 else "completed",
                    "progress": progress,
                    "step": step
                }

    async def get_progress(self, video_name: str):
        async with self._lock:
            if video_name not in self.status:
                # Verificar si el video ya está procesado
                video_data = get_video_data(video_name)
                if video_data and video_data.get("processed_video_path"):
                    return {
                        "status": "completed",
                        "progress": 100,
                        "step": "completed",
                        "processed_video_path": video_data["processed_video_path"],
                        "heatmap_path": video_data["heatmap_path"]
                    }
                return {
                    "status": "not_started",
                    "progress": 0,
                    "step": "not_started"
                }
            return self.status[video_name]

processing_status = ProcessingStatus()

@video_router.get("/available-videos")
async def get_available_videos():
    try:
        blobs = list(storage_client.list_blobs(ORIGINAL_VIDEOS_BUCKET))
        videos = [blob.name for blob in blobs if blob.name.lower().endswith(tuple(ALLOWED_EXTENSIONS))]
        return {"videos": videos}
    except Exception as e:
        logger.error(f"Error getting available videos: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={
                "videos": [],
                "error": str(e),
                "detail": "Error getting video list"
            }
        )

@video_router.post("/upload")
async def upload_video(file: UploadFile = File(...)):
    try:
        if not file.filename.lower().endswith(tuple(ALLOWED_EXTENSIONS)):
            raise HTTPException(
                status_code=400, 
                detail=f"Only {', '.join(ALLOWED_EXTENSIONS)} files are allowed"
            )

        # Validar tamaño del archivo
        file_size = 0
        content = await file.read()
        file_size = len(content)
        
        if file_size > MAX_CONTENT_LENGTH:
            raise HTTPException(
                status_code=400,
                detail=f"File size exceeds maximum allowed ({MAX_CONTENT_LENGTH/1024/1024}MB)"
            )

        # Subir a GCS usando BytesIO
        blob = original_bucket.blob(file.filename)
        blob.upload_from_string(
            content,
            content_type='video/mp4'
        )

        return JSONResponse(
            status_code=200,
            content={"message": f"Video {file.filename} uploaded successfully"}
        )
    except Exception as e:
        logger.error(f"Error uploading video: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@video_router.get("/process/{video_name}")
async def process_video(video_name: str, background_tasks: BackgroundTasks):
    try:
        logger.info(f"Processing request for video: {video_name}")

        # Verificar si el video existe en GCS
        if not original_bucket.blob(video_name).exists():
            raise HTTPException(status_code=404, detail="Video not found in storage")

        # Verificar si ya está en proceso
        current_status = await processing_status.get_progress(video_name)
        if current_status["status"] == "processing":
            return current_status
        
        # Verificar base de datos
        video_data = get_video_data(video_name)
        logger.info(f"Video data from DB: {video_data}")

        # Verificar si ya está procesado en la base de datos
        video_data = get_video_data(video_name)
        if video_data and video_data.get("processed_video_path"):
            return {
                "status": "completed",
                "progress": 100,
                "step": "completed",
                "processed_video_path": video_data["processed_video_path"],
                "heatmap_path": video_data["heatmap_path"]
            }

        # Iniciar procesamiento
        background_tasks.add_task(
            process_video_background,
            video_name
        )

        return {
            "status": "processing",
            "progress": 0,
            "step": "starting"
        }

    except Exception as e:
        logger.error(f"Error in process_video: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

async def process_video_background(video_name: str):
    temp_video_path = TEMP_DIR / video_name
    temp_processed_path = TEMP_DIR / f"processed_{video_name}"

    try:
        logger.info(f"Starting processing for {video_name}")
        logger.info(f"Checking GCS buckets...")
        
        # Verificar buckets
        if not original_bucket.exists():
            logger.error("Original bucket doesn't exist")
            return
        if not processed_bucket.exists():
            logger.error("Processed bucket doesn't exist")
            return
        if not heatmaps_bucket.exists():
            logger.error("Heatmaps bucket doesn't exist")
            return
            
        # Verificar existencia del video en bucket original
        blob = original_bucket.blob(video_name)
        if not blob.exists():
            logger.error(f"Video {video_name} not found in original bucket")
            return
    
 
        # Descargar video original de GCS
        logger.info(f"Downloading video {video_name} from GCS")
        blob = original_bucket.blob(video_name)
        blob.download_to_filename(str(temp_video_path))

        # Generar metadata
        await processing_status.set_progress(video_name, 0, "generating_metadata")
        metadata = generate_metadata(str(temp_video_path))
        
        # Guardar metadata en PostgreSQL
        insert_or_update_video_data(video_name, metadata=json.dumps(metadata))
        await processing_status.set_progress(video_name, 33, "metadata_complete")

        # Procesar video
        await processing_status.set_progress(video_name, 33, "processing_video")
        await process_video_with_metadata(temp_video_path, temp_processed_path, metadata)

        # Subir video procesado a GCS
        processed_blob = processed_bucket.blob(f"processed_{video_name}")
        processed_blob.upload_from_filename(str(temp_processed_path))
        gcs_processed_path = f"gs://{PROCESSED_VIDEOS_BUCKET}/processed_{video_name}"
        
        # Actualizar base de datos con la ruta del video procesado
        insert_or_update_video_data(video_name, processed_video_path=gcs_processed_path)
        await processing_status.set_progress(video_name, 66, "video_complete")

        # Generar y subir heatmap
        await processing_status.set_progress(video_name, 66, "generating_heatmap")
        heatmap_path = await generate_heatmap_background(video_name, metadata)
        
        if heatmap_path and os.path.exists(heatmap_path):
            # Subir heatmap a GCS
            heatmap_blob = heatmaps_bucket.blob(f"heatmap_{video_name.replace('.mp4', '.png')}")
            heatmap_blob.upload_from_filename(str(heatmap_path))
            gcs_heatmap_path = f"gs://{HEATMAPS_BUCKET}/heatmap_{video_name.replace('.mp4', '.png')}"
            
            # Actualizar base de datos con la ruta del heatmap
            insert_or_update_video_data(video_name, heatmap_path=gcs_heatmap_path)
            
            # Limpiar archivo temporal del heatmap
            os.remove(str(heatmap_path))

        await processing_status.set_progress(video_name, 100, "completed")

    except Exception as e:
        logger.error(f"Error in background processing: {str(e)}")
        await processing_status.set_progress(video_name, -1, f"error: {str(e)}")
        raise
    finally:
        # Limpiar archivos temporales
        if os.path.exists(str(temp_video_path)):
            os.remove(str(temp_video_path))
        if os.path.exists(str(temp_processed_path)):
            os.remove(str(temp_processed_path))

@video_router.get("/stream/{video_name}")
async def stream_video(video_name: str):
    try:
        # Verificar en la base de datos si existe versión procesada
        video_data = get_video_data(video_name)
        
        if video_data and video_data.get("processed_video_path"):
            # Extraer nombre del blob de la ruta GCS
            blob_name = video_data["processed_video_path"].split('/')[-1]
            blob = processed_bucket.blob(blob_name)
        else:
            # Usar video original
            blob = original_bucket.blob(video_name)

        if not blob.exists():
            raise HTTPException(status_code=404, detail="Video not found")

        # Configurar streaming
        def generate():
            download_stream = blob.download_as_bytes()
            yield download_stream

        return StreamingResponse(
            generate(),
            media_type="video/mp4",
            headers={
                "Accept-Ranges": "bytes",
                "Content-Disposition": f'attachment; filename="{blob.name}"'
            }
        )

    except Exception as e:
        logger.error(f"Error streaming video: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@video_router.get("/status/{video_name}")
async def get_processing_status(video_name: str):
    try:
        status = await processing_status.get_progress(video_name)
        
        # Si está completado, incluir las rutas
        if status["status"] == "completed":
            video_data = get_video_data(video_name)
            if video_data:
                status.update({
                    "processed_video_path": video_data["processed_video_path"],
                    "heatmap_path": video_data["heatmap_path"]
                })
                
        return status
    except Exception as e:
        logger.error(f"Error getting status: {str(e)}")
        return {"status": "error", "message": str(e)}

def generate_metadata(video_path: str):
    """Generar metadata para el video usando YOLO"""
    model = YOLO(str(MODEL_PATH))
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise Exception("Could not open video")

    metadata = []
    frame_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        results = model(frame)
        detections = []

        for r in results[0]:
            for box, cls, conf in zip(r.boxes.xyxy, r.boxes.cls, r.boxes.conf):
                if conf > 0.3:
                    coords = box.cpu().numpy()
                    detections.append({
                        "label": model.names[int(cls)],
                        "confidence": float(conf),
                        "coordinates": [[int(c) for c in coords]]
                    })

        if detections:
            metadata.append({
                "frame": frame_count,
                "objects": detections
            })

        frame_count += 1

    cap.release()
    return metadata

async def process_video_with_metadata(input_path, output_path, metadata):
    """Procesar video añadiendo las detecciones"""
    cap = cv2.VideoCapture(str(input_path))
    if not cap.isOpened():
        raise Exception("Could not open video for processing")

    fps = int(cap.get(cv2.CAP_PROP_FPS))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    temp_output = str(output_path).replace('.mp4', '_temp.mp4')
    
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(temp_output, fourcc, fps, (width, height))

    frame_count = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame_metadata = next((m for m in metadata if m["frame"] == frame_count), None)
            
            if frame_metadata:
                for obj in frame_metadata["objects"]:
                    try:
                        x1, y1, x2, y2 = map(int, obj["coordinates"][0])
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                        cv2.putText(frame, f"{obj['label']} {obj['confidence']:.2f}",
                                 (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                    except (ValueError, IndexError) as e:
                        logger.error(f"Error drawing detection: {str(e)}")
                        continue

            writer.write(frame)
            frame_count += 1

    finally:
        cap.release()
        writer.release()

    try:
        # Convertir video temporal a MP4 compatible con web
        subprocess.run([
            'ffmpeg', '-i', temp_output,
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-crf', '28',
            '-movflags', '+faststart',
            '-pix_fmt', 'yuv420p',
            str(output_path)
        ], check=True)
        
        # Limpiar archivo temporal
        if os.path.exists(temp_output):
            os.remove(temp_output)
            
    except subprocess.CalledProcessError as e:
        raise Exception(f"Error converting video: {str(e)}")
    except Exception as e:
        raise Exception(f"Unexpected error: {str(e)}")

    if not os.path.exists(str(output_path)):
        raise Exception("Processed video file was not generated")
        
    if os.path.getsize(str(output_path)) == 0:
        os.remove(str(output_path))
        raise Exception("Generated video file is empty")
        
    return str(output_path)

@video_router.get("/rtsp/stream/{video_name}")
async def stream_frame(video_name: str):
    try:
        video_data = get_video_data(video_name)
        if video_data and video_data.get("processed_video_path"):
            # Usar video procesado si existe
            blob_name = video_data["processed_video_path"].split('/')[-1]
            blob = processed_bucket.blob(blob_name)
        else:
            # Usar video original
            blob = original_bucket.blob(video_name)

        if not blob.exists():
            raise HTTPException(status_code=404, detail="Video not found")

        # Descargar el contenido
        content = blob.download_as_bytes()
        
        return StreamingResponse(
            io.BytesIO(content),
            media_type="video/mp4",
            headers={
                "Cache-Control": "no-cache",
                "Access-Control-Allow-Origin": "*"
            }
        )

    except Exception as e:
        logger.error(f"Error streaming frame: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))