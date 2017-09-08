#!/usr/bin/env python3

from .messaging import get_messages, send_message, ack_message
from .utils import form_message
import json
from datetime import datetime
from plutoid import Executor
from blinker import signal as blinker_signal
import logging
import base64
import sys
import signal

logger = logging.getLogger(__name__)


DEFAULT_MESSAGING_TIMEOUT = 2


class KernelState(object):
    def __init__(self, kernel_id):
        self.kernel_id = kernel_id

        self.cmds_in_progress = []
        self.last_ping_request_timestamp = datetime.now()

        self.code_execution_revese_path = None
        self.code_execution_msg_id = None
        self.code_execution_start_time = 0

        self.last_input_response = None

        self.pending_stdout_chunks = []
        self.pending_stderr_chunks = []

    
    def reset_code_execution_state(self):
        self.mark_not_in_progress('input_request')
        self.mark_not_in_progress('code_execution')
        self.code_execution_revese_path = None
        self.code_execution_msg_id = None
        self.code_execution_start_time = 0
        self.pending_stdout_chunks = []
        self.pending_stderr_chunks = []

    
    def mark_in_progress(self, cmd):
        self.cmds_in_progress.append(cmd)


    def mark_not_in_progress(self, cmd):
        if cmd in self.cmds_in_progress:
            self.cmds_in_progress.remove(cmd)


    def is_in_progress(self, cmd):
        return cmd in self.cmds_in_progress


    def is_executing_code(self):
        return self.is_in_progress("code_execution")


    def is_awaiting_input(self):
        return self.is_in_progress("input_request")


