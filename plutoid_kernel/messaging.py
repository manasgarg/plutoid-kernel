#!/usr/bin/env python3

from pydisque.client import Client as DisqueClient
import logging

logger = logging.getLogger(__name__)
disque_client = None

def init(disque_servers=(("localhost",7711),)):
    disque_servers = ["%s:%d" % disque_server for disque_server in disque_servers]

    logger.info('Connecting to disque servers: %s' % ', '.join(disque_servers))

    global disque_client
    disque_client = DisqueClient(disque_servers)
    disque_client.connect()

def get_messages(queue_name, timeout):
    logger.info('Getting messages from queue %s with timeout %d' % (queue_name, timeout))
    return disque_client.get_job([queue_name], timeout=timeout*1000)

def send_message(queue_name, message):
    logger.info('Sending message to queue %s' % queue_name)
    disque_client.add_job(queue_name, message)

def ack_message(system_message_id):
    logger.debug('Acking message id %s' % system_message_id)
    disque_client.ack_job(system_message_id)