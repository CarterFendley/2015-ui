#!/usr/bin/env python3

import tornado.ioloop
from tornado.ioloop import IOLoop
import tornado.web
import tornado.websocket
import sys
import time
from networktables import NetworkTable
from tornado.websocket import WebSocketHandler
from tornado.websocket import WebSocketClosedError
from tornado.options import define, options, parse_command_line
import logging
import json
import os.path
import cv2
import struct
import threading
import socket
import numpy as np
import logging

from threading import RLock
logging.basicConfig(level=logging.DEBUG)



class WebSocket(tornado.websocket.WebSocketHandler):

    #
    # WebSocket API
    #

    def check_origin(self, origin):
        return True
    
    def open(self):

        self.ioloop = IOLoop.current()
        self.nt = NetworkTable.getGlobalTable()
        NetworkTable.addGlobalListener(self.valueChanged, immediateNotify=True)

    def on_message(self, message):
        data=json.loads(message)

        key = data['key']
        val = data['value']
       
        print('key-',key,',val-',val,' type is ', type(val))

        self.nt.putValue(key, val)
   
    def on_close(self):
        print("WebSocket closed")
        NetworkTable.removeGlobalListener(self.valueChanged)

    #
    # NetworkTables specific stuff
    #
            
    def valueChanged(self, key, value, isNew):
        self.ioloop.add_callback(self.changeValue, key, value,"valueChanged")

    def changeValue(self, key, value, event):
        #sends a message to the driverstation
        message={'key':key,
                 'value':value,
                 'event':event}
        
        try:
            self.write_message(message, False)
        except WebSocketClosedError:
            print("websocket closed when sending message")

def init_networktables(ipaddr):

    print("Connecting to networktables at %s" % ipaddr)
    NetworkTable.setIPAddress(ipaddr)
    NetworkTable.setClientMode()
    NetworkTable.initialize()
    print("Networktables Initialized")

class CaptureClient:
    '''
        This probably isn't terribly efficient.. 
    '''
    kPort = 1180
    kMagicNumber = bytes([0x01, 0x00, 0x00, 0x00])
    kSize640x480 = 0
    kSize320x240 = 1
    kSize160x120 = 2
    
    intStruct = struct.Struct("!i")
    
    def __init__(self, host):
        self.host = host
        
        self.running = True
        self.sock = None
        self.on_img = None
        
        self.fps = 10
        self.compression = 30
        self.size = self.kSize160x120
        
        self.thread = threading.Thread(target=self._capture_thread)
        self.logger = logging.getLogger('cvclient')
        
    def start(self):
        
        if self.on_img is None:
            raise ValueError("No capture function set")
        
        self.thread.start()
    
    def stop(self):
        self.running = False
        if self.sock is not None:
            self.sock.close()
            
        self.thread.join()
    
    def set_on_img(self, fn):
        self.on_img = fn
    
    def _capture_thread(self):
        
        address = (self.host, 1180)

        while self.running:
        
            self.sock = None
        
            try:
                self.sock = socket.create_connection(address, timeout=1)
                
                self.sock.settimeout(5)
                
                s = self.sock.makefile('rwb')
                self._do_capture(s)
                
            except IOError:
                
                self.logger.exception("Error reading data")
                
                try:
                    if self.sock is not None:
                        self.sock.close()
                except:
                    pass
                
                if self.sock is None:
                    time.sleep(1)

    def _read(self, s, size):
        data = s.read(size)
        if len(data) != size:
            raise IOError("EOF")
        return data

    def _do_capture(self, s):
        
        # TODO: Add metrics
        
        s.write(self.intStruct.pack(self.fps))
        s.write(self.intStruct.pack(self.compression))
        s.write(self.intStruct.pack(self.size))
        s.flush()
        
        '''self.sock.close()
        self.sock = socket.create_connection((self.host, 1180), timeout=1)
                
        self.sock.settimeout(5)
                
        s = self.sock.makefile('rwb')'''
        
        while True:
            
            # read an int
            print("Read")
            magic = self._read(s, 4)
            sz = self.intStruct.unpack(self._read(s, 4))[0]
            
            # read the image buffer
            print("readsz: %s" % sz)
            img_bytes = self._read(s, sz)
            
            img_bytes = np.fromstring(img_bytes, np.uint8)
            
            # decode it
            img = cv2.imdecode(img_bytes, cv2.IMREAD_COLOR)
        
            # write to a buffer
            # - TODO: use two buffers to save memory allocations
            #cv2.imwrite("text.jpg",img)


class MyStaticFileHandler(tornado.web.StaticFileHandler):

    # This is broken in tornado, disable it
    def check_etag_header(self):
        return False

def main():

    define("host", default='127.0.0.1', help="Hostname of robot", type=str)
    define("port", default=8888, help="run on the given port", type=int)

    parse_command_line()

    init_networktables(options.host)
    
    capture = CaptureClient(options.host)
    img_lock = threading.Lock()
    imgs = [None]
    def _on_img(img):
        with img_lock:
            imgs[0] = img

    capture.set_on_img(_on_img)
    capture.start()

    app = tornado.web.Application([
        (r'/ws', WebSocket),
        (r"/(.*)", MyStaticFileHandler, {"path": os.path.dirname(__file__)}),

    ])
    
    print("Listening on http://localhost:%s/" % options.port)
    print("- Websocket API at ws://localhost:%s/ws" % options.port)

    app.listen(options.port)
    tornado.ioloop.IOLoop.instance().start()


if __name__ == '__main__':
    main()
#connectToIP(ipadd)
