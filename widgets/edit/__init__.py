import time

def make_uuid():
    global uuid
    uuid = f'{time.time_ns():019d}'
    return uuid

def set_uuid(new_uuid):
    global uuid
    uuid = new_uuid

uuid = None
