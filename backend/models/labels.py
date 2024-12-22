from ultralytics import YOLO

model = YOLO(r'C:\Users\Usuario\Documents\proyectoCloud\backend\models\yolov8n.pt')

print("Etiquetas disponibles en el modelo preentrenado:")
print(model.names)