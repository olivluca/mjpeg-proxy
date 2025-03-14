#!/usr/bin/env python3
import click
import logging
import socket
import socketserver
import threading
from urllib.parse import urlparse
import queue
from time import sleep

FORMAT_CONS = '%(asctime)s %(name)-26s %(levelname)8s\t%(message)s'
logging.basicConfig(level=logging.INFO, format=FORMAT_CONS)

class MJEPGClient(threading.Thread):
    def __init__(self, mjpegurl):
        threading.Thread.__init__(self)
        self.url_components = urlparse(mjpegurl)
        self.ready = []
        self.receivers = 0
        self.connected = False
        self.boundary = None
        self.log = logging.getLogger('MJEPGClient')

    def connect(self):
        self.log.info('connecting to server')
        self.connected = False
        self.client_socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_STREAM)
        remote_host = self.url_components.netloc.split(':')[0]
        remote_port = int(self.url_components.port) if self.url_components.port is not None else 80
        self.log.info('Connecting to {}:{}'.format(remote_host, remote_port))
        try:
            self.client_socket.connect((remote_host, remote_port))
            get_request = "GET {}{} HTTP/1.1\r\n\r\n".format(
                self.url_components.path,
                self.url_components.query
            ).encode('utf-8')
            self.log.info("Request: {}".format(get_request))
            self.client_socket.send(get_request)
            self.boundary = None
            data = bytes()
            while not self.boundary:
                r = self.client_socket.recv(1024)
                if not r:
                    break
                data += r
                while data and not self.boundary:
                    p=data.find(b'\r\n')
                    if p>=0:
                       line=data[:p]
                       self.log.info('Header line {}'.format(line))
                       data=data[p+2:]
                       p=line.find(b'boundary=')
                       if p>=0:
                          self.boundary=b'--'+line[p+len(b'boundary='):]+b'\r\n'
                          self.log.info('Multipart boundary: {}'.format(self.boundary))
                          break
            if not self.boundary:
              self.log.error('No boundary found')
              return
            self.connected = True
            self.log.info('connected')
        except Exception as e:
            self.connected = False
            self.log.error(str(e))
            return

    def run(self):
        while self.receivers > 0:
            if not self.connected:
                buffer = bytes()
                current_offset = 0
                self.connect()
                if not self.connected:
                    sleep(1)
                    continue

            r = self.client_socket.recv(1024)
            if not r:
                self.log.error('server disconnected')
                self.connected=False
                continue
            buffer += r
            offset = buffer.find(self.boundary, current_offset)
            if offset == -1:
                current_offset = len(buffer) - len(self.boundary)
            else:
                for r in self.ready:
                    try:
                        r.out_queue.put_nowait(buffer[:offset])
                    except queue.Full:
                        self.log.error('queue full, kicking out client')
                        r.queuefull=True
                current_offset = 0
                buffer = buffer[offset+len(self.boundary):]
        self.log.info('Closing down.')

class ThreadedTCPRequestHandler(socketserver.BaseRequestHandler):
    def handle(self):
        self.log = logging.getLogger('ThreadedTCPRequestHandler')
        self.log.info('New connection from: {}'.format(self.client_address[0]))
        self.queuefull=False
        if self.server.mjpegclient is None or not self.server.mjpegclient.is_alive():
            self.log.info("No MJPEGClient. Starting new one.")
            self.server.mjpegclient = MJEPGClient(self.server.mjpegurl)
            self.server.mjpegclient.receivers += 1
            self.server.mjpegclient.start()
        else:
            # Need this else clause because we need to increment before starting above
            self.server.mjpegclient.receivers += 1
        self.log.info('Receivers {}'.format(self.server.mjpegclient.receivers))
        # I don't care about the headers so I just skip reading them
        self.out_queue = queue.Queue(maxsize=1)
        request_buffer = bytes()
        self.request.send(b'HTTP/1.0 200 OK\r\n')
        self.request.send(b'Connection: Close\r\n')
        self.request.send(b'Server: mjpeg-proxy\r\n')
        self.request.send(b'Content-Type: multipart/x-mixed-replace; boundary=--myboundary\r\n')
        self.request.send(b'Cache-Control: no-store, no-cache, must-revalidate, pre-check=0, post-check=0, max-age=0\r\n')
        self.request.send(b'Pragma: no-cache\r\n')
        self.request.send(b'Expires: Mon, 1 Jan 2000 00:00:00 GMT\r\n');
        self.request.send(b'\r\n')
        self.server.mjpegclient.ready.append(self)
        while not self.queuefull:
            try:
                frame = self.out_queue.get()
                self.request.send(b'--myboundary\r\n')
                self.request.send(frame)
            except BrokenPipeError:
                self.log.info('Connection closed from {}: Broken pipe.'.format(self.client_address[0]))
                break
            except ConnectionResetError:
                self.log.info('Connection closed from {}: Connection reset by peer.'.format(self.client_address[0]))
                break
        self.server.mjpegclient.receivers -= 1
        self.log.info('Remaining receivers {}'.format(self.server.mjpegclient.receivers))

class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    def __init__(self, bindhost, handler, mjpegurl):
        socketserver.TCPServer.__init__(self, bindhost, handler)
        self.mjpegurl = mjpegurl
        self.mjpegclient = None


@click.command()
@click.argument(
    'mjpegurl',
    required=True,
)
@click.option(
    '--listenhost',
    '-l',
    default='localhost',
    help='Address/host to bind to'
)
@click.option(
    '--listenport',
    '-p',
    default=8080,
    type=int,
    help='Port to bind to'
)
def cli(mjpegurl, listenhost, listenport):

    socketserver.TCPServer.allow_reuse_address = True
    server = ThreadedTCPServer((listenhost, listenport), ThreadedTCPRequestHandler, mjpegurl)

    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    server_thread.join()
    server.shutdown()
    server.server_close()

if __name__ == '__main__':
    cli()