class Kernel(object):
    def __init__(self, kernel_id, session_mode, ping_interval, input_timeout, max_code_execution_time):
        self.kernel_id = kernel_id
        self.session_mode = session_mode
        self.ping_interval = ping_interval
        self.input_timeout = input_timeout
        self.max_code_execution_time = max_code_execution_time

        self.kernel_state = KernelState(self.kernel_id)
        self.executor = Executor(self.fetch_input, self.max_code_execution_time)

        blinker_signal('plutoid::stdout').connect(self.publish_stdout)
        blinker_signal('plutoid::stderr').connect(self.publish_stderr)
        blinker_signal('plutoid::matplotlib').connect(self.publish_matplotlib)


    def fetch_input(self, prompt):
        response = form_message(self.kernel_id, 'input_request',
                        {'in_response_to': self.kernel_state.code_execution_msg_id,
                         'prompt': prompt})

        send_message(self.kernel_state.code_execution_revese_path, json.dumps(response))

        self.kernel_state.mark_in_progress('input_request')
        self.fetch_and_process_messages(valid_msg_types=['input_response', 'shutdown'], 
            awaited_msg_type='input_response', duration=self.input_timeout)
        self.kernel_state.mark_not_in_progress('input_request')

        if self.kernel_state.last_input_response:
            content = self.kernel_state.last_input_response['msg_data']['content']
            self.kernel_state.last_input_response = None
        else:
            logger.warn('Did not receive input_response.')
            content = ''

        return content
        

    def publish_stdout(self, sender, content):
        self.publish_output('stdout', sender, content)


    def publish_stderr(self, sender, content):
        self.publish_output('stderr', sender, content)


    def publish_output(self, stdout_or_stderr, sender, content):
        if not content: return

        if not self.kernel_state.is_executing_code():
            logger.warn('Side effect %s observed while not executing code')
            return

        if stdout_or_stderr == 'stdout':
            chunks = self.kernel_state.pending_stdout_chunks
        else:
            chunks = self.kernel_state.pending_stderr_chunks

        chunks.append(content)
        if content[-1] != '\n':
            return

        logger.info('Publishing side effect of type %s' % stdout_or_stderr)

        response = form_message(self.kernel_id, stdout_or_stderr, {
                        'in_response_to': self.kernel_state.code_execution_msg_id,
                        'content': ''.join(chunks)
                    })

        send_message(self.kernel_state.code_execution_revese_path, json.dumps(response))

        if stdout_or_stderr == 'stdout':
            self.kernel_state.pending_stdout_chunks = []
        else:
            self.kernel_state.pending_stderr_chunks = []


    def publish_matplotlib(self, sender, mimetype, content):
        if not self.kernel_state.is_executing_code():
            logger.warn('Side effect matplotlib observed while not executing code')
            return

        logger.info('Publishing side effect of type matplotlib')

        response = form_message(self.kernel_id, 'matplotlib_drawing', {
                        'in_response_to': self.kernel_state.code_execution_msg_id,
                        mimetype: mimetype,
                        content: base64.b64encode(content)
                    })

        send_message(self.kernel_state.code_execution_revese_path, json.dumps(response))


    def handle_ping_request(self, message):
        if 'msg_data' not in message or 'reverse_path' not in message['msg_data']:
            logger.warn('Invalid ping request: %s' % json.dumps(message))
            return

        response = form_message(self.kernel_id, 'ping_response',
                        {'in_response_to': message['header']['msg_id']})

        send_message(message['msg_data']['reverse_path'], json.dumps(response))

        self.kernel_state.last_ping_request_timestamp = datetime.now()


    def handle_code_execution(self, message):
        if 'msg_data' not in message or 'reverse_path' not in message['msg_data'] or 'code' not in message['msg_data']:
            logger.warn('Invalid code execution message: %s' % json.dumps(message))
            return

        if self.kernel_state.is_in_progress('code_execution'):
            logger.warn('Received code execution message while already executing code: %s' % json.dumps(message))
            return

        self.kernel_state.code_execution_revese_path = message['msg_data']['reverse_path']
        self.kernel_state.code_execution_msg_id = message['header']['msg_id']
        self.kernel_state.mark_in_progress('code_execution')

        code = message['msg_data']['code']
        self.executor.exec_code(code)

        self.send_code_execution_complete()
        self.kernel_state.reset_code_execution_state()

        if not self.session_mode:
            self.shutdown()


    def handle_shutdown(self):
        self.shutdown()

    
    def shutdown(self):
        logger.info('Shutting down')
        sys.exit()


    def start(self):
        logger.info('Kernel with id %s started.' % self.kernel_id)

        self.fetch_and_process_messages()

        logger.info('Kernel with id %s exiting.' % self.kernel_id)


    def fetch_and_process_messages(self, valid_msg_types=None, awaited_msg_type=None, duration=0):
        if awaited_msg_type:
            received_awaited_message = False
        else:
            received_awaited_message = True

        loop_start_time = datetime.now()

        while True:
            ping_messages = []
            non_ping_messages = []

            messages = get_messages(self.kernel_id, timeout=DEFAULT_MESSAGING_TIMEOUT)
            logger.debug('Received %d messages.' % len(messages))

            for queue_name, system_message_id, message in messages:
                message = json.loads(message)
                ack_message(system_message_id)

                if not self.is_valid_message(message):
                    logger.warn('Recevied invalid message: %s' % json.dumps(message))
                    continue

                msg_type = message['header']['msg_type']
                if msg_type == 'ping_request':
                    ping_messages.append(message)
                elif not valid_msg_types or msg_type in valid_msg_types:
                    non_ping_messages.append(message)
                else:
                    logger.warn('Invalid message type for the current state: %s' % json.dumps(message))

                if awaited_msg_type and msg_type == awaited_msg_type:
                    received_awaited_message = True

            for message in ping_messages:
                self.process_message(message)

            for message in non_ping_messages:
                self.process_message(message)

            self.validate_ping_timeout()

            if awaited_msg_type and received_awaited_message:
                break

            if duration and (datetime.now() - loop_start_time).total_seconds() > duration:
                break

    
    def validate_ping_timeout(self):
        ping_delta = (datetime.now() - self.kernel_state.last_ping_request_timestamp).total_seconds()
        if ping_delta > 2*self.ping_interval:
            logger.warn('Did not receive ping for %d seconds.' % ping_delta)
            self.shutdown()
        else:
            logger.debug('%d secodns before ping timeout.' % (2*self.ping_interval - ping_delta))


    def process_message(self, message):
        msg_type = message['header']['msg_type']

        logger.info('Processing message of type %s' % msg_type)

        if msg_type == 'ping_request':
            self.handle_ping_request(message)
        elif msg_type == 'code_execution':
            self.handle_code_execution(message)
        elif msg_type == 'input_response':
            self.kernel_state.last_input_response = message
        elif msg_type == 'shutdown':
            self.handle_shutdown()
        else:
            logger.warn('Received message of unknown type: %s' % json.dumps(message))


    def send_code_execution_complete(self):
        response = form_message(self.kernel_id, 'code_execution_complete',
                        {'in_response_to': self.kernel_state.code_execution_msg_id,
                         'stdout': ''.join(self.kernel_state.pending_stdout_chunks),
                         'stderr': ''.join(self.kernel_state.pending_stderr_chunks)})

        send_message(self.kernel_state.code_execution_revese_path, json.dumps(response))


    def is_valid_message( self, message):
        if 'header' not in message: return False

        header = message['header']
        for field in ['kernel_id', 'msg_id', 'msg_type', 'timestamp']:
            if field not in header: return False

        return True