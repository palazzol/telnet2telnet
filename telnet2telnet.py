# -*- coding: utf-8 -*-
"""
Created on Mon Jul 13 22:48:16 2020

@author: palazzol

This file was tested with python3 under Windows

Used to connect Serial Terminals with ESP-Link adapters to a Telnet Server.
Configuration info is in terminals.json

Still TODO:
    Add Ctrl-C Handler
    Cleanup all the debug printing
    Setup Auto-reconnect
    Configure baudrate on ESP-Link
    
"""
import sys
import asyncio
from enum import Enum
import json

class TelnetState(Enum):
    NORMAL = 0
    IAC = 1
    DO = 2
    WILL = 3
    SB = 4
    
TelnetChar = { 
    'IAC' :b'\xff',
    'DONT':b'\xfe',
    'DO'  :b'\xfd',
    'WONT':b'\xfc',
    'WILL':b'\xfb',
    'SB'  :b'\xfa',
    'SE'  :b'\xf0'
}
    
class TelnetClientProtocol(asyncio.Protocol):
    def __init__(self, name, termtype, baudrate, on_con_lost, other):
        self.name = name
        self.termtype = termtype
        self.baudrate = baudrate
        self.on_con_lost = on_con_lost
        self.state = TelnetState.NORMAL
        self.other = other
        self.subbuf = b''
        
    def set_other(self, other):
        self.other = other
    
    def other_write(self, b):
        if self.other:
                self.other.write(b)

    def connection_made(self, transport):
        #transport.write(self.message.encode())
        #print('Data sent: {!r}'.format(self.message))
        self.transport = transport

    def ProcessSubBuf(self):
        print('Subbuf: ',self.subbuf)
        if int(self.subbuf[0]) == 24:
            self.transport.write(TelnetChar['IAC'])
            self.transport.write(TelnetChar['SB'])
            self.transport.write(b'\x18')
            self.transport.write(b'\x00')
            self.transport.write(self.termtype.encode())
            self.transport.write(TelnetChar['IAC'])
            self.transport.write(TelnetChar['SE'])
            
        elif int(self.subbuf[0]) == 31:
            self.transport.write(TelnetChar['IAC'])
            self.transport.write(TelnetChar['SB'])
            self.transport.write(b'\x1f')
            self.transport.write(b'\x00\x50\x00\x18') # 80x24
            self.transport.write(TelnetChar['IAC'])
            self.transport.write(TelnetChar['SE'])
            
        elif int(self.subbuf[0]) == 32:
            self.transport.write(TelnetChar['IAC'])
            self.transport.write(TelnetChar['SB'])
            self.transport.write(b'\x20')
            self.transport.write(b'\x00')
            s = self.baudrate+','+self.baudrate
            self.transport.write(s.encode())
            self.transport.write(TelnetChar['IAC'])
            self.transport.write(TelnetChar['SE'])            
 
            
    def data_received(self, data):
        print('Data received from {0}: {1!r}'.format(self.name,data))
        for b in data:
            b = b.to_bytes(1, sys.byteorder)
            
            if self.state == TelnetState.NORMAL:
                if b == TelnetChar['IAC']:
                    self.state = TelnetState.IAC
                else:
                    self.other_write(b)
                    
            elif self.state == TelnetState.IAC:
                if b == TelnetChar['IAC']:
                    self.state = TelnetState.NORMAL
                    self.other_write(b)
                elif b == TelnetChar['DO']:
                    self.state = TelnetState.DO
                elif b == TelnetChar['WILL']:
                    self.state = TelnetState.WILL
                elif b == TelnetChar['SB']:
                    self.state = TelnetState.SB
                    self.subbuf = b''
                else:
                    self.other_write(TelnetChar['IAC'])
                    self.other_write(b)
                    
            elif self.state == TelnetState.DO:
                self.state = TelnetState.NORMAL
                if b[0] in (1, 24, 31, 32):
                    print('accept {0} DO 0x{1:02x}'.format(self.name, b[0]))
                    self.transport.write(TelnetChar['IAC'])
                    self.transport.write(TelnetChar['WILL'])
                    self.transport.write(b)                
                else:
                    print('reject {0} DO 0x{1:02x}'.format(self.name, b[0]))
                    self.transport.write(TelnetChar['IAC'])
                    self.transport.write(TelnetChar['WONT'])
                    self.transport.write(b)
                
            elif self.state == TelnetState.SB:
                if b == TelnetChar['SE']:
                    self.ProcessSubBuf()
                    self.state = TelnetState.NORMAL
                else:
                    self.subbuf = self.subbuf + b
                    
            elif self.state == TelnetState.WILL:
                self.state = TelnetState.NORMAL
                print('accept {0} WILL 0x{1:02x}'.format(self.name, b[0]))
                self.transport.write(TelnetChar['IAC'])
                self.transport.write(TelnetChar['DO'])
                self.transport.write(b)

    def connection_lost(self, exc):
        print(self.name+' closed the connection')
        #print(self.name, self.termtype)
        if not self.on_con_lost.done():
            self.on_con_lost.set_result(True)
        

class RawClientProtocol(asyncio.Protocol):
    def __init__(self, name, on_con_lost, other):
        self.name = name
        self.on_con_lost = on_con_lost
        self.other = other

    def set_other(self, other):
        self.other = other
    
    def other_write(self, buf):
        if self.other:
                for b in buf:
                    b = b.to_bytes(1, sys.byteorder)
                    self.other.write(b)
                    if (b == TelnetChar['IAC']):
                        self.other.write(b)
                
    def connection_made(self, transport):
        #transport.write(self.message.encode())
        #print('Data sent: {!r}'.format(self.message))
        self.transport = transport
        
    def data_received(self, data):
        print('Data received from {0}: {1!r}'.format(self.name,data))
        self.other_write(data)

    def connection_lost(self, exc):
        print(self.name+' closed the connection')
        #print(self.name, self.termtype)
        if not self.on_con_lost.done():
            self.on_con_lost.set_result(True)
            
async def CreateTerminalConnections(loop, serverdata, on_con_lost):
    transports = []
    protocols = []
    stransports = [] 
    sprotocols = []
    print(serverdata)
    for term in serverdata['terminals']:
        print(term)
        # first, connect to the terminals
        transport, protocol = await loop.create_connection(
                lambda: RawClientProtocol(term['name'], on_con_lost, None),
                term['address'], 23)
        transports.append(transport)
        protocols.append(protocol)
        
        # create server link, and connect server->terminal
        stransport, sprotocol = await loop.create_connection(
                lambda: TelnetClientProtocol(serverdata['name'], term['type'], term['baudrate'], on_con_lost, transport),
                serverdata['address'], 23)
        stransports.append(stransport)
        sprotocols.append(sprotocol)
        
        # finally, connect terminal->server
        protocol.set_other(stransport)
    return transports, protocols, stransports, sprotocols
        
# Async def means this is a coroutine,
# It can pause and resume at await statements
        
async def main():
    
    with open('terminals.json','r') as fp:
        serverdata = json.load(fp)

    # Get a reference to the event loop as we plan to use
    # low-level APIs.
    loop = asyncio.get_running_loop()
    on_con_lost = loop.create_future()

    transports, protocols, stransports, sprotocols = await CreateTerminalConnections(loop, serverdata, on_con_lost)
    
    # Wait until the protocol signals that the connection
    # is lost and close the transport.
    try:
        await on_con_lost
    finally:
        for transport in transports:
            transport.close()
        for stransport in stransports:
            stransport.close()
        
# ok, let's start the show
asyncio.run(main())
