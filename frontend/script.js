const API_URL = 'http://35.226.34.108';

let processingMonitorInterval = null;
let streamInterval = null;
let currentProgress = 0;

// Event Listeners
document.addEventListener('DOMContentLoaded', () => {
    const videoSelect = document.getElementById('video-select');
    const uploadInput = document.getElementById('video-upload');
    
    loadVideoList();
    
    videoSelect.addEventListener('change', () => {
        console.log('Video seleccionado cambiado');
        if (processingMonitorInterval) {
            clearInterval(processingMonitorInterval);
        }
        clearDisplays();
        currentProgress = 0;
        checkExistingProcessedVideo();
        stopStreamSimulation();
    });

    uploadInput.addEventListener('change', () => {
        const file = uploadInput.files[0];
        if (file) {
            const fileSize = file.size / (1024 * 1024); // Convert to MB
            if (fileSize > 16) {
                showError('El archivo excede el límite de 16MB');
                uploadInput.value = '';
            }
        }
    });
});

// Funciones de carga inicial y subida
async function uploadVideo() {
    const fileInput = document.getElementById('video-upload');
    const file = fileInput.files[0];
    
    if (!file) {
        showError('Por favor seleccione un video');
        return;
    }

    // Verificar extensión
    const validExtensions = ['.mp4', '.avi', '.mov'];
    const fileExtension = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
    if (!validExtensions.includes(fileExtension)) {
        showError('Formato de archivo no válido. Use MP4, AVI o MOV');
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch(`${API_URL}/api/videos/upload`, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Error al subir el video');
        }

        await loadVideoList();
        showCompletionMessage('Video subido exitosamente');
        fileInput.value = '';
        
        // Actualizar estadísticas de almacenamiento
        updateStorageInfo();
    } catch (error) {
        console.error('Error:', error);
        showError(error.message);
    }
}

async function loadVideoList() {
    try {
        const response = await fetch(`${API_URL}/api/videos/available-videos`);
        if (!response.ok) throw new Error('Error al obtener la lista de videos');
        const data = await response.json();
        
        const select = document.getElementById('video-select');
        select.innerHTML = '<option value="">Seleccione un video</option>';
        
        if (data.videos && Array.isArray(data.videos)) {
            data.videos.forEach(video => {
                const option = document.createElement('option');
                option.value = video;
                option.textContent = video;
                select.appendChild(option);
            });
        }

        // Actualizar estadísticas
        updateStorageInfo();
    } catch (error) {
        console.error('Error:', error);
        showError('Error al cargar la lista de videos: ' + error.message);
    }
}

// Funciones de procesamiento
async function processVideo() {
    const videoName = document.getElementById('video-select').value;
    if (!videoName) {
        showError('Seleccione un video');
        return;
    }

    try {
        clearDisplays();
        const progressContainer = document.getElementById('progress-container');
        progressContainer.style.display = 'block';
        updateProgress(0, 'Iniciando procesamiento...');

        const response = await fetch(`${API_URL}/api/videos/process/${videoName}`);
        const data = await response.json();

        if (data.status === 'error') {
            showError(data.message || 'Error iniciando el procesamiento');
            return;
        }

        if (data.status === 'completed') {
            await showResults(videoName);
            return;
        }

        startProgressMonitoring(videoName);
        updateProcessingStatus('Procesando');
        recordProcessingStartTime();

    } catch (error) {
        console.error('Error:', error);
        showError('Error al procesar el video: ' + error.message);
        hideProgress();
    }
}

function startProgressMonitoring(videoName) {
    if (processingMonitorInterval) {
        clearInterval(processingMonitorInterval);
    }

    let failedAttempts = 0;
    const maxFailedAttempts = 5;
    let completionShown = false;

    const checkStatus = async () => {
        try {
            const response = await fetch(`${API_URL}/api/videos/status/${videoName}`);
            const data = await response.json();

            if (data.status === 'error') {
                clearInterval(processingMonitorInterval);
                showError(data.message || 'Error en el procesamiento');
                hideProgress();
                updateProcessingStatus('Error');
                return;
            }

            if (data.progress >= currentProgress) {
                currentProgress = data.progress;
                updateProgress(currentProgress, getStepMessage(data.step));

                if (data.status === 'completed' && !completionShown) {
                    completionShown = true;
                    clearInterval(processingMonitorInterval);
                    updateProgress(100, '¡Proceso completado! (100%)');
                    showCompletionMessage();
                    updateProcessingStatus('Completado');
                    updateProcessingTime();
                    
                    setTimeout(async () => {
                        await showResults(videoName);
                        hideProgress();
                    }, 1500);
                }
            }

            failedAttempts = 0;

        } catch (error) {
            console.error('Error monitoreando estado:', error);
            failedAttempts++;

            if (failedAttempts >= maxFailedAttempts) {
                clearInterval(processingMonitorInterval);
                showError('Error de conexión al monitorear el proceso');
                hideProgress();
                updateProcessingStatus('Error');
            }
        }
    };

    checkStatus();
    processingMonitorInterval = setInterval(checkStatus, 1000);
}

