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
DB_FN = '.mpysync_sha1.db'


class DB:

  async def __aenter__(self):
    try:
      self.f = open(DB_FN, "r+b")
      scan = False
    except OSError:
      self.f = open(DB_FN, "w+b")
      scan = True
    self.db = btree.open(self.f)
    if scan:
      await self.scan()
    return self.db
    
  async def __aexit__(self, exc_type, exc_value, traceback):
    self.db.close()
    self.f.close()
  
  async def scan(self):
    print('scanning...')
    import binascii
    todo = set(os.listdir())
    while todo:
      await asyncio.sleep(0)
      fn = todo.pop()
      if fn==DB_FN: continue
      stat = os.stat(fn)
      if stat[0]==16384:
        [todo.add(fn+'/'+fn2) for fn2 in os.listdir(fn)]
        self.db[fn.encode()] = b'__dir__'
      else:
        with open(fn,'rb') as f:
          print('scanning', fn)
          h = hashlib.sha1()
          while data := f.read(BUF_SIZE):
            await asyncio.sleep(0)
            h.update(data)
          sig = binascii.hexlify(h.digest())
          self.db[fn.encode()] = sig
    

def server():

  import binascii
  import btree
  
  app = App()
  
  @app.post('/__mpysync__/soft_reset')
  async def restart(req, resp):
    resp.add_header('Content-Type', 'application/json')
    await resp._send_headers()
    await resp.send(json.dumps({'status':'ok'}))
    await resp.writer.aclose()
    sys.exit()
    
  @app.get('/__mpysync__/hello')
  async def clear_cache(req, resp):
    return {'resp':'hi'}
  
  @app.post('/__mpysync__/clear_cache')
  async def clear_cache(req, resp):
    os.remove(DB_FN)
    return {'status':'ok'}
  
  @app.route('/__mpysync__/sha1')
  async def files_sha1(req, resp):

    ret = {}

    async with DB() as db:
      for key, value in db.items():
        ret[key.decode()] = value
    
    await resp._send_headers()
    for x in ret.items():
      await resp.send(json.dumps(x))
      await resp.send('\n')
    await resp.writer.aclose()

  @app.post('/__mpysync__/rm')
  async def rm(req, resp):
    async with DB() as db:
      to_remove = await req.json()
      for fn in to_remove:
        print('rm', fn)
        stat = os.stat(fn)
        if stat[0]==16384:
          os.rmdir(fn)
        else:
          os.remove(fn)
        del db[fn.encode()]
    return {'status':'ok'}
    
  @app.post('/__mpysync__/save', save_headers=['Content-Length', 'Content-Filename', 'Content-SHA1', 'Content-Verify'])
  async def save(req, resp):
    fn = req.headers.get(b'content-filename').decode()
    size = int(req.headers.get(b'content-length'))
    sig = req.headers.get(b'content-sha1')
    verify = b'content-verify' in req.headers
    if not fn: raise HTTPException(404)
    print('=>', fn)

    async with DB() as db:
      try: stat = os.stat(fn)
      except: stat = None
      print('sig', sig, stat, db.get(fn.encode()), fn.encode())
      if sig == b'__dir__':
        if not stat:
          os.mkdir(fn)
        elif stat[0]!=16384:
          os.rm(fn)
          os.mkdir(fn)
        db[fn.encode()] = sig
      else:
        tfn = fn+'.part'
        with open(tfn, 'wb') as f:
          total_read = 0
          while total_read < size:
            data = await req.reader.read(min(BUF_SIZE, size-total_read))
            total_read += len(data)
            print('read', len(data), total_read)
            f.write(data)
            print('wrote', len(data))
        if verify:
          print('checking', tfn)
          with open(tfn,'rb') as f:
            h = hashlib.sha1()
            while data := f.read(BUF_SIZE):
              await asyncio.sleep(0)
              h.update(data)
          sha1 = binascii.hexlify(h.digest())
        else: sha1 = sig
        if sha1 == sig:
          os.rename(tfn, fn)
          db[fn.encode()] = sig
        else:
          print('failed check:', tfn)
          raise HTTPException(500)
        
    return {'status':'ok'}
        
  #import network
  #sta_if = network.WLAN(network.STA_IF)
  #sta_if.active(True)
  #sta_if.connect('<ssid>', '<password>')
#  app.run(host='0.0.0.0', port=HTTP_PORT)
  loop = asyncio.get_event_loop()
  coro = app._tcp_server('0.0.0.0', HTTP_PORT, app.backlog)
  loop.create_task(coro)
  print("mpysync server initialized - don't forget to run:")
  print("import uasyncio as asyncio")
  print("asyncio.get_event_loop().run_forever()")
        


