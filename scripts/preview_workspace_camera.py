"""Local browser preview of the fixed workspace camera. No motor access."""
import argparse
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    env = Path(__file__).resolve().parents[1]/'config/docker.env'
    device = next(line.split('=', 1)[1].strip().strip('"\'')
                  for line in env.read_text().splitlines() if line.startswith('WORKSPACE_CAMERA='))
    cv2.setNumThreads(1)
    camera = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not camera.isOpened():
        raise RuntimeError(f'Cannot open workspace camera: {device}. Stop other camera users first.')
    camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    camera.set(cv2.CAP_PROP_FPS, 30)
    stop = threading.Event()
    condition = threading.Condition()
    state = {'jpeg': None, 'sequence': 0, 'error': None, 'last_frame': None}
    token = secrets.token_urlsafe(24)

    def capture():
        try:
            while not stop.is_set():
                ok, frame = camera.read()
                if not ok:
                    raise RuntimeError('Camera read failed')
                ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if not ok:
                    raise RuntimeError('Preview JPEG encoding failed')
                with condition:
                    state.update(jpeg=encoded.tobytes(), sequence=state['sequence']+1,
                                 last_frame=time.monotonic())
                    condition.notify_all()
        except Exception as error:
            with condition:
                state['error'] = str(error)
                condition.notify_all()

    page = '''<!doctype html><html><head><meta charset="utf-8"><title>Workspace camera</title>
<style>body{background:#17202a;color:#f4f6f7;font:18px system-ui;margin:24px}main{max-width:960px;margin:auto}img{width:100%;height:auto;display:block}button{font:inherit;padding:12px 18px;margin:16px 0;cursor:pointer}p{line-height:1.5}</style></head>
<body><main><h1>Fixed workspace camera</h1><p>Place the cube within this view and the arm’s known reach. This preview does not measure robot reach.</p>
<img src="/stream.mjpg" alt="Live workspace camera"><button id="stop">Stop preview and release camera</button>
<p id="status">Camera only. No robot connection. Stop this preview before recording.</p></main>
<script>document.querySelector('#stop').onclick=async()=>{await fetch('/stop',{method:'POST',headers:{'X-Preview-Token':'TOKEN'}});document.querySelector('img').removeAttribute('src');document.querySelector('#status').textContent='Preview stopped. Camera released; you can record now.'};</script></body></html>'''.replace('TOKEN', token).encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == '/':
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(page)))
                self.end_headers()
                self.wfile.write(page)
            elif self.path == '/status':
                with condition:
                    data = json.dumps({k: v for k, v in state.items() if k != 'jpeg'}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(data)
            elif self.path == '/stream.mjpg':
                self.send_response(200)
                self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                sequence = -1
                try:
                    while not stop.is_set():
                        with condition:
                            condition.wait_for(lambda: state['sequence'] != sequence or state['error'] or stop.is_set(), timeout=2)
                            if state['error'] or stop.is_set():
                                break
                            jpeg, current = state['jpeg'], state['sequence']
                        if jpeg is None or current == sequence:
                            continue
                        sequence = current
                        self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '+str(len(jpeg)).encode()+b'\r\n\r\n'+jpeg+b'\r\n')
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
            else:
                self.send_error(404)

        def do_POST(self):
            if self.path != '/stop' or self.headers.get('X-Preview-Token') != token:
                self.send_error(403)
                return
            stop.set()
            with condition:
                condition.notify_all()
            worker.join(timeout=2)
            camera.release()
            self.send_response(200)
            self.send_header('Content-Length', '0')
            self.end_headers()
            threading.Thread(target=server.shutdown, daemon=True).start()

    server = None
    worker = threading.Thread(target=capture, daemon=True)
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
        server.daemon_threads = True
        worker.start()
        print(f'Workspace camera preview: http://127.0.0.1:{args.port} — camera only; no motor access.', flush=True)
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        with condition:
            condition.notify_all()
        if worker.is_alive():
            worker.join(timeout=2)
        camera.release()
        if server is not None:
            server.server_close()
        print('Workspace camera released.', flush=True)


if __name__ == '__main__':
    main()
