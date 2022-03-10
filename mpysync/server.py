import hashlib, json, os, sys
import binascii

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
  

if 'App' not in globals():
  try:
    from uttp import App, HTTPException
  except ImportError:
    from .uttp import App, HTTPException
  

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
        
    
if ON_BOARD:
  server()


