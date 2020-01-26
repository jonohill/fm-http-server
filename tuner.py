import asyncio
from asyncio import subprocess
import math
import logging
import os
import traceback
import sys
    
BUFFER_BLOCK_SEC = 0.05
BUFFER_TOTAL_SEC = 10

logging.basicConfig(level=os.environ.get('LOGLEVEL', 'DEBUG').upper())
log = logging.getLogger(__name__)

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
        self._fm_proc = None
        self._tuned = False
        self._tune_task = None

    def listener_count(self):
        return self._listeners

    def _kill_fm_proc(self):
        try:
            if self._fm_proc:
                self._fm_proc.kill()
        except ProcessLookupError:
            # Already dead
            pass
        self._fm_proc = None
            

    async def tune(self):
        if self._tuned:
            await self._tune_task
            return
        
        self._tuned = True
        try:
            self._buffer = {}
            self._min = 0
            self._max = -1

            self._fm_proc = fm_proc = await asyncio.create_subprocess_exec('softfm',
                '-t', 'rtlsdr',
                '-c', f'freq={self.freq}000',
                '-b', str(BUFFER_BLOCK_SEC),
                '-R', '-', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            ff_proc = await asyncio.create_subprocess_exec('ffmpeg',
                '-f', 's16le', '-ac', '2', '-ar', '48000', '-i', '-',
                '-acodec', 'libopus', '-b:a', f'{self.bitrate}', '-f', 'mpegts', '-',
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            async def read_stderr(reader: asyncio.StreamReader, logger):
                while not reader.at_eof():
                    try:
                        line_bytes = await reader.readuntil()
                    except asyncio.LimitOverrunError as err:
                        line_bytes = await reader.read(err.consumed)
                    except asyncio.IncompleteReadError as err:
                        line_bytes = err.partial
                    logger.info(line_bytes.decode('utf-8').strip())

            async def pipe_data():
                while not fm_proc.stdout.at_eof():
                    ff_proc.stdin.write(await fm_proc.stdout.read(math.ceil(BUFFER_BLOCK_SEC * (48000 * 16))))
                    await ff_proc.stdin.drain()
                if ff_proc.stdin.can_write_eof():
                    ff_proc.stdin.write_eof()
            
            async def read_stdout():
                chunk = True
                while chunk:
                    chunk = await ff_proc.stdout.read(self._block_size)
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

            fm_proc_log_task = read_stderr(fm_proc.stderr, logging.getLogger('softfm'))
            ff_proc_log_task = read_stderr(ff_proc.stderr, logging.getLogger('ffmpeg'))
            
            for t in asyncio.as_completed([fm_proc_log_task, ff_proc_log_task, read_stdout(), pipe_data()]):
                try:
                    await t
                except Exception:
                    log.debug('tuner exception: ' + traceback.format_exc())
                    self._kill_fm_proc()
        finally:
            self._tuned = False

    async def _await_data(self):
        self._data_event.clear()
        await self._data_event.wait()

    async def listen(self):
        '''Generator of chunks of audio. Cancel the generator to stop listening.'''
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
                            yield await t
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
                if self._fm_proc:
                    self._kill_fm_proc()
                    tune_task = self._tune_task
                    self._tune_task = None
                    await tune_task
