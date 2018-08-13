#!/usr/bin/env python3

import cgi
import os
import signal
import subprocess
import shlex
from time import sleep
import sys

M3U8_PATH = '/var/www/html/fm.m3u8'
HTTP_M3U8_PATH = '/media/fm.m3u8'

qs = cgi.parse()

# Pull out the freq parameter
FM_FREQ = 0
if "frequency" in qs:
    val = qs["frequency"][0]
    try:
        FM_FREQ = int(val)
    except:
        print("Status: 400 Bad Request")
        print()
        print("Error: bad frequency")
        exit()
else:
    print("Status: 400 Bad Request")
    print()
    print("Error: frequency not set")
    exit()

# And other configuration
FM_BITRATE = os.environ.get('FM_BITRATE') or 128

def log(msg):
    print(msg, file=sys.stderr)
    
# Open PID file - note this effectively locks the server
launch = False
with open('/tmp/fm.pid', 'a+') as f:
    f.seek(0)
    fmPid = f.read().strip()
    if len(fmPid) > 0:
        # pid set, so we can assume it's already running
        setFreq = 0
        with open('/tmp/fm.freq', 'r') as fFreq:
            setFreq = int(fFreq.read())
        if setFreq == FM_FREQ:
            # Check that the process is still running, and if so send SIGUSR1 to reset the timeout
            try:
                os.kill(fmPid, signal.SIGUSR1)
            except OSError:
                # Not running apparently
                launch = True
        else:
            # Freq changed - kill
            launch = True
            try:
                os.kill(fmPid, signal.SIGTERM)
            except OSError:
                # Wasn't running anyway
                pass
    else:
        launch = True
    
    if launch:
        newProc = subprocess.Popen(shlex.split(f'./tuner.py --logfile=/var/log/fm.log --output={M3U8_PATH} --bitrate={FM_BITRATE} --runtime=60 {FM_FREQ}'))
        f.seek(0)
        f.write(str(newProc.pid).ljust(7)) # to ensure we overwrite any existing pid in the file
        with open('/tmp/fm.freq', 'w+') as fFreq:
            fFreq.write(FM_FREQ)        

        # Wait a bit for the m3u8 file to be produced
        for x in range(10):
            if os.path.exists(M3U8_PATH):
                break
            sleep(1)
        
        if not os.path.exists(M3U8_PATH):
            log('The m3u8 file did not get created within 10 seconds, giving up')
            print('Status: 500 Server Error')
            exit(1)

    print('Status: 302 Found')
    print('Location: ' + HTTP_M3U8_PATH)
