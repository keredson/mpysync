import hashlib, json, os, sys

try:
  import btree, machine
  import uasyncio as asyncio
  import usocket as socket
  import gc
  ON_BOARD = True
  IS_UASYNCIO_V3 = hasattr(asyncio, "__version__") and asyncio.__version__ >= (3,)
except:
  import asyncio
  ON_BOARD = False
  

BUF_SIZE = 2048
HTTP_PORT = 31261
    
'''
Striped-down version of uttp
(C) Derek Anderson 2022
(C) Konstantin Belyalov 2017-2018
'''    
class App:

    def __init__(self, request_timeout=3, max_concurrency=3, backlog=16, debug=False):
        self.loop = asyncio.get_event_loop()
        self.request_timeout = request_timeout
        self.max_concurrency = max_concurrency
        self.backlog = backlog
        self.debug = debug
        self.explicit_url_map = {}
        # Currently opened connections
        self.conns = {}
        # Statistics
        self.processed_connections = 0

    def _find_url_handler(self, req):
        if req.path in self.explicit_url_map:
            return self.explicit_url_map[req.path]
        return (None, None)

    async def _handle_request(self, req, resp):
        await req.read_request_line()
        # Find URL handler
        req.handler, req.params = self._find_url_handler(req)
        print(req.method.decode(), req.path.decode())
        if not req.handler:
            # No URL handler found - read response and issue HTTP 404
            await req.read_headers()
            raise HTTPException(404)
        # req.params = params
        # req.handler = han
        resp.params = req.params
        # Read / parse headers
        await req.read_headers(req.params['save_headers'])

    async def _handler(self, reader, writer):
        """Handler for TCP connection with
        HTTP/1.0 protocol implementation
        """
        gc.collect()

        try:
            req = request(reader)
            resp = response(writer)
            # Read HTTP Request with timeout
            await asyncio.wait_for(self._handle_request(req, resp), self.request_timeout)

            # Ensure that HTTP method is allowed for this path
            if req.method not in req.params['methods']:
                raise HTTPException(405)

            # Handle URL
            gc.collect()
            if hasattr(req, '_param'):
                ret = await req.handler(req, resp, req._param)
            else:
                ret = await req.handler(req, resp)
            await resp._handle_return(ret)
            # Done here
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        except OSError as e:
            # Do not send response for connection related errors - too late :)
            # P.S. code 32 - is possible BROKEN PIPE error (TODO: is it true?)
            if e.args[0] not in (errno.ECONNABORTED, errno.ECONNRESET, 32):
                try:
                    await resp.error(500)
                except Exception as e:
                    sys.print_exception(e)
        except HTTPException as e:
            try:
                await resp.error(e.code)
            except Exception as e:
                sys.print_exception(e)
        except Exception as e:
            # Unhandled expection in user's method
            print(req.path.decode())
            sys.print_exception(e)
            try:
                await resp.error(500)
                # Send exception info if desired
                if self.debug:
                    sys.print_exception(e, resp.writer.s)
            except Exception as e:
                pass
        finally:
            await writer.aclose()
            # Max concurrency support -
            # if queue is full schedule resume of TCP server task
            if len(self.conns) == self.max_concurrency:
                self.loop.create_task(self._server_coro)
            # Delete connection, using socket as a key
            del self.conns[id(writer.s)]

    def add_route(self, url, f, **kwargs):
        # Initial params for route
        params = {'methods': ['GET'],
                  'save_headers': ['Content-Length', 'Content-Type'],
                  'max_body_size': 1024,
                  'allowed_access_control_headers': '*',
                  'allowed_access_control_origins': '*',
                  }
        params.update(kwargs)
        params['allowed_access_control_methods'] = ', '.join(params['methods'])
        # Convert methods/headers to bytestring
        params['methods'] = [x.encode() for x in params['methods']]
        params['save_headers'] = [x.lower().encode() for x in params['save_headers']]

        if url == '' or '?' in url:
            raise ValueError('Invalid URL')

        # If URL has a parameter
        if url.encode() in self.explicit_url_map:
            raise ValueError('URL exists')
        self.explicit_url_map[url.encode()] = (f, params)


    def route(self, url, **kwargs):
        def _route(f):
            self.add_route(url, f, **kwargs)
            return f
        return _route
    
    def get(self, url, **kwargs):
        kwargs['methods'] = ['GET']
        return self.route(url, **kwargs)

    def post(self, url, **kwargs):
        kwargs['methods'] = ['POST']
        return self.route(url, **kwargs)

    async def _tcp_server(self, host, port, backlog):
        addr = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0][-1]
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setblocking(False)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(addr)
        sock.listen(backlog)
        try:
            while True:
                if IS_UASYNCIO_V3:
                    yield asyncio.core._io_queue.queue_read(sock)
                else:
                    yield asyncio.IORead(sock)
                csock, caddr = sock.accept()
                csock.setblocking(False)
                # Start handler / keep it in the map - to be able to
                # shutdown gracefully - by close all connections
                self.processed_connections += 1
                hid = id(csock)
                handler = self._handler(asyncio.StreamReader(csock),
                                        asyncio.StreamWriter(csock, {}))
                self.conns[hid] = handler
                self.loop.create_task(handler)
                # In case of max concurrency reached - temporary pause server:
                # 1. backlog must be greater than max_concurrency, otherwise
                #    client will got "Connection Reset"
                # 2. Server task will be resumed whenever one active connection finished
                if len(self.conns) == self.max_concurrency:
                    # Pause
                    yield False
        except asyncio.CancelledError:
            return
        finally:
            sock.close()