// Funciones de UI y actualización
function updateProgress(progress, message) {
    const progressFill = document.getElementById('progress-fill');
    const progressText = document.getElementById('progress-text');
    
    progressFill.style.width = `${progress}%`;
    progressText.textContent = message || `${progress}%`;
}

function hideProgress() {
    const progressContainer = document.getElementById('progress-container');
    progressContainer.style.display = 'none';
}

function getStepMessage(step) {
    const messages = {
        'starting': 'Iniciando procesamiento...',
        'generating_metadata': 'Analizando video y generando metadata (33%)...',
        'metadata_complete': 'Metadata generada (33%)',
        'processing_video': 'Procesando video con detecciones (66%)...',
        'video_complete': 'Video procesado (66%)',
        'generating_heatmap': 'Generando mapa de calor (90%)...',
        'completed': '¡Proceso completado! (100%)'
    };
    return messages[step] || 'Procesando...';
}

// Funciones de resultados y visualización
async function showResults(videoName) {
    try {
        const response = await fetch(`${API_URL}/api/videos/status/${videoName}`);
        const data = await response.json();
        
        if (data.status !== 'completed') {
            throw new Error('Los archivos no están listos');
        }
        
        if (data.processed_video_path) {
            await showProcessedVideo(videoName);
        }
        
        if (data.heatmap_path) {
            await showHeatmap(videoName);
        }
        
        await loadVideoObjects(videoName);
        await updateDetectionStats(videoName);
        
    } catch (error) {
        console.error('Error mostrando resultados:', error);
        showError(error.message);
    }
}

async function showProcessedVideo(videoName) {
    const videoPlayer = document.getElementById('video-player');
    const videoError = document.getElementById('video-error');
    
    videoPlayer.style.display = 'none';
    videoError.style.display = 'none';
    
    try {
        const response = await fetch(`${API_URL}/api/videos/stream/${videoName}`);
        if (!response.ok) throw new Error('Error al cargar el video');
        
        const blob = await response.blob();
        const videoUrl = URL.createObjectURL(blob);
        
        videoPlayer.src = videoUrl;
        videoPlayer.style.display = 'block';
        
        videoPlayer.addEventListener('loadeddata', () => {
            videoPlayer.style.display = 'block';
        });
        
    } catch (error) {
        console.error('Error:', error);
        videoError.textContent = error.message;
        videoError.style.display = 'block';
    }
}

async function showHeatmap(videoName) {
    try {
        const heatmapContainer = document.getElementById('heatmap-container');
        // Mostrar estado de carga
        heatmapContainer.innerHTML = '<p>Cargando mapa de calor...</p>';
        
        // Primera petición para verificar el estado
        const response = await fetch(`${API_URL}/api/heatmap/${videoName}`);
        const data = await response.json();
        
        console.log('Respuesta del servidor heatmap:', data); // Debug log
        
        if (data.status === 'ready') {
            try {
                // Segunda petición para obtener la imagen
                const heatmapResponse = await fetch(`${API_URL}/api/heatmap/download/${videoName}`, {
                    headers: {
                        'Cache-Control': 'no-cache',
                        'Pragma': 'no-cache'
                    }
                });
                
                if (!heatmapResponse.ok) {
                    throw new Error(`HTTP error! status: ${heatmapResponse.status}`);
                }
                
                const blob = await heatmapResponse.blob();
                if (blob.size === 0) {
                    throw new Error('Blob vacío recibido');
                }
                
                const imageUrl = URL.createObjectURL(blob);
                
                heatmapContainer.innerHTML = `
                    <img src="${imageUrl}"
                         alt="Mapa de calor"
                         style="max-width: 100%; height: auto; display: block; margin: 0 auto;"
                         onload="console.log('Imagen cargada correctamente')"
                         onerror="console.error('Error al cargar la imagen del heatmap')">
                `;
            } catch (downloadError) {
                console.error('Error al descargar el heatmap:', downloadError);
                heatmapContainer.innerHTML = '<p class="error-text">Error al cargar el mapa de calor: ' + downloadError.message + '</p>';
            }
        } else if (data.status === 'processing') {
            heatmapContainer.innerHTML = '<p>Generando mapa de calor...</p>';
        } else {
            throw new Error('Estado no válido: ' + data.status);
        }
    } catch (error) {
        console.error('Error cargando heatmap:', error);
        const heatmapContainer = document.getElementById('heatmap-container');
        heatmapContainer.innerHTML = '<p class="error-text">Error al cargar el mapa de calor: ' + error.message + '</p>';
    }
}

