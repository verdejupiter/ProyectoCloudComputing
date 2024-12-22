from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from video_routes import video_router
from metadata_routes import metadata_router
from starlette.types import Scope, Receive, Send 
from heatmap import heatmap_router
from database import init_database
from config import *
import logging
from google.cloud import storage
from google.oauth2 import service_account

# Configurar logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = FastAPI(title="Sistema de Detección de Videos")

@app.get("/")
async def root():
    return {"message": "API is running"}

# Inicializar la base de datos al inicio
init_database()

# Inicializar cliente de Google Cloud Storage con credenciales
credentials = service_account.Credentials.from_service_account_file('service-account-key.json')
storage_client = storage.Client(credentials=credentials, project='video-detection-2024')

# Obtener buckets
original_bucket = storage_client.bucket(ORIGINAL_VIDEOS_BUCKET)
processed_bucket = storage_client.bucket(PROCESSED_VIDEOS_BUCKET)
heatmaps_bucket = storage_client.bucket(HEATMAPS_BUCKET)

class CustomStaticFiles(StaticFiles):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Personalizar el manejo de archivos estáticos para incluir CORS y streaming"""
        headers = [
            (b"access-control-allow-origin", b"*"),
            (b"access-control-allow-methods", b"GET, HEAD, OPTIONS"),
            (b"access-control-allow-headers", b"range, accept-ranges, content-type"),
            (b"access-control-expose-headers", b"content-range, content-length, accept-ranges"),
            (b"accept-ranges", b"bytes"),
        ]
        
        if scope["type"] == "http":
            path = scope["path"]
            if path.endswith((".mp4", ".webm")):
                new_headers = list(scope["headers"])
                new_headers.extend(headers)
                scope["headers"] = new_headers
        
        await super().__call__(scope, receive, send)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Configuración de directorio temporal
TEMP_DIR.mkdir(exist_ok=True)

# Montar directorio temporal para archivos procesados
app.mount("/temp", CustomStaticFiles(directory=str(TEMP_DIR)), name="temp")

# Registrar routers
app.include_router(video_router, prefix="/api/videos", tags=["Videos"])
app.include_router(metadata_router, prefix="/api/metadata", tags=["Metadata"])
app.include_router(heatmap_router, prefix="/api/heatmap", tags=["Heatmap"])

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy"}

# Manejadores de errores
@app.exception_handler(404)
async def custom_404_handler(request: Request, exc):
    return JSONResponse(
        status_code=404,
        content={"detail": "Not Found"}
    )

@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    logger.error(f"Internal error: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error"}
    )

@app.on_event("startup")
async def startup_event():
    """Verificar conexiones y crear recursos necesarios al iniciar"""
    try:
        # Verificar archivo de credenciales
        print("1. Verificando archivo de credenciales...")
        credentials_path = os.path.abspath('service-account-key.json')
        if not os.path.exists(credentials_path):
            raise Exception(f"Archivo de credenciales no encontrado en: {credentials_path}")
        
        # Verificar buckets
        print("2. Verificando buckets...")
        for bucket_name in [ORIGINAL_VIDEOS_BUCKET, PROCESSED_VIDEOS_BUCKET, HEATMAPS_BUCKET]:
            bucket = storage_client.bucket(bucket_name)
            if not bucket.exists():
                logger.warning(f"Bucket {bucket_name} no existe")
        
        # Verificar conexión a PostgreSQL
        print("3. Verificando conexión a PostgreSQL...")
        init_database()
        
        logger.info("Aplicación iniciada correctamente")
    except Exception as e:
        logger.error(f"Error durante el inicio de la aplicación: {str(e)}")
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Limpiar recursos al cerrar la aplicación"""
    try:
        # Limpiar archivos temporales
        import shutil
        if TEMP_DIR.exists():
            shutil.rmtree(str(TEMP_DIR))
        logger.info("Aplicación cerrada correctamente")
    except Exception as e:
        logger.error(f"Error durante el cierre de la aplicación: {str(e)}")