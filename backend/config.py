import os
from pathlib import Path
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Obtener la ruta base del proyecto
BASE_DIR = Path(__file__).resolve().parent

# Configuración de Google Cloud Storage
GCS_PROJECT_ID = os.getenv('GCS_PROJECT_ID', 'video-detection-2024')
ORIGINAL_VIDEOS_BUCKET = os.getenv('ORIGINAL_VIDEOS_BUCKET', 'video-detection-original-2024')
PROCESSED_VIDEOS_BUCKET = os.getenv('PROCESSED_VIDEOS_BUCKET', 'video-detection-processed-2024')
HEATMAPS_BUCKET = os.getenv('HEATMAPS_BUCKET', 'video-detection-heatmaps-2024')
GOOGLE_APPLICATION_CREDENTIALS = os.getenv('GOOGLE_APPLICATION_CREDENTIALS', 'service-account-key.json')

# Configuración de PostgreSQL
POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'localhost')
POSTGRES_PORT = os.getenv('POSTGRES_PORT', '5432')
POSTGRES_DB = os.getenv('POSTGRES_DB', 'video_detection')
POSTGRES_USER = os.getenv('POSTGRES_USER', 'postgres')
POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD', 'angely')

# URL de la base de datos PostgreSQL
DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

# Configuración de directorios temporales para procesamiento
TEMP_DIR = BASE_DIR / "temp"
MODELS_DIR = BASE_DIR / "models"
TEMP_DIR.mkdir(exist_ok=True)
MODELS_DIR.mkdir(exist_ok=True)

# Configuración del modelo YOLO
MODEL_PATH = MODELS_DIR / "yolov8n.pt"

# Configuración de la API
API_HOST = "127.0.0.1"
API_PORT = 8000

# Configuraciones adicionales
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov'}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size