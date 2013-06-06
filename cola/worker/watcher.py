#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
Created on 2013-6-5

@author: Chine
'''

import threading
import time
import os
import subprocess
import shutil

from cola.core.rpc import ColaRPCServer, client_call, FileTransportServer
from cola.core.utils import get_ip, import_job, root_dir
from cola.core.zip import ZipHandler
from cola.job.conf import main_conf

TIME_SLEEP = 10

class WorkerWatcherRunning(Exception): pass

class WorkerWatcher(object):
    def __init__(self, rpc_server, master, zip_dir, job_dir):
        self.rpc_server = rpc_server
        self.master = master
        self.node = '%s:%s' % (get_ip(), main_conf.worker.port)
        self.zip_dir = zip_dir
        self.job_dir = job_dir
        
        self.stopped = False
        
        self.rpc_server.register_function(self.stop, 'stop')
        self.rpc_server.register_function(self.start_job, 'start_job')
        self.rpc_server.register_function(self.clear_job, 'clear_job')
        self.set_file_receiver(self.zip_dir)
        
    def set_file_receiver(self, base_dir):
        serv = FileTransportServer(self.rpc_server, base_dir)
        return serv
    
    def register_heartbeat(self):
        client_call(self.master, 'register_heartbeat', self.node)
        
    def start_job(self, zip_filename):
        zip_file = os.path.join(self.zip_dir, zip_filename)
        job_dir = ZipHandler.uncompress(zip_file, self.job_dir)
        job = import_job(job_dir)
        
        master_port = job.context.job.master_port
        master = '%s:%s' % (self.master.split(':')[0], master_port)
        dirname = os.path.dirname(os.path.abspath(__file__))
        f = os.path.join(dirname, 'loader.py')
        return_code = subprocess.call('python "%s" "%s" %s' % (f, job_dir, master))
        
        return return_code
    
    def clear_job(self, job_name):
        job_name = job_name.replace(' ', '_')
        shutil.rmtree(os.path.join(self.job_dir, job_name))
        
    def run(self):
        def _start():
            while not self.stopped:
                self.register_heartbeat()
                time.sleep(TIME_SLEEP)
        
        thread = threading.Thread(target=_start)
        thread.setDaemon(True)
        thread.start()
        thread.join()
        
    def stop(self):
        self.stopped = True
        
def makedirs(dir_):
    if not os.path.exists(dir_):
        os.makedirs(dir_)
        
def create_rpc_server():
    rpc_server = ColaRPCServer((get_ip(), main_conf.worker.port))
    thd = threading.Thread(target=rpc_server.serve_forever)
    thd.setDaemon(True)
    thd.start()
    return rpc_server

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        raise ValueError('Worker watcher need at least 1 parameters.')
    master = sys.argv[1]
    if ':' not in master:
        master = '%s:%s' % (master, main_conf.master.port)
    
    root = root_dir()
    worker_watcher_dir = os.path.join(root, 'data', 'worker', 'watcher')
    makedirs(worker_watcher_dir)
    zip_dir = os.path.join(root, 'data', 'zip')
    makedirs(zip_dir)
    job_dir = os.path.join(root, 'data', 'jobs')
    makedirs(job_dir)
    
    lock_f = os.path.join(worker_watcher_dir, 'lock')
    if os.path.exists(lock_f):
        raise WorkerWatcherRunning('There has been a running master watcher.')
    
    rpc_server = create_rpc_server()
    try:
        open(lock_f, 'w').close()
        
        master_watcher = WorkerWatcher(rpc_server, master, zip_dir, job_dir)
        master_watcher.run()
    finally:
        rpc_server.shutdown()
        os.remove(lock_f)