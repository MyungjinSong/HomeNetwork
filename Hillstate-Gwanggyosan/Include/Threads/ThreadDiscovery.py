import os
import sys
import time
import threading
CURPATH = os.path.dirname(os.path.abspath(__file__))  # Project/Include/Threads
INCPATH = os.path.dirname(CURPATH)  # Project/Include/
PROJPATH = os.path.dirname(INCPATH)  # Proejct/
sys.path.extend([CURPATH, INCPATH, PROJPATH])
sys.path = list(set(sys.path))
del CURPATH, INCPATH, PROJPATH
from Common import Callback, writeLog


class ThreadDiscovery(threading.Thread):
    _keepAlive: bool = True

    def __init__(self, timeout: int):
        threading.Thread.__init__(self, name='Discovery Thread')
        self.timeout = timeout
        self.sig_terminated = Callback()
    
    def run(self):
        writeLog(f'Started (for {self.timeout} seconds)', self)
        tm_start = time.perf_counter()
        while self._keepAlive:
            if time.perf_counter() - tm_start >= self.timeout:
                break
            time.sleep(0.1)
        writeLog('Terminated', self)
        self.sig_terminated.emit()

    def stop(self):
        self._keepAlive = False