// Funciones de streaming
async function startStreamSimulation() {
    const videoName = document.getElementById('video-select').value;
    if (!videoName) {
        showError('Seleccione un video primero');
        return;
    }

    const streamView = document.getElementById('stream-view');
    const streamButton = document.getElementById('stream-button');
    const stopStreamButton = document.getElementById('stop-stream-button');

    try {
        // Verificar primero si el video existe
        const statusResponse = await fetch(`${API_URL}/api/videos/status/${videoName}`);
        const statusData = await statusResponse.json();
        
        if (statusData.status === 'error') {
            showError('Error: Video no disponible para streaming');
            return;
        }

        streamView.style.display = 'block';
        streamView.classList.add('loading-stream');
        streamButton.style.display = 'none';
        stopStreamButton.style.display = 'inline-block';

        streamInterval = setInterval(async () => {
            try {
                const response = await fetch(`${API_URL}/api/videos/rtsp/stream/${videoName}?t=${Date.now()}`);
                if (!response.ok) throw new Error('Error en el stream');
                
                const blob = await response.blob();
                const url = URL.createObjectURL(blob);
                
                // Liberar URL anterior si existe
                if (streamView.src) {
                    URL.revokeObjectURL(streamView.src);
                }
                
                streamView.src = url;
                streamView.classList.remove('loading-stream');
            } catch (error) {
                console.error('Error en stream:', error);
                stopStreamSimulation();
                showError('Error en el streaming: ' + error.message);
            }
        }, 100);
    } catch (error) {
        console.error('Error iniciando stream:', error);
        showError('Error iniciando el streaming');
    }
}

function stopStreamSimulation() {
    if (streamInterval) {
        clearInterval(streamInterval);
        streamInterval = null;
    }

    const streamView = document.getElementById('stream-view');
    const streamButton = document.getElementById('stream-button');
    const stopStreamButton = document.getElementById('stop-stream-button');

    streamView.style.display = 'none';
    streamView.classList.remove('loading-stream');
    streamButton.style.display = 'inline-block';
    stopStreamButton.style.display = 'none';
}

// Funciones de búsqueda y objetos
async function loadVideoObjects(videoName) {
    const objectSelect = document.getElementById('object-search');
    objectSelect.innerHTML = '<option value="">Seleccione un objeto</option>';
    
    try {
        const response = await fetch(`${API_URL}/api/metadata/objects/${videoName}`);
        const data = await response.json();
        
        if (data.status === 'found' && data.objects) {
            data.objects.forEach(obj => {
                const option = document.createElement('option');
                option.value = obj.label;
                option.textContent = `${obj.label} (${obj.total_detections} detecciones)`;
                objectSelect.appendChild(option);
            });
        }
    } catch (error) {
        console.error('Error cargando objetos:', error);
        showError('Error cargando lista de objetos');
    }
}

async function searchObjects() {
    const videoName = document.getElementById('video-select').value;
    const objectLabel = document.getElementById('object-search').value;
    const searchResults = document.getElementById('search-results');
    
    if (!videoName || !objectLabel) {
        showError('Seleccione un video y un objeto');
        return;
    }
    
    try {
        const response = await fetch(`${API_URL}/api/metadata/objects/${videoName}`);
        const data = await response.json();
        
        if (data.status === 'found') {
            const objectData = data.objects.find(obj => obj.label === objectLabel);
            if (objectData) {
                const resultsHTML = objectData.occurrences.map(occurrence => `
                    <div class="result-card">
                        <div class="result-info">
                            <span>Frame: ${occurrence.frame}</span>
                            <span>Tiempo: ${occurrence.timestamp.toFixed(2)}s</span>
                            <span>Confianza: ${(occurrence.confidence * 100).toFixed(1)}%</span>
                        </div>
                        <button class="jump-button" onclick="jumpToTimestamp(${occurrence.timestamp})">
                            Ir al momento
                        </button>
                    </div>
                `).join('');
                
                searchResults.innerHTML = `
                    <h3>Resultados para "${objectLabel}"</h3>
                    <div class="results-container">
                        ${resultsHTML}
                    </div>
                `;
            } else {
                searchResults.innerHTML = `<p>No se encontró el objeto "${objectLabel}" en este video</p>`;
            }
        }
    } catch (error) {
        console.error('Error en búsqueda:', error);
        showError('Error al buscar objetos');
    }
}

