#!/usr/bin/env python3

import click
from plutoid_kernel.kernel import Kernel
from plutoid_kernel.messaging import init as init_messaging
import logging
import logging.config

logger = logging.getLogger(__name__)


def validate_kernel_id(ctx, param, value):
    if not value:
        raise click.BadParameter('kernel-id must be a UUID.')
    
    return value


def setup_logging(verbose, logdir):
    loglevel = logging.INFO
    if verbose: loglevel = logging.DEBUG

    logging.config.dictConfig({
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'standard': {
                'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
            },
        },
        'handlers': {
            'default': {
                'level': loglevel,
                'class': 'logging.StreamHandler',
                'formatter': 'standard'
            },
        },
        'loggers': {
            '': {
                'handlers': ['default'],
                'level': loglevel,
                'propagate': True
            }
        }
    })


@click.command()
@click.option('--kernel-id', callback=validate_kernel_id)
@click.option('--verbose', is_flag=True)
@click.option('--logdir')
@click.option('--session-mode', is_flag=True)
@click.option('--disque-server', multiple=True, type=(str, int), default=(('localhost', 7711),))
@click.option('--ping-interval', default=15)
@click.option('--input-timeout', default=600)
@click.option('--max-code-execution-time', default=15)
def main(kernel_id, verbose, logdir, session_mode, disque_server, ping_interval, input_timeout, max_code_execution_time):
    setup_logging(verbose, logdir)

    logger.info('Starting plutoid kernel...')

    init_messaging(disque_server)

    kernel = Kernel(kernel_id, session_mode, ping_interval, input_timeout, max_code_execution_time)
    kernel.start()



if __name__ == "__main__":
    main()