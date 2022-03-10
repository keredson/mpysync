import hashlib, json, os, pathlib, sys
import asyncio
ON_BOARD = False
  

HTTP_PORT = 31261



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
  try: import uttp
  except ImportError as e: print(e)
  
  

def client(directory:str=None, host:str=None, port=None, baud:int=115200, dry_run:bool=False, clear_cache:bool=False, verify:bool=False):

  if not port and not host:
    raise Exception('must specify either host or port')

  import re, requests
    
  if port:
    import ampy.files, ampy.pyboard, time, tempfile, inspect
    board_files = ampy.files.Files(ampy.pyboard.Pyboard(port, baudrate=baud, rawdelay=0))
    
    with tempfile.NamedTemporaryFile(suffix='.py') as f:
      f.write(inspect.getsource(_get_ip).encode())
      f.write('_get_ip()'.encode())
      f.flush()
      lines = board_files.run(f.name, True, False).decode().strip().split('\n')
    device_missing_uttp = len(lines)>1 and 'no module named' in lines[1]
    if not host:
      host = lines[0].strip()
      host = '%s:%i' % (host, HTTP_PORT)
        
    with tempfile.NamedTemporaryFile(suffix='.py') as f:
      path_to_module = pathlib.Path(__file__).parent
      if device_missing_uttp:
        with open(os.path.join(path_to_module, 'uttp.py'),'rb') as src_f:
          f.write(src_f.read())
      with open(os.path.join(path_to_module, 'server.py'),'rb') as src_f:
        f.write(src_f.read())
      f.write('\nasyncio.get_event_loop().run_forever()\n'.encode())
      f.flush()
      board_files.run(f.name, False, False)

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
          while data := f.read(1024*1024):
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
    
    