// Funciones de utilidad
function jumpToTimestamp(timestamp) {
    const videoPlayer = document.getElementById('video-player');
    if (videoPlayer) {
        videoPlayer.currentTime = timestamp;
        videoPlayer.play();
    }
}

function showError(message) {
    const errorDiv = document.createElement('div');
    errorDiv.className = 'error-message';
    errorDiv.textContent = message;
    
    const container = document.querySelector('.container');
    if (container) {
        container.insertBefore(errorDiv, container.firstChild);
        setTimeout(() => errorDiv.remove(), 5000);
    }
}

function showCompletionMessage(message = 'Proceso completado exitosamente') {
    const container = document.querySelector('.container');
    const messageDiv = document.createElement('div');
    messageDiv.className = 'success-message';
    messageDiv.innerHTML = `
        <div class="success-content">
            <div class="success-icon">✓</div>
            <div class="success-text">
                <h4>¡Éxito!</h4>
                <p>${message}</p>
            </div>
        </div>
    `;
    
    container.insertBefore(messageDiv, container.firstChild);
    setTimeout(() => messageDiv.classList.add('show'), 100);
    setTimeout(() => {
        messageDiv.classList.add('hide');
        setTimeout(() => messageDiv.remove(), 500);
    }, 5000);
}

function clearDisplays() {
    const videoPlayer = document.getElementById('video-player');
    const heatmapContainer = document.getElementById('heatmap-container');
    const progressContainer = document.getElementById('progress-container');
    const videoError = document.getElementById('video-error');
    const searchResults = document.getElementById('search-results');
    const streamView = document.getElementById('stream-view');

    if (processingMonitorInterval) {
        clearInterval(processingMonitorInterval);
    }
    if (streamInterval) {
        clearInterval(streamInterval);
    }

    videoPlayer.style.display = 'none';
    videoPlayer.src = '';
    heatmapContainer.innerHTML = '';
    progressContainer.style.display = 'none';
    searchResults.innerHTML = '';
    streamView.style.display = 'none';
    
    if (videoError) {
        videoError.style.display = 'none';
    }
}

async function checkExistingProcessedVideo() {
    const videoName = document.getElementById('video-select').value;
    if (!videoName) return;
    
    try {
        const response = await fetch(`${API_URL}/api/videos/status/${videoName}`);
        const data = await response.json();
        
        if (data.status === 'completed') {
            await showResults(videoName);
            updateProcessingStatus('Completado');
        }
    } catch (error) {
        console.error('Error verificando video:', error);
        showError('Error al verificar el estado del video');
    }
}

// Funciones de estadísticas
async function updateDetectionStats(videoName) {
    try {
        const response = await fetch(`${API_URL}/api/metadata/objects/${videoName}`);
        const data = await response.json();
        
        if (data.status === 'found') {
            const totalObjects = data.objects.reduce((sum, obj) => sum + obj.total_detections, 0);
            const uniqueObjects = data.objects.length;
            const avgConfidence = data.objects.reduce((sum, obj) => sum + obj.average_confidence, 0) / uniqueObjects;

            document.getElementById('total-objects').textContent = totalObjects;
            document.getElementById('unique-objects').textContent = uniqueObjects;
            document.getElementById('avg-confidence').textContent = `${(avgConfidence * 100).toFixed(1)}%`;
        }
    } catch (error) {
        console.error('Error actualizando estadísticas:', error);
    }
}

function updateProcessingStatus(status) {
    const statusElement = document.getElementById('processing-status');
    if (statusElement) {
        statusElement.textContent = status;
    }
}

function recordProcessingStartTime() {
    window.processingStartTime = Date.now();
    updateProcessingTime();
}

function updateProcessingTime() {
    if (window.processingStartTime) {
        const duration = (Date.now() - window.processingStartTime) / 1000; // en segundos
        const timeElement = document.getElementById('processing-time');
        if (timeElement) {
            timeElement.textContent = `${duration.toFixed(1)} segundos`;
        }
    }
}

async function updateStorageInfo() {
    try {
        const response = await fetch(`${API_URL}/api/videos/available-videos`);
        const data = await response.json();
        
        const storageElement = document.getElementById('storage-info');
        if (storageElement) {
            const totalVideos = data.videos ? data.videos.length : 0;
            storageElement.textContent = `${totalVideos} videos almacenados`;
        }
    } catch (error) {
        console.error('Error actualizando información de almacenamiento:', error);
    }
}