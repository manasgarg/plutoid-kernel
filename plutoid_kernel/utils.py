#!/usr/bin/env python3

import uuid
from datetime import datetime

def form_message(kernel_id, msg_type, msg_data={}):
    return {
        'header': {
            'kernel_id': kernel_id,
            'msg_type': msg_type,
            'msg_id': str(uuid.uuid4()),
            'timestamp': datetime.utcnow().isoformat()
        },
        'msg_data': msg_data
    }