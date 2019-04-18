import sys
sys.path.insert (0, '../../')
sys.path.insert (0, '../../../')

from app import app
import pika
from RabbitMQ.message_queue import *
import json
import pandas as pd
from flask import Flask,render_template,request,redirect
import numpy as np
from googleapiclient.discovery import build
from oauth2client import client, tools, file
from googleapiclient.http import MediaFileUpload
from httplib2 import Http
from threading import Thread

SCOPES = 'https://www.googleapis.com/auth/drive'
RMQ = RabbitMQ()
data = ""

def receiveInput(exchange, key):
    RMQ.receive(callback, exchange, key)

def callback(ch, method, properties, body):
    global data
    if not isinstance(body, str):
            body = body.decode()
    data = body
    print(data)

t1 = Thread(target = receiveInput, args = ('', "quake_queue"))
t1.start()

@app.route('/')
def firstpage():
    # TODO : Replace proper queuename here
    return render_template('p.html',title='IAS')

@app.route('/earthquake_status')
def status():
    '''
        When called, this function will receive data from some stream and send it back to the caller
    '''
    global data
    status = {"status" : data}
    status = json.dumps(status)
    print(status)
    return status