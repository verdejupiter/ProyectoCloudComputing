import psycopg2
from psycopg2.extras import Json
import logging
import time
from config import DATABASE_URL

logger = logging.getLogger(__name__)

def get_db_connection():
    """Crear una conexión a la base de datos PostgreSQL"""
    try:
        return psycopg2.connect(DATABASE_URL)
    except Exception as e:
        logger.error(f"Error conectando a la base de datos: {str(e)}")
        raise

def init_database():
    """Inicializar la base de datos si no existe"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Crear tabla si no existe
        cur.execute('''
            CREATE TABLE IF NOT EXISTS metadata (
                id SERIAL PRIMARY KEY,
                video_name VARCHAR(255) NOT NULL UNIQUE,
                metadata JSONB NOT NULL,
                processed_video_path VARCHAR(255),
                heatmap_path VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        logger.info("Base de datos inicializada correctamente")
    except Exception as e:
        logger.error(f"Error inicializando la base de datos: {str(e)}")
        raise
    finally:
        cur.close()
        conn.close()

def insert_or_update_video_data(video_name, metadata=None, processed_video_path=None, heatmap_path=None):
    """Insertar o actualizar datos del video en PostgreSQL"""
    logger.info(f"Attempting to insert/update data for {video_name}")
    logger.info(f"Metadata present: {metadata is not None}")
    logger.info(f"Processed path: {processed_video_path}")
    logger.info(f"Heatmap path: {heatmap_path}")

    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            
            # Verificar si el registro existe
            cur.execute("SELECT id FROM metadata WHERE video_name = %s", (video_name,))
            existing = cur.fetchone()

            if existing:
                # Construir la consulta de actualización dinámicamente
                update_parts = []
                update_values = []

                if metadata is not None:
                    update_parts.append("metadata = %s")
                    update_values.append(Json(metadata) if isinstance(metadata, dict) else metadata)

                if processed_video_path is not None:
                    update_parts.append("processed_video_path = %s")
                    update_values.append(processed_video_path)

                if heatmap_path is not None:
                    update_parts.append("heatmap_path = %s")
                    update_values.append(heatmap_path)

                if update_parts:
                    query = f"""
                        UPDATE metadata 
                        SET {', '.join(update_parts)}
                        WHERE video_name = %s
                    """
                    cur.execute(query, tuple(update_values + [video_name]))
            else:
                # Insertar nuevo registro
                cur.execute("""
                    INSERT INTO metadata (video_name, metadata, processed_video_path, heatmap_path)
                    VALUES (%s, %s, %s, %s)
                """, (
                    video_name,
                    Json(metadata) if isinstance(metadata, dict) else metadata,
                    processed_video_path,
                    heatmap_path
                ))

            conn.commit()
            return True

        except Exception as e:
            logger.error(f"Error en insert_or_update_video_data: {str(e)}")
            retry_count += 1
            if retry_count == max_retries:
                return False
            time.sleep(1)
        finally:
            cur.close()
            conn.close()

def get_video_data(video_name):
    """Obtener datos de un video específico"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT video_name, metadata, processed_video_path, heatmap_path, created_at
            FROM metadata 
            WHERE video_name = %s
        """, (video_name,))
        
        result = cur.fetchone()
        if result:
            return {
                "video_name": result[0],
                "metadata": result[1],
                "processed_video_path": result[2],
                "heatmap_path": result[3],
                "created_at": result[4]
            }
        return None

    except Exception as e:
        logger.error(f"Error en get_video_data: {str(e)}")
        return None
    finally:
        cur.close()
        conn.close()

def check_video_paths(video_name):
    """Función de debug para verificar las rutas en la base de datos"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT processed_video_path, heatmap_path
            FROM metadata 
            WHERE video_name = %s
        """, (video_name,))
        
        result = cur.fetchone()
        
        if result:
            logger.info(f"Rutas en DB para {video_name}:")
            logger.info(f"Video procesado: {result[0]}")
            logger.info(f"Heatmap: {result[1]}")
        
        return result

    except Exception as e:
        logger.error(f"Error en check_video_paths: {str(e)}")
        return None
    finally:
        cur.close()
        conn.close()