def _parse_mpysyncignore():
  ret = []
  if os.path.isfile('.mpysyncignore'):
    with open('.mpysyncignore') as f:
      for line in f.readlines():
        ret.append(line.strip())
  return ret


def _get_ip():
  import network
  sta_if = network.WLAN(network.STA_IF)
  sta_if.active(True)
  print(sta_if.ifconfig()[0])
  
  

def client(directory:str=None, host:str=None, port=None, baud:int=115200, dry_run:bool=False, clear_cache:bool=False, verify:bool=False):

  if not port and not host:
    raise Exception('must specify either host or port')

  import re, requests
    
  if port:
    import ampy.files, ampy.pyboard, time, tempfile, inspect
    board_files = ampy.files.Files(ampy.pyboard.Pyboard(port, baudrate=baud, rawdelay=0))
    
    if not host:
      with tempfile.NamedTemporaryFile(suffix='.py') as f:
        f.write(inspect.getsource(_get_ip).encode())
        f.write('_get_ip()'.encode())
        f.flush()
        host = board_files.run(f.name, True, False).decode().strip()
        host = '%s:%i' % (host, HTTP_PORT)
        
    with tempfile.NamedTemporaryFile(suffix='.py') as f:
      with open(__file__,'rb') as src_f:
        f.write(src_f.read())
      f.write('\nasyncio.get_event_loop().run_forever()\n'.encode())
      f.flush()
      output = board_files.run(f.name, False, False)

    print('waiting for', host, 'to start...')
    from requests.adapters import HTTPAdapter
    from requests.packages.urllib3.util.retry import Retry
    retry_strategy = Retry(
        total=10,
        backoff_factor=.2,
    )
    http = requests.Session()
    http.mount("http://", HTTPAdapter(max_retries=retry_strategy))
    response = http.get('http://'+host+'/__mpysync__/hello')

  if ':' not in host:
    host += ':%i' % HTTP_PORT

  ignore_rules = _parse_mpysyncignore()
  ignore_patterns = [re.compile(s) for s in ignore_rules]
  if ignore_patterns:
    print('ignoring:', ignore_rules)
  matches = lambda f: any(p.match(f) for p in ignore_patterns)
  
  if clear_cache:
    requests.post('http://'+host+'/__mpysync__/clear_cache')

  if directory:
    d = directory

    print('scanning files (local)...')
    todo = set(os.listdir(d))
    seen = {}
    while todo:
      fn = todo.pop()
      rfn = os.path.join(d, fn)
      if os.path.isdir(rfn):
        [todo.add(os.path.join(fn, fn2)) for fn2 in os.listdir(rfn)]
        seen[fn] = '__dir__'
      else:
        with open(rfn,'rb') as f:
          h = hashlib.sha1()
          while data := f.read(BUF_SIZE):
            h.update(data)
          seen[fn] = h.hexdigest()
    
    
    print('scanning files (board)...')
    resp = requests.get('http://'+host+'/__mpysync__/sha1')
    other = {}
    for line in resp.iter_lines():
      k,v = json.loads(line.strip())
      other[k] = v
    
    for fn, h in sorted(seen.items()):
      rfn = os.path.join(d, fn)
      if matches(fn): continue
      if h != other.get(fn):
        print('=>', fn)
        if not dry_run:
          if h == '__dir__':
            data = None
          else:
            with open(rfn, 'rb') as f:
              data = f.read()
          headers = {'Content-Filename':fn, 'Content-SHA1':h}
          if headers:
            headers['Content-Verify'] = 'true'
          resp = requests.post(
            'http://'+host+'/__mpysync__/save', 
            headers=headers,
            data=data
          )
      if fn in other:
        del other[fn]

    to_remove = sorted([fn for fn in other.keys() if not matches(fn)], reverse=True)
    if to_remove and not dry_run:
      sets=[to_remove[i:i + 10] for i in range(0, len(to_remove), 10)]
      for fns in sets:
        for fn in fns:
          print('rm', fn)
        resp = requests.post(
          'http://'+host+'/__mpysync__/rm', 
          json=fns,
        )

  if port:
    resp = requests.post('http://'+host+'/__mpysync__/soft_reset')
  
  print('...done')
    
    
    
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



  

if ON_BOARD:
  server()

if __name__=='__main__' and not ON_BOARD:
  import darp
  darp.prep(client).run()
