from database import init_database, insert_or_update_video_data, get_video_data

# Inicializar la base de datos
init_database()

# Insertar datos de prueba
test_data = {
    "video_name": "test.mp4",
    "metadata": {"test": True},
    "processed_video_path": "/path/to/processed.mp4",
    "heatmap_path": "/path/to/heatmap.png"
}

success = insert_or_update_video_data(
    test_data["video_name"],
    test_data["metadata"],
    test_data["processed_video_path"],
    test_data["heatmap_path"]
)

if success:
    print("Datos insertados correctamente")
    # Recuperar los datos
    data = get_video_data("test.mp4")
    print("Datos recuperados:", data)