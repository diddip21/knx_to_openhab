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
from .service_manager import restart_service, get_service_status
from .storage import load_config
from .updater import Updater

cfg = load_config()

if FLASK_AVAILABLE:
    app = Flask(__name__,
                template_folder=os.path.join(os.path.dirname(__file__), '..', 'templates'),
                static_folder=os.path.join(os.path.dirname(__file__), '..', 'static'),
                static_url_path='/static')
    app.config['UPLOAD_FOLDER'] = cfg.get('jobs_dir', './var/lib/knx_to_openhab')
    job_mgr = JobManager(cfg)
    updater = Updater(base_path=os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

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
        password = request.form.get('password') or None
        job = job_mgr.create_job(saved_path, original_name=fn, password=password)
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

    @app.route('/api/job/<job_id>', methods=['PATCH'])
    def update_job(job_id):
        data = request.get_json() or {}
        try:
            ok = job_mgr.update_job(job_id, data)
            if ok:
                return jsonify({'ok': True})
            else:
                return jsonify({'error': 'not found'}), 404
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/job/<job_id>/rerun', methods=['POST'])
    def rerun_job(job_id):
        """Create a new job based on an existing job's input."""
        job = job_mgr.get_job(job_id)
        if not job:
            return jsonify({'error': 'job not found'}), 404
        
        input_path = job.get('input')
        if not input_path or not os.path.exists(input_path):
            return jsonify({'error': 'original input file not found'}), 404
            
        try:
            # Create a new job with the same input and password
            new_job = job_mgr.create_job(input_path, original_name=job.get('name'), password=job.get('password'))
            return jsonify(new_job), 201
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/job/<job_id>/file/diff', methods=['GET'])
    def job_file_diff(job_id):
        path = request.args.get('path')
        if not path:
            return jsonify({'error': 'path required'}), 400
        
        # path is like "items/knx.items" (relative to openhab root)
        # normalize path
        path = path.replace('\\', '/')
        if path.startswith('openhab/'):
            path = path[8:]
            
        diff = job_mgr.get_file_diff(job_id, path)
        if diff is None:
            return jsonify({'error': 'diff not available'}), 404
        return jsonify(diff)

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

    @app.route('/api/job/<job_id>', methods=['DELETE'])
    def delete_job(job_id):
        try:
            ok = job_mgr.delete_job(job_id)
            return jsonify({'ok': ok})
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

    @app.route('/api/service/<service_name>/status', methods=['GET'])
    def service_status(service_name):
        status = get_service_status(service_name)
        return jsonify(status)

    @app.route('/api/status')
    def status():
        s = job_mgr.status()
        return jsonify(s)

    @app.route('/api/version', methods=['GET'])
    def get_version():
        """Get current version information."""
        try:
            version_info = updater.get_current_version()
            return jsonify(version_info)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/version/check', methods=['GET'])
    def check_version():
        """Check for available updates from GitHub."""
        try:
            update_info = updater.check_for_updates()
            return jsonify(update_info)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/version/update', methods=['POST'])
    def trigger_update():
        """Trigger the self-update process."""
        try:
            # Check if running on Windows (dev) or Linux (prod)
            if sys.platform == 'win32':
                return jsonify({
                    'status': 'simulated',
                    'message': 'Update simulation: Script would run on Linux.'
                })
            
            success, message = updater.trigger_update()
            if success:
                return jsonify({
                    'status': 'updating',
                    'message': message
                })
            else:
                return jsonify({'error': message}), 500
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/version/log', methods=['GET'])
    def get_update_log():
        """Get the log of the last update attempt."""
        return jsonify({'log': updater.get_update_log()})


    @app.route('/api/file/preview', methods=['GET'])
    def file_preview():
        """Preview a generated OpenHAB configuration file."""
        file_path = request.args.get('path', '')
        backup_name = request.args.get('backup', None)  # Optional: fetch from backup
        
        if not file_path:
            return jsonify({'error': 'path parameter required'}), 400
        
        # Security: Only allow files within openhab directory
        openhab_base = os.path.abspath(cfg.get('openhab_path', 'openhab'))
        requested_path = os.path.abspath(file_path)
        
        # Check if requested path is within openhab directory
        if not requested_path.startswith(openhab_base):
            return jsonify({'error': 'access denied: path outside openhab directory'}), 403
        
        # If backup specified, extract file from backup
        if backup_name:
            backups_dir = cfg.get('backups_dir', './var/backups/knx_to_openhab')
            backup_path = os.path.join(backups_dir, backup_name)
            
            if not os.path.isfile(backup_path):
                return jsonify({'error': 'backup not found'}), 404
            
            try:
                # Get relative path within openhab directory
                rel_path = os.path.relpath(requested_path, openhab_base)
                # Normalize to forward slashes for tarfile
                rel_path = rel_path.replace('\\', '/')
                
                # Extract file from backup
                with tarfile.open(backup_path, 'r:gz') as tar:
                    # Backup contains directory named 'openhab', so prepend it
                    member_path = f"openhab/{rel_path}"
                    try:
                        member = tar.getmember(member_path)
                        f = tar.extractfile(member)
                        if f:
                            content = f.read().decode('utf-8', errors='replace')
                            # Limit content size
                            if len(content) > 1024 * 1024:
                                content = content[:1024 * 1024] + '\n\n... [Content truncated, file too large]'
                            return jsonify({
                                'path': file_path,
                                'content': content,
                                'size': member.size,
                                'from_backup': True
                            })
                        else:
                            return jsonify({'error': 'file not found in backup'}), 404
                    except KeyError:
                        return jsonify({'error': 'file not found in backup'}), 404
            except Exception as e:
                return jsonify({'error': f'failed to read file from backup: {str(e)}'}), 500
        
        # Otherwise, read current file
        if not os.path.isfile(requested_path):
            return jsonify({'error': 'file not found'}), 404
        
        # Read file content
        try:
            with open(requested_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            
            # Limit content size to prevent memory issues (max 1MB)
            if len(content) > 1024 * 1024:
                content = content[:1024 * 1024] + '\n\n... [Content truncated, file too large]'
            
            return jsonify({
                'path': file_path,
                'content': content,
                'size': os.path.getsize(requested_path),
                'from_backup': False
            })
        except Exception as e:
            return jsonify({'error': f'failed to read file: {str(e)}'}), 500

    @app.route('/api/config', methods=['GET'])
    def get_config():
        """Get the current configuration."""
        try:
            # Load the main config.json file which contains knxproject_to_openhab settings
            main_config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config.json')
            with open(main_config_path, 'r', encoding='utf-8') as f:
                main_config = json.load(f)
            return jsonify(main_config)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/config', methods=['POST'])
    def set_config():
        """Update the configuration."""
        try:
            new_config = request.get_json()
            if not new_config:
                return jsonify({'error': 'No config data provided'}), 400
            
            # Validate that it's a dict
            if not isinstance(new_config, dict):
                return jsonify({'error': 'Config must be a JSON object'}), 400
            
            # Save to the main config file (which contains knxproject_to_openhab settings)
            main_config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config.json')
            with open(main_config_path, 'w', encoding='utf-8') as f:
                json.dump(new_config, f, indent=2, ensure_ascii=False)
            
            return jsonify({'message': 'Configuration updated successfully'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/config/schema', methods=['GET'])
    def get_config_schema():
        """Get the configuration schema."""
        try:
            schema_path = os.path.join(os.path.dirname(__file__), 'config_schema.json')
            with open(schema_path, 'r', encoding='utf-8') as f:
                schema = json.load(f)
            return jsonify(schema)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/project/preview', methods=['POST'])
    def project_preview():
        """Preview a KNX project structure without processing it."""
        if 'file' not in request.files:
            return jsonify({'error': 'no file part'}), 400
        f = request.files['file']
        if f.filename == '':
            return jsonify({'error': 'no selected file'}), 400
        
        # Save to temporary location
        fn = secure_filename(f.filename)
        temp_path = os.path.join(app.config['UPLOAD_FOLDER'], f"temp_{uuid.uuid4().hex}_{fn}")
        f.save(temp_path)
        
        try:
            password = request.form.get('password') or None
            
            # Load project (json dump or parse knxproj)
            if temp_path.lower().endswith('.json'):
                with open(temp_path, 'r', encoding='utf8') as file:
                    project = json.load(file)
            else:
                # Parse knxproj archive using XKNXProj
                from xknxproject.xknxproj import XKNXProj
                knxproj = XKNXProj(path=temp_path, password=password, language='de-DE')
                project = knxproj.parse()
            
            # Extract project metadata
            import importlib
            knxmod = importlib.import_module('knxproject_to_openhab')
            
            # Get building structure
            building = knxmod.create_building(project)
            addresses = knxmod.get_addresses(project)
            house = knxmod.put_addresses_in_building(building, addresses, project)
            
            # Extract metadata
            project_name = house[0].get('name_long') if house else None
            gateway_ip = knxmod.get_gateway_ip(project)
            homekit_enabled = knxmod.is_homekit_enabled(project)
            alexa_enabled = knxmod.is_alexa_enabled(project)
            
            # Detect unknown items (addresses without proper room/floor assignments or with default names)
            unknown_items = []
            for addr in addresses:
                floor_name = addr.get('Floor', '').strip()
                room_name = addr.get('Room', '').strip()
                
                # Check if floor or room is unknown/empty
                if (not floor_name or floor_name.upper() in ['UNKNOWN', 'UNBEKANNT']) or \
                   (not room_name or room_name.upper() in ['UNKNOWN', 'UNBEKANNT']) or \
                   (not floor_name and not room_name):  # Items without both floor and room
                    unknown_items.append({
                        'name': addr.get('Group name', 'Unknown Address'),
                        'address': addr.get('Address', 'N/A'),
                        'floor': floor_name or 'None',
                        'room': room_name or 'None'
                    })
            
            # Build preview structure
            preview_data = {
                'metadata': {
                    'project_name': project_name,
                    'gateway_ip': gateway_ip,
                    'homekit_enabled': homekit_enabled,
                    'alexa_enabled': alexa_enabled,
                    'total_addresses': len(addresses),
                    'unknown_items': unknown_items
                },
                'buildings': []
            }
            
            if house:
                for building_data in house:
                    building_info = {
                        'name': building_data.get('Description', building_data.get('Group name', 'Unknown Building')),
                        'description': building_data.get('name_long', ''),
                        'floors': []
                    }
                    
                    for floor_data in building_data.get('floors', []):
                        floor_info = {
                            'name': floor_data.get('Description', floor_data.get('Group name', 'Unknown Floor')),
                            'description': floor_data.get('name_long', ''),
                            'rooms': []
                        }
                        
                        for room_data in floor_data.get('rooms', []):
                            # Format addresses to ensure they have the required fields
                            raw_addresses = room_data.get('Addresses', [])
                            formatted_addresses = []
                            for addr in raw_addresses:
                                formatted_addr = {
                                    'Group name': addr.get('Group name', addr.get('name', 'Unknown Address')),
                                    'Address': addr.get('Address', addr.get('address', 'N/A'))
                                }
                                formatted_addresses.append(formatted_addr)
                            
                            room_info = {
                                'name': room_data.get('Description', room_data.get('Group name', 'Unknown Room')),
                                'description': room_data.get('name_long', ''),
                                'address_count': len(formatted_addresses),
                                'device_count': len(room_data.get('devices', [])),
                                'addresses': formatted_addresses
                            }
                            floor_info['rooms'].append(room_info)
                        
                        building_info['floors'].append(floor_info)
                    
                    preview_data['buildings'].append(building_info)
            
            return jsonify(preview_data)
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        finally:
            # Clean up temp file
            try:
                os.remove(temp_path)
            except:
                pass

    @app.route('/api/job/<job_id>/preview', methods=['GET'])
    def job_preview(job_id):
        """Generate structure preview for a past job."""
        job = job_mgr.get_job(job_id)
        if not job:
            return jsonify({'error': 'job not found'}), 404
        
        input_path = job.get('input')
        if not input_path or not os.path.exists(input_path):
            return jsonify({'error': 'job input file not found'}), 404
            
        try:
            password = job.get('password')
            
            # Load project (json dump or parse knxproj)
            if input_path.lower().endswith('.json'):
                with open(input_path, 'r', encoding='utf8') as file:
                    project = json.load(file)
            else:
                # Parse knxproj archive using XKNXProj
                from xknxproject.xknxproj import XKNXProj
                knxproj = XKNXProj(path=input_path, password=password, language='de-DE')
                project = knxproj.parse()
            
            # Extract project metadata
            import importlib
            knxmod = importlib.import_module('knxproject_to_openhab')
            
            # Get building structure
            building = knxmod.create_building(project)
            addresses = knxmod.get_addresses(project)
            house = knxmod.put_addresses_in_building(building, addresses, project)
            
            # Extract metadata
            project_name = house[0].get('name_long') if house else None
            gateway_ip = knxmod.get_gateway_ip(project)
            homekit_enabled = knxmod.is_homekit_enabled(project)
            alexa_enabled = knxmod.is_alexa_enabled(project)
            
            # Detect unknown items (addresses without proper room/floor assignments or with default names)
            unknown_items = []
            for addr in addresses:
                floor_name = addr.get('Floor', '').strip()
                room_name = addr.get('Room', '').strip()
                
                # Check if floor or room is unknown/empty
                if (not floor_name or floor_name.upper() in ['UNKNOWN', 'UNBEKANNT']) or \
                   (not room_name or room_name.upper() in ['UNKNOWN', 'UNBEKANNT']) or \
                   (not floor_name and not room_name):  # Items without both floor and room
                    unknown_items.append({
                        'name': addr.get('Group name', 'Unknown Address'),
                        'address': addr.get('Address', 'N/A'),
                        'floor': floor_name or 'None',
                        'room': room_name or 'None'
                    })
            
            # Build preview structure
            preview_data = {
                'metadata': {
                    'project_name': project_name,
                    'gateway_ip': gateway_ip,
                    'homekit_enabled': homekit_enabled,
                    'alexa_enabled': alexa_enabled,
                    'total_addresses': len(addresses),
                    'unknown_items': unknown_items
                },
                'buildings': []
            }
            
            if house:
                for building_data in house:
                    building_info = {
                        'name': building_data.get('Description', building_data.get('Group name', 'Unknown Building')),
                        'description': building_data.get('name_long', ''),
                        'floors': []
                    }
                    
                    for floor_data in building_data.get('floors', []):
                        floor_info = {
                            'name': floor_data.get('Description', floor_data.get('Group name', 'Unknown Floor')),
                            'description': floor_data.get('name_long', ''),
                            'rooms': []
                        }
                        
                        for room_data in floor_data.get('rooms', []):
                            # Format addresses to ensure they have the required fields
                            raw_addresses = room_data.get('Addresses', [])
                            formatted_addresses = []
                            for addr in raw_addresses:
                                formatted_addr = {
                                    'Group name': addr.get('Group name', addr.get('name', 'Unknown Address')),
                                    'Address': addr.get('Address', addr.get('address', 'N/A'))
                                }
                                formatted_addresses.append(formatted_addr)
                            
                            room_info = {
                                'name': room_data.get('Description', room_data.get('Group name', 'Unknown Room')),
                                'description': room_data.get('name_long', ''),
                                'address_count': len(formatted_addresses),
                                'device_count': len(room_data.get('devices', [])),
                                'addresses': formatted_addresses
                            }
                            floor_info['rooms'].append(room_info)
                        
                        building_info['floors'].append(floor_info)
                    
                    preview_data['buildings'].append(building_info)
            
            return jsonify(preview_data)
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    if __name__ == '__main__':
        host = cfg.get('bind_host', '0.0.0.0')
        port = cfg.get('port', 8080)
        app.run(host=host, port=port)
else:
    # Provide a minimal message when Flask is not available
    if __name__ == '__main__':
        print('Flask is not installed. Please install requirements to run the server.')
