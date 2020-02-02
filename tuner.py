import asyncio
from asyncio import subprocess
import math
import logging
import os
import signal
import traceback
import sys
from time import time
import shlex
    
BUFFER_BLOCK_SEC = 0.05
BUFFER_TOTAL_SEC = 10

logging.basicConfig(level=os.environ.get('LOGLEVEL', 'DEBUG').upper())
log = logging.getLogger(__name__)
log_level = log.getEffectiveLevel()

prev_instrumented = None, None
instrumented = set()
def instrument(name):
    if log_level != logging.DEBUG:
        return
        
    global prev_instrumented
    global instrumented

    if name in instrumented:
        return
    instrumented |= {name}

    this_time = time()
    prev_name, prev_time = prev_instrumented
    if prev_name:
        log.debug(f'~~~ INSTRUMENTATION: {prev_name} --> {name}: {this_time - prev_time}s')

    prev_instrumented = name, this_time
    
class Tuner:

    def __init__(self, freq, bitrate=96000):
        self.bitrate = bitrate
        self.freq = freq

        # TODO smarter allocation of buffer - container packets?
        self._block_size = math.ceil(bitrate * BUFFER_BLOCK_SEC)
        self._block_count = math.ceil(BUFFER_TOTAL_SEC / BUFFER_BLOCK_SEC)

        self._buffer = {}
        self._min = 0
        self._max = -1

        self._listeners = 0
        self._data_event = asyncio.Event()
        self._proc = None
        self._tuned = False
        self._tune_task = None

    def listener_count(self):
        return self._listeners

    async def _kill_proc(self):
        try:
            if self._proc:
                pgid = os.getpgid(self._proc.pid)
                os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            # Already dead
            pass
        self._proc = None
            
    async def tune(self):
        if self._tuned:
            await self._tune_task
            return
        
        self._tuned = True
        try:
            self._buffer = {}
            self._min = 0
            self._max = -1

            quote = lambda *args: ' '.join([ shlex.quote(s) for s in args ])
            cmd = quote(
                'softfm',
                '-t', 'rtlsdr',
                '-c', f'freq={self.freq}000,blklen={BUFFER_BLOCK_SEC * 2}',
                '-b', str(BUFFER_BLOCK_SEC),
                '-R', '-') + ' | ' + quote(
                'ffmpeg',
                '-f', 's16le', '-ac', '2', '-ar', '48000', '-i', '-',
                '-acodec', 'libopus', '-b:a', f'{self.bitrate}',
                '-f', 'mpegts', '-pes_payload_size', '500', '-')
            log.debug(cmd)
            self._proc = proc = await asyncio.create_subprocess_shell(cmd, preexec_fn=os.setsid, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            instrument('softfm/ffmpeg started')

            async def read_stderr():
                stderr = proc.stderr
                while not stderr.at_eof():
                    try:
                        line_bytes = await stderr.readuntil()
                    except asyncio.LimitOverrunError as err:
                        line_bytes = await stderr.read(err.consumed)
                    except asyncio.IncompleteReadError as err:
                        line_bytes = err.partial
                    log.info('softfm/ffmpeg: ' + line_bytes.decode('utf-8').strip())
            
            async def read_stdout():
                chunk = True
                while chunk:
                    chunk = await proc.stdout.read(self._block_size)
                    instrument('ffmpeg packet')
                    if chunk:
                        self._max += 1
                        self._buffer[self._max] = chunk
                        while (self._max - self._min) > self._block_count:
                            try:
                                del self._buffer[self._min]
                            except KeyError:
                                pass
                            self._min += 1
                    self._data_event.set()
            
            instrument('start tasks')
            for t in asyncio.as_completed([read_stderr(), read_stdout()]):
                try:
                    await t
                except Exception:
                    log.debug('tuner exception: ' + traceback.format_exc())
                    await self._kill_proc()
        finally:
            self._tuned = False

    async def _await_data(self):
        self._data_event.clear()
        await self._data_event.wait()

    async def listen(self):
        '''Generator of chunks of audio. Cancel the generator to stop listening.'''
        instrument('listen generator started')
        try:
            self._listeners += 1
            if not self._tune_task:
                self._tune_task = asyncio.create_task(self.tune())

            run_generator = True
            async def gen_chunks():
                pos = max(self._max, 0)
                while run_generator:
                    while self._max <= pos and run_generator:
                        await self._await_data()
                    if not run_generator:
                        break
                    chunk = self._buffer[pos]
                    instrument('gen chunk')
                    yield chunk
                    pos += 1

            # Schedule both tuner and generator
            it = gen_chunks()
            gen_task = None
            def create_gen_task():
                nonlocal gen_task
                # gen_task = asyncio.create_task(type(it).__anext__(it))
                gen_task = asyncio.create_task(it.__anext__())
                return gen_task
            pending = { create_gen_task(), self._tune_task }
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for t in done:
                    try:
                        if t == gen_task:
                            chunk = await t
                            instrument('listen chunk')
                            yield chunk
                            pending |= { create_gen_task() }
                        else:
                            log.warning('Tune task completed!')
                            run_generator = False
                            self._data_event.set()
                    except StopAsyncIteration:
                        # Tune task will be either awaited below or by other listeners
                        pending = {}

        finally:
            self._listeners -= 1
            if self._listeners <= 0:
                self._listeners = 0
                if self._proc:
                    await self._kill_proc()
                    tune_task = self._tune_task
                    self._tune_task = None
                    await tune_task
