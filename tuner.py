#!/usr/bin/env python3

"""Tune to an fm station using SoftFM and create HLS files using ffmpeg.

Usage:
    tuner.py [--logfile=<filepath>] [--output=<m3u8path>] [--bitrate=<kbps>] [--runtime=<seconds>] <kHz>
    tuner.py (-h | --help)

Options:
    -h --help               Show this screen.
    --logfile=<filepath>    Path to logfile. If specified, logging to STDERR is suppressed. Any existing file will be overwritten.
    --output=<m3u8path>     Path to m3u8 output file. Segments will be created in the same location [default: ./fm.m3u8].
    --bitrate=<kbps>        Output AAC bitrate in kbps [default: 128].
    --runtime=<seconds>     Run for this length of time. Send SIGUSR1 to have it run again once expired.
"""

from docopt import docopt
import subprocess
import shlex
import os
from os import path
import glob
import sys
import signal

args = docopt(__doc__)

def getIntArg(argName):
    try:
        val = args[argName]
        if val is None:
            return None
        else:
            return int(args[argName])
    except ValueError:
        raise ValueError(f'{argName} must be an integer')

freq = getIntArg('<kHz>')
bitrate = getIntArg('--bitrate')
runTime = getIntArg('--runtime')
outPath = path.abspath(args['--output'])
segmentsPath = path.join(path.dirname(outPath), f'fm%06d.ts')
logfile = args['--logfile']
logToFile = False
if logfile is not None:
    logToFile = True
    logfile = open(args['--logfile'], 'w+')
else:
    logfile = sys.stderr

def log(msg):
    print(msg, file=logfile)

run = True
def setRunTrue(signum, frame):
    global run
    run = True
signal.signal(signal.SIGUSR1, setRunTrue)

fmProcess = None
ffProcess = None
try:
    fmProcess = subprocess.Popen(shlex.split(f'softfm -t rtlsdr -c freq={freq}000 -R -'), stdout=subprocess.PIPE, stderr=logfile)
    ffProcess = subprocess.Popen(shlex.split(f'ffmpeg -f s16le -ac 2 -ar 48000 -i - -acodec aac -b:a {bitrate}k -f ssegment -segment_list "{outPath}" -segment_list_type hls -segment_list_size 10 -segment_list_flags +live -segment_time 10 -hls_flags delete_segments -y {segmentsPath}'), stdin=fmProcess.stdout, stderr=logfile)

    if runTime is None:
        ffProcess.communicate()
    else:
        while run:
            run = False
            for x in range(runTime):
                try:
                    ffProcess.communicate(timeout=1)
                except subprocess.TimeoutExpired:
                    if run:
                        log("Runtime timer reset")
                        break
        log("Runtime expired")
                    
except FileNotFoundError as e:
    log(f'ERROR: {e.filename} is not installed')
    raise
finally:
    try:
        if ffProcess is not None:
            ffProcess.send_signal(signal.SIGTERM)
            ffProcess.communicate()
    except Exception as e:
        log('Killing ffmpeg process failed')
        log(e)
    # Clean up output files
    os.remove(outPath)
    files = glob.glob(path.join(path.dirname(outPath), 'fm*.ts'))
    for f in files:
        os.remove(f)
                
    logfile.close()
