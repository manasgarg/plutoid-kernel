#!/usr/bin/env python3

import pytest
import subprocess
import uuid
from pydisque.client import Client as PydisqueClient
from plutoid_kernel.utils import form_message
import json
import time


CLIENT_CHANNEL = str(uuid.uuid4())
disque_client = PydisqueClient()
disque_client.connect()


@pytest.fixture
def kernel_details_session_mode(scope="session"):
    kernel_id = str(uuid.uuid4())
    cmd = 'plutoidkernel --session-mode --kernel-id %s --ping-interval 2' % kernel_id
    kernel_proc = subprocess.Popen(cmd.split(' '))

    yield (kernel_id, kernel_proc)

    if not kernel_proc.returncode:
        kernel_proc.terminate()

    # clear the disque queue
    for queue_name, system_message_id, message in disque_client.get_job([CLIENT_CHANNEL], timeout=1000):
        disque_client.ack_job(system_message_id)


@pytest.fixture
def kernel_details(scope="session"):
    kernel_id = str(uuid.uuid4())
    cmd = 'plutoidkernel --kernel-id %s --verbose --ping-interval 2 --max-code-execution-time 2' % kernel_id
    kernel_proc = subprocess.Popen(cmd.split(' '))

    yield (kernel_id, kernel_proc)

    if not kernel_proc.returncode:
        kernel_proc.terminate()

    # clear the disque queue
    for queue_name, system_message_id, message in disque_client.get_job([CLIENT_CHANNEL], timeout=1000):
        disque_client.ack_job(system_message_id)


def send_ping_request(kernel_id):
    message = form_message(kernel_id, 'ping_request', {'reverse_path': CLIENT_CHANNEL})
    disque_client.add_job(kernel_id, json.dumps(message))


def retrieve_ping_response(timeout=1000):
    ping_response = None

    for queue_name, system_message_id, message in disque_client.get_job([CLIENT_CHANNEL], timeout=timeout):
        disque_client.ack_job(system_message_id)
        message = json.loads(message)
        if message['header']['msg_type'] == 'ping_response':
            ping_response = message

    return ping_response
        

def test_ping_response(kernel_details):
    kernel_id, kernel_proc = kernel_details
    send_ping_request(kernel_id)
    assert retrieve_ping_response() != None


def test_kernel_exits_if_no_ping(kernel_details):
    kernel_id, kernel_proc = kernel_details
    try:
        kernel_proc.wait(timeout=6)
    except subprocess.TimeoutExpired:
        pass
    assert kernel_proc.returncode != None


def test_code_execution_complete_message(kernel_details):
    kernel_id, kernel_proc = kernel_details
    code = '''i = 2'''
    message = form_message(kernel_id, 'code_execution', {'reverse_path': CLIENT_CHANNEL, 'code': code})
    disque_client.add_job(kernel_id, json.dumps(message))

    desired_response = None
    for queue_name, system_message_id, message in disque_client.get_job([CLIENT_CHANNEL], timeout=2000):
        disque_client.ack_job(system_message_id)
        message = json.loads(message)
        if message['header']['msg_type'] == 'code_execution_complete':
            desired_response = message

    assert desired_response != None


def fetch_messages(requested_message_counts, duration_seconds=2):
    collected_messages = {}
    collected_message_counts = {}
    for k in requested_message_counts.keys():
        collected_message_counts[k] = 0
        collected_messages[k] = []

    start_time = time.time()

    while True:
        for queue_name, system_message_id, message in disque_client.get_job([CLIENT_CHANNEL], timeout=1000):
            disque_client.ack_job(system_message_id)
            message = json.loads(message)
            msg_type = message['header']['msg_type']
            if msg_type in requested_message_counts \
                    and collected_message_counts[msg_type] != requested_message_counts[msg_type]:
                collected_messages[msg_type].append(message)
                collected_message_counts[msg_type] += 1

        if len(set(requested_message_counts.items()) ^ set(collected_message_counts.items())) == 0:
            break

        if time.time() - start_time > duration_seconds:
            break

    return collected_messages


def test_stdout_message(kernel_details):
    kernel_id, kernel_proc = kernel_details
    code = '''
print("message on stdout - 0")
print("message on stdout - 1")
'''
    message = form_message(kernel_id, 'code_execution', {'reverse_path': CLIENT_CHANNEL, 'code': code})
    disque_client.add_job(kernel_id, json.dumps(message))

    collected_messages = fetch_messages({'stdout': 2})

    assert 'stdout' in collected_messages
    assert len(collected_messages['stdout']) == 2

    mesg0 = collected_messages['stdout'][0]
    mesg1 = collected_messages['stdout'][1]

    assert mesg0['msg_data']['content'] == 'message on stdout - 0\n'
    assert mesg1['msg_data']['content'] == 'message on stdout - 1\n'


