# mpysync

Rsync-like tool for [MicroPython](https://micropython.org/).

- Works over serial or WiFi.
- Can be run (as an async task) in the background of your normal app (for remote updates).
- Generally 10-100x faster than using `ampy`.

## Install

```
$ pip install mpysync
```

## Performance
Take for example, a decently sized project (50 files, 836K) on an ESP32...

Copying all files with `ampy`:
```
$ time ampy --port /dev/ttyUSB0 put build/ui ui
real	8m33.000s
```

Vs. rsync-ing the same files (no changes):
```
$ time python -m mpysync build/ --host 10.0.0.179
real	0m1.511s

$ time python -m mpysync build/ --port /dev/ttyUSB0
real	0m6.858s
```

Worst case (no files in common), copying all files w/ `mpysync` is still an order of magnitude faster:
```
$ time python -m mpysync build/ --port /dev/ttyUSB0
real	0m59.650s
```



## CLI Usage

### Over Serial
```
python -m mpysync build/ --port /dev/ttyUSB0
```

### Over WiFi
```
python -m mpysync build/ --host 10.0.0.179
```

### All Options
```
python -m mpysync [--directory <str>] [--host <str>] [--port <value>] [--baud <int>] [--dry_run <bool>] [--clear_cache <bool>] [--verify <bool>]
```

## OTA Usage

In your `main.py` or (or anywhere really):

```
import mpysync.server
```

Then (somewhere later in your code), start the main event loop:

```
import uasyncio as asyncio
asyncio.get_event_loop().run_forever()
```

By default it listens on port 31261.

### Memory
When running in the background (for OTA updates), `mpysync` consumes 16k RAM if you're already using uttp, 20k otherwise.