class HTTPException(Exception):
    def __init__(self, code=400):
        self.code = code

class request:
    """HTTP Request class"""

    def __init__(self, _reader):
        self.reader = _reader
        self.headers = {}
        self.method = b''
        self.path = b''
        self.query_string = b''

    async def read_request_line(self):
        while True:
            rl = await self.reader.readline()
            # skip empty lines
            if rl == b'\r\n' or rl == b'\n':
                continue
            break
        rl_frags = rl.split()
        if len(rl_frags) != 3:
            raise HTTPException(400)
        self.method = rl_frags[0]
        url_frags = rl_frags[1].split(b'?', 1)
        self.path = url_frags[0]
        if len(url_frags) > 1:
            self.query_string = url_frags[1]

    async def read_headers(self, save_headers=[]):
        while True:
            gc.collect()
            line = await self.reader.readline()
            if line == b'\r\n':
                break
            frags = line.split(b':', 1)
            frags[0] = frags[0].lower()
            if len(frags) != 2:
                raise HTTPException(400)
            if frags[0] in save_headers:
                self.headers[frags[0]] = frags[1].strip()

    async def json(self):
        gc.collect()
        size = int(self.headers[b'content-length'])
        if size > self.params['max_body_size'] or size < 0:
            raise HTTPException(413)
        data = await self.reader.readexactly(size)
        # Use only string before ';', e.g:
        # application/x-www-form-urlencoded; charset=UTF-8
        ct = self.headers[b'content-type'].split(b';', 1)[0]
        try:
            if ct == b'application/json':
                return json.loads(data)
        except ValueError:
            # Re-generate exception for malformed form data
            raise HTTPException(400)


class response:
    """HTTP Response class"""

    def __init__(self, _writer):
        self.writer = _writer
        self.send = _writer.awrite
        self.code = 200
        self.version = '1.0'
        self.headers = {}

    async def _send_headers(self):
        # Request line
        hdrs = 'HTTP/{} {} MSG\r\n'.format(self.version, self.code)
        # Headers
        for k, v in self.headers.items():
            hdrs += '{}: {}\r\n'.format(k, v)
        hdrs += '\r\n'
        # Collect garbage after small mallocs
        gc.collect()
        await self.send(hdrs)

    async def error(self, code, msg=None):
        self.code = code
        if msg:
            self.add_header('Content-Length', len(msg))
        await self._send_headers()
        if msg:
            await self.send(msg)
    
    async def _handle_return(self, o):
        if o is None:
          return
        elif isinstance(o, dict):
          self.add_header('Content-Type', 'application/json')
          await self._send_headers()
          await self.send(json.dumps(o))
        else:
          raise Exception('unknown return type: %s' % o)

    def add_header(self, key, value):
        self.headers[key] = value



  

