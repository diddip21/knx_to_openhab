import os
import sys
import json
import uuid
import time
try:
    from flask import Flask, request, jsonify, send_from_directory, render_template, stream_with_context, Response
    from werkzeug.utils import secure_filename
    FLASK_AVAILABLE = True
except Exception:
    # allow module import when Flask is not installed (for static analysis/tests)
    Flask = None
    request = None
    jsonify = lambda x: x
    render_template = lambda n: f"Template {n} not available"
    stream_with_context = lambda g: g
    Response = object
    secure_filename = lambda n: n
    FLASK_AVAILABLE = False

from .jobs import JobManager
from .service_manager import restart_service
from .storage import load_config

cfg = load_config()

if FLASK_AVAILABLE:
    app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), '..', 'templates'))
    app.config['UPLOAD_FOLDER'] = cfg.get('jobs_dir', './var/lib/knx_to_openhab')
    job_mgr = JobManager(cfg)

    # Basic HTTP auth (simple implementation) -------------------------------------------------
    from base64 import b64decode

    def _auth_failed():
        return ("Unauthorized", 401, {"WWW-Authenticate": "Basic realm=\"KNX UI\""})

    def _check_auth_header(auth_header: str) -> bool:
        try:
            if not auth_header or not auth_header.lower().startswith('basic '):
                return False
            token = auth_header.split(None, 1)[1]
            decoded = b64decode(token).decode('utf-8')
            user, pwd = decoded.split(':', 1)
            acfg = cfg.get('auth', {})
            return acfg.get('user') == user and acfg.get('password') == pwd
        except Exception:
            return False

    @app.before_request
    def require_auth():
        # if auth disabled, allow
        acfg = cfg.get('auth', {})
        if not acfg.get('enabled'):
            return None
        # allow static files without auth (CSS/JS/templates served under /static)
        path = request.path or ''
        if path.startswith('/static'):
            return None
        # health/status endpoint allowed
        if path == '/api/status':
            return None
        auth = request.headers.get('Authorization')
        if _check_auth_header(auth):
            return None
        return _auth_failed()


    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/api/upload', methods=['POST'])
    def upload():
        if 'file' not in request.files:
            return jsonify({'error': 'no file part'}), 400
        f = request.files['file']
        if f.filename == '':
            return jsonify({'error': 'no selected file'}), 400
        fn = secure_filename(f.filename)
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        saved_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{uuid.uuid4().hex}-{fn}")
        f.save(saved_path)
        job = job_mgr.create_job(saved_path, original_name=fn)
        return jsonify(job), 201

    @app.route('/api/jobs', methods=['GET'])
    def jobs():
        return jsonify(job_mgr.list_jobs())

    @app.route('/api/job/<job_id>', methods=['GET'])
    def job_detail(job_id):
        j = job_mgr.get_job(job_id)
        if not j:
            return jsonify({'error': 'not found'}), 404
        return jsonify(j)

    @app.route('/api/job/<job_id>/events')
    def job_events(job_id):
        q = job_mgr.get_queue(job_id)
        if q is None:
            return jsonify({'error': 'not found'}), 404

        def event_stream():
            while True:
                msg = q.get()
                if msg is None:
                    yield 'event: done\ndata: {}\n\n'.format(json.dumps({'status': 'done'}))
                    break
                yield 'data: {}\n\n'.format(json.dumps(msg))

        return Response(stream_with_context(event_stream()), mimetype='text/event-stream')

    @app.route('/api/job/<job_id>/rollback', methods=['POST'])
    def rollback(job_id):
        data = request.get_json() or {}
        backup = data.get('backup')
        try:
            ok, out = job_mgr.rollback(job_id, backup)
            return jsonify({'ok': ok, 'output': out})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/service/restart', methods=['POST'])
    def service_restart():
        data = request.get_json() or {}
        svc = data.get('service')
        if not svc:
            return jsonify({'error': 'service missing'}), 400
        ok, out = restart_service(svc)
        return jsonify({'ok': ok, 'output': out})

    @app.route('/api/status')
    def status():
        s = job_mgr.status()
        return jsonify(s)

    if __name__ == '__main__':
        host = cfg.get('bind_host', '0.0.0.0')
        port = cfg.get('port', 8080)
        app.run(host=host, port=port)
else:
    # Provide a minimal message when Flask is not available
    if __name__ == '__main__':
        print('Flask is not installed. Please install requirements to run the server.')
