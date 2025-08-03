import os
import cv2
import base64
import redis
import sqlite3
from flask import Flask, render_template, request, jsonify
import numpy as np
from werkzeug.utils import secure_filename
from weapon_detector import WeaponDetector  # Ensure this file exists

app = Flask(__name__)  # FIXED from _name
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg'}

# Initialize detector once
detector = WeaponDetector()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

@app.route('/', methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        if 'file' not in request.files:
            return render_template('index.html', error="No file uploaded")
        
        file = request.files['file']
        if file.filename == '':
            return render_template('index.html', error="No file selected")
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            try:
                image = cv2.imread(filepath)
                image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                results = detector.detect(image_rgb)
                
                # Convert annotated image bytes to numpy array
                annotated_array = cv2.imdecode(
                    np.frombuffer(results['annotated_image'], np.uint8), 
                    cv2.IMREAD_COLOR
                )
                _, buffer = cv2.imencode('.jpg', annotated_array)
                annotated_img = base64.b64encode(buffer).decode('utf-8')
                
                return render_template('result.html',
                                       annotated_image=annotated_img,
                                       detections=list(zip(results['boxes'], results['scores'], results['classes'])))
            except Exception as e:
                return render_template('index.html', error=f"Error: {str(e)}")
            finally:
                if os.path.exists(filepath):
                    os.remove(filepath)
    
    return render_template('index.html')

@app.route('/api/detect', methods=['POST'])
def api_detect():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type'}), 400
    
    try:
        npimg = np.frombuffer(file.read(), np.uint8)
        image = cv2.imdecode(npimg, cv2.IMREAD_COLOR)
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        
        results = detector.detect(image_rgb)

        # Convert annotated image bytes to numpy array
        annotated_array = cv2.imdecode(
            np.frombuffer(results['annotated_image'], np.uint8), 
            cv2.IMREAD_COLOR
        )
        _, buffer = cv2.imencode('.jpg', annotated_array)
        annotated_img = base64.b64encode(buffer).decode('utf-8')
        
        return jsonify({
            'detections': {
                'count': len(results['boxes']),
                'boxes': results['boxes'],
                'scores': results['scores'],
                'classes': results['classes']
            },
            'annotated_image': annotated_img
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Add health check endpoints
@app.route('/health')
def health_check():
    """Health check endpoint for Docker and load balancer"""
    try:
        # Check Redis connection if using Redis
        try:
            redis_url = os.getenv('REDIS_URL')
            if redis_url:
                redis_client = redis.Redis.from_url(redis_url)
                redis_client.ping()
                redis_status = "healthy"
            else:
                redis_status = "not_configured"
        except Exception as e:
            redis_status = f"unhealthy: {str(e)}"
        
        # Check if model detector is working
        try:
            # Simple test to see if detector is initialized
            if hasattr(detector, 'model') or hasattr(detector, 'detect'):
                model_status = "healthy"
            else:
                model_status = "detector_not_initialized"
        except Exception as e:
            model_status = f"unhealthy: {str(e)}"
        
        # Check upload directory
        upload_status = "healthy" if os.path.exists(app.config['UPLOAD_FOLDER']) else "upload_dir_missing"
        
        # Overall health
        critical_services = [model_status, upload_status]
        overall_healthy = all([status == "healthy" for status in critical_services])
        
        response = {
            "status": "healthy" if overall_healthy else "unhealthy",
            "services": {
                "redis": redis_status,
                "model_detector": model_status,
                "upload_directory": upload_status,
                "detector_type": type(detector).__name__
            },
            "version": "1.0"
        }
        
        return jsonify(response), 200 if overall_healthy else 503
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "version": "1.0"
        }), 503

@app.route('/metrics')
def metrics():
    """Prometheus metrics endpoint (basic implementation)"""
    # You can implement proper Prometheus metrics here
    # For now, just return basic info
    return """
# HELP weapon_detection_requests_total Total number of requests
# TYPE weapon_detection_requests_total counter
weapon_detection_requests_total 0

# HELP weapon_detection_processing_time_seconds Time spent processing requests
# TYPE weapon_detection_processing_time_seconds histogram
weapon_detection_processing_time_seconds_bucket{le="0.1"} 0
weapon_detection_processing_time_seconds_bucket{le="0.5"} 0
weapon_detection_processing_time_seconds_bucket{le="1.0"} 0
weapon_detection_processing_time_seconds_bucket{le="+Inf"} 0
weapon_detection_processing_time_seconds_count 0
weapon_detection_processing_time_seconds_sum 0
""", 200, {'Content-Type': 'text/plain'}

# Always make sure upload folder exists (even if running under Gunicorn)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)