from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
import logging
from config import *
from database import get_video_data
from google.cloud import storage

logger = logging.getLogger(__name__)
metadata_router = APIRouter()

# Inicializar cliente de Google Cloud Storage
storage_client = storage.Client()
original_bucket = storage_client.bucket(ORIGINAL_VIDEOS_BUCKET)

@metadata_router.get("/{video_name}")
def get_metadata(video_name: str):
    """Obtener metadata de un video específico"""
    try:
        video_data = get_video_data(video_name)
        if not video_data or not video_data.get("metadata"):
            return JSONResponse(
                content={"error": "Metadata not found", "status": "not_found"}, 
                status_code=404
            )
            
        return {
            "metadata": video_data["metadata"],
            "status": "found",
            "processed_video_path": video_data.get("processed_video_path"),
            "heatmap_path": video_data.get("heatmap_path")
        }
    except Exception as e:
        logger.error(f"Error getting metadata: {str(e)}")
        return JSONResponse(
            content={"error": str(e), "status": "error"}, 
            status_code=500
        )

@metadata_router.get("/search/{object_label}")
def search_object(object_label: str):
    """Buscar objetos por etiqueta en todos los videos procesados"""
    try:
        results = []
        blobs = storage_client.list_blobs(ORIGINAL_VIDEOS_BUCKET)
        video_names = [blob.name for blob in blobs if blob.name.endswith('.mp4')]

        for video_name in video_names:
            try:
                video_data = get_video_data(video_name)
                if not video_data or not video_data.get("metadata"):
                    continue

                metadata = video_data["metadata"]
                if not isinstance(metadata, list):
                    continue

                frame_results = []
                for detection in metadata:
                    objects_found = []
                    for obj in detection.get("objects", []):
                        if obj["label"].lower() == object_label.lower():
                            objects_found.append({
                                "coordinates": obj["coordinates"],
                                "confidence": obj.get("confidence", 1.0)
                            })
                    
                    if objects_found:
                        frame_results.append({
                            "frame": detection["frame"],
                            "timestamp": detection["frame"] / 30,  # Asumiendo 30 FPS
                            "objects": objects_found
                        })

                if frame_results:
                    results.append({
                        "video_name": video_name,
                        "frames": sorted(frame_results, key=lambda x: x["frame"]),
                        "processed_video_path": video_data.get("processed_video_path"),
                        "total_detections": sum(len(frame["objects"]) for frame in frame_results)
                    })
            except Exception as e:
                logger.error(f"Error processing video {video_name}: {str(e)}")
                continue

        if not results:
            return JSONResponse(
                content={
                    "error": f"No objects found with label '{object_label}'",
                    "status": "not_found"
                },
                status_code=404
            )

        # Ordenar por número total de detecciones
        results.sort(key=lambda x: x["total_detections"], reverse=True)
        return {"results": results, "status": "found"}

    except Exception as e:
        logger.error(f"Error searching objects: {str(e)}")
        return JSONResponse(
            content={"error": str(e), "status": "error"},
            status_code=500
        )

@metadata_router.get("/objects/{video_name}")
def get_video_objects(video_name: str):
    """Obtener objetos únicos detectados en un video específico"""
    try:
        video_data = get_video_data(video_name)
        if not video_data or not video_data.get("metadata"):
            return JSONResponse(
                content={"error": "Metadata not found", "status": "not_found"},
                status_code=404
            )

        metadata = video_data["metadata"]
        if not isinstance(metadata, list):
            return JSONResponse(
                content={"error": "Invalid metadata format", "status": "error"},
                status_code=500
            )

        # Obtener objetos únicos con sus frames
        unique_objects = {}
        for detection in metadata:
            frame_number = detection["frame"]
            for obj in detection.get("objects", []):
                label = obj["label"]
                if label not in unique_objects:
                    unique_objects[label] = []
                    
                unique_objects[label].append({
                    "frame": frame_number,
                    "confidence": obj["confidence"],
                    "timestamp": frame_number / 30,  # Asumiendo 30 FPS
                    "coordinates": obj["coordinates"]
                })

        # Convertir a lista ordenada y calcular estadísticas
        objects_list = []
        for label, occurrences in unique_objects.items():
            total_confidence = sum(o["confidence"] for o in occurrences)
            avg_confidence = total_confidence / len(occurrences)
            
            objects_list.append({
                "label": label,
                "occurrences": sorted(occurrences, key=lambda x: x["frame"]),
                "total_detections": len(occurrences),
                "average_confidence": round(avg_confidence, 3),
                "first_detection": min(occurrences, key=lambda x: x["frame"])["frame"],
                "last_detection": max(occurrences, key=lambda x: x["frame"])["frame"]
            })

        # Ordenar por número total de detecciones
        objects_list.sort(key=lambda x: x["total_detections"], reverse=True)
        
        return {
            "objects": objects_list,
            "status": "found",
            "total_unique_objects": len(objects_list)
        }

    except Exception as e:
        logger.error(f"Error getting video objects: {str(e)}")
        return JSONResponse(
            content={"error": str(e), "status": "error"},
            status_code=500
        )