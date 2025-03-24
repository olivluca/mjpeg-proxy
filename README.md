# mjpeg-proxy
A proxy that connects to a single MJPEG stream and distributes to multiple inbound (HTTP) clients and optionally rotate the image.

```
Usage: mjpeg-proxy.py [OPTIONS] MJPEGURL

Options:
  -l, --listenhost TEXT      Address/host to bind to
  -p, --listenport INTEGER   Port to bind to
  -r, --rotate [90|180|270]  Image rotation
  --help                     Show this message and exit.
```