def test_stderr_message(kernel_details):
    kernel_id, kernel_proc = kernel_details
    code = '''
import sys

print("message on stderr - 0", file=sys.stderr)
print("message on stderr - 1", file=sys.stderr)
'''
    message = form_message(kernel_id, 'code_execution', {'reverse_path': CLIENT_CHANNEL, 'code': code})
    disque_client.add_job(kernel_id, json.dumps(message))

    collected_messages = fetch_messages({'stderr': 2})

    assert 'stderr' in collected_messages
    assert len(collected_messages['stderr']) == 2

    mesg0 = collected_messages['stderr'][0]
    mesg1 = collected_messages['stderr'][1]

    assert mesg0['msg_data']['content'] == 'message on stderr - 0\n'
    assert mesg1['msg_data']['content'] == 'message on stderr - 1\n'


def test_stdout_stderr_in_code_execution_complete(kernel_details):
    kernel_id, kernel_proc = kernel_details
    code = '''
import sys
sys.stdout.write('hello, world')
sys.stderr.write('hello, world')
'''
    message = form_message(kernel_id, 'code_execution', {'reverse_path': CLIENT_CHANNEL, 'code': code})
    disque_client.add_job(kernel_id, json.dumps(message))

    collected_messages = fetch_messages({'code_execution_complete': 1})

    assert 'code_execution_complete' in collected_messages
    assert len(collected_messages['code_execution_complete']) == 1

    msg = collected_messages['code_execution_complete'][0]
    assert 'stdout' in msg['msg_data']
    assert msg['msg_data']['stdout'] == 'hello, world'
    assert 'stderr' in msg['msg_data']
    assert msg['msg_data']['stderr'] == 'hello, world'


def test_shutdown(kernel_details):
    kernel_id, kernel_proc = kernel_details

    message = form_message(kernel_id, 'shutdown')
    disque_client.add_job(kernel_id, json.dumps(message))

    try:
        kernel_proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass
    
    assert kernel_proc.returncode != None


def test_exception(kernel_details):
    kernel_id, kernel_proc = kernel_details
    code = '''
prin(10)
'''
    message = form_message(kernel_id, 'code_execution', {'reverse_path': CLIENT_CHANNEL, 'code': code})
    disque_client.add_job(kernel_id, json.dumps(message))

    collected_messages = fetch_messages({'stderr': 10, 'code_execution_complete': 1})

    assert len(collected_messages['stderr']) > 0
    assert collected_messages['stderr'][0]['msg_data']['content'].find("Traceback") > -1 \
            or collected_messages['stderr'][1]['msg_data']['content'].find("Traceback") > -1


def test_session_mode(kernel_details_session_mode):
    kernel_id, kernel_proc = kernel_details_session_mode
    code1 = 'i=2'
    code2 = 'print(i)'

    message = form_message(kernel_id, 'code_execution', {'reverse_path': CLIENT_CHANNEL, 'code': code1})
    disque_client.add_job(kernel_id, json.dumps(message))

    collected_messages = fetch_messages({'code_execution_complete': 1})

    message = form_message(kernel_id, 'code_execution', {'reverse_path': CLIENT_CHANNEL, 'code': code2})
    disque_client.add_job(kernel_id, json.dumps(message))

    collected_messages = fetch_messages({'stdout': 1, 'code_execution_complete': 1})

    assert 'stdout' in collected_messages
    assert len(collected_messages['stdout']) == 1

    mesg = collected_messages['stdout'][0]

    assert mesg['msg_data']['content'] == '2\n'

    message = form_message(kernel_id, 'shutdown')
    disque_client.add_job(kernel_id, json.dumps(message))

    try:
        kernel_proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass
    
    assert kernel_proc.returncode != None


def test_input(kernel_details):
    kernel_id, kernel_proc = kernel_details
    code = '''
s = input('Enter something: ')
print(s)
'''

    message = form_message(kernel_id, 'code_execution', {'reverse_path': CLIENT_CHANNEL, 'code': code})
    disque_client.add_job(kernel_id, json.dumps(message))

    collected_messages = fetch_messages({'input_request': 1})
    assert 'input_request' in collected_messages
    assert len(collected_messages['input_request']) == 1
    assert collected_messages['input_request'][0]['msg_data']['prompt'] == 'Enter something: '

    message = form_message(kernel_id, 'input_response', {'content': 'xyz'})
    disque_client.add_job(kernel_id, json.dumps(message))

    collected_messages = fetch_messages({'stdout': 1, 'code_execution_complete': 1})
    assert 'stdout' in collected_messages
    assert len(collected_messages['stdout']) == 1
    assert collected_messages['stdout'][0]['msg_data']['content'] == 'xyz\n'


def test_max_code_execution_time(kernel_details):
    kernel_id, kernel_proc = kernel_details

    code = '''
import time
while True:
    time.sleep(20)
'''

    message = form_message(kernel_id, 'code_execution', {'reverse_path': CLIENT_CHANNEL, 'code': code})
    disque_client.add_job(kernel_id, json.dumps(message))

    collected_messages = fetch_messages({'stderr': 1, 'code_execution_complete': 1}, 5)

    assert 'stderr' in collected_messages
    assert len(collected_messages['stderr']) == 1
    assert collected_messages['stderr'][0]['msg_data']['content'] == 'Code is executing for too long (>2 secs). Quota over.\n'