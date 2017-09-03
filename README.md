# plutoid-kernel

`plutoid-kernel` builds upon the `plutiod` library and provides the capabilities of running a standalone python kernel. It's equivalent to `ipykernel` from the Jupyter eco-system. It has a messaging interface and via that interface, it accepts code execution commands, publishes side effects, responds to heartbeat and asks for input.

## Operational Overview

First step is to start the `plutoid-kernel` process and specify at least the following two parameters on the command line: `--id <kernel-id>` and `--disque-servers <host:port>`. When the kernel starts, it connects to the `disque` server and waits for messages on the `kernel-id` channel. The kernel is now ready to execute code.

A client can now send message of type `code_execution` to the `kernel-id` queue on `disque` server. The `plutoid-kernel` will execute the code from that message and publish all the side effects back on the `disque` server.

When a client sends message to `plutoid-kernel`, it must do two things:
* Publish the message to `kernel-id` queue on disque server. That's where `plutoid-kernel` will look for the messages.
* In all messages, the client must specify a queue name where `plutoid-kernel` can publish all the side effects like stdout, stderr, matplotlib drawings etc.

A client must also periodically publish `ping_request` message for the heartbeat mechanism. If the client does not recieve two successive `ping_response` messages, it should assume the `plutoid-kernel` to be dead.


## Invocation

The first set of inputs to the kernel come from the command line interface when the kernel is spawned. It recieves the following arguments:

* `--id <kernel-id>` - Mandatory. This id is used in messaging. Must be a UUID which is generated afresh whenever a kernel is spawned.
* `--session-mode` - Enabling session model keeps the kernel running and serve multiple code execution requests. Otherwise, it would exit after serving a single request.
* `--disque-servers <host1:port1>,<host2:port2>,<host3:port3>` - A comma separated list of disque servers. Default is `localhost:7711`.
* `--ping-interval <seconds>` - Number of seconds within which a ping must come from the client as heartbeat mechanism. If the heartbeat is missed twice, the kernel will exit. Default is 15 seconds.
* `--input-timeout <seconds>` - Number of seconds for which kernel will wait for an input response. If the response does not come within this duration, the kernel will terminate the code execution with an exception. Default is 600 seconds.

## Messaging Interface

`plutoid-kernel` makes use of `disque` for all the messaging needs and all messages are encoded as `JSON` objects. The I/O related code is abstracted out. So, you can integrate it with your choice of messaging infrastructure.

### Disque Queue Name

After starting up, the `plutoid-kernel` will expect to receive all messages from the `disque` queue with the same name as `kernel-id`. So, the general flow is to generate a uuid and use that as the `kernel-id` when `plutoid-kernel` is spawned. Subsequently, all messages to that kernel are to be published to the `disque` queue by the same name as that `kernel-id`.

### Message format

All messages are modeled based on the following format:

```json
{
    "header": {
        "kernel_id": "<kernel-id>",
        "msg_id": "<msg-id>",
        "msg_type": "<msg-type>",
        "timestamp": "<timestamp>"
    },
    "msg_data": {}
}
```

Explanation of fields in the header:
* `kernel_id` is the id of the kernel as per the command line argument during invocation of kernel.
* `msg_id` is the id of this particular message. This must be unique per message. Expected to be a UUID.
* `msg_type` could be `ping_request`, `ping_response`, `code_execution`, `input_request`, `input_response`, `stdout`, `stderr`, `matplotlib_drawing`, `completion`.
* `timestamp` is the create time of message in ISO8601 format (e.g. 2017-09-02T05:41:58+00:00).

`msg_data` depends on individual `msg_type` and its format is documented along with the `msg_type`.

### Ping

The client system (or the application that requests code execution) must periodically issue `ping_request`. It should also expect a `ping_response`. If it misses two responses, it can assume that the `plutoid-kernel` is not alive.

`ping_request` has the following schema:

```json
{
    "header": {
        "kernel_id": "<kernel-id>",
        "msg_id": "<msg-id>",
        "msg_type": "ping_request",
        "timestamp": "<timestamp>"
    },
    "msg_data": {
        "reverse_path": "<disque-queue-name>"
    }
}
```

The `msg_data` section for `ping_request` has one field: `reverse_path`. This is the name of the disque queue where `ping_response` must be published. If unspecified, it defaults to the `kernel-id`.

`ping_response` has the following schema:

```json
{
    "header": {
        "kernel_id": "<kernel-id>",
        "msg_id": "<msg-id>",
        "msg_type": "ping_response",
        "timestamp": "<timestamp>"
    },
    "msg_data": {
        "in_response_to": "<ping-request-msg-id>"
    }
}
```

The `msg_data` section for `ping_response` has one field: `in_response_to`. It has the `msg_id` of the `ping_request` that's being responded to.

### Code Execution

All code execution requests are submitted by using the `code_execution` message. Here is the schema:

```json
{
    "header": {
        "kernel_id": "<kernel-id>",
        "msg_id": "<msg-id>",
        "msg_type": "code_execution",
        "timestamp": "<timestamp>"
    },
    "msg_data": {
        "reverse_path": "<disque-queue-name>",
        "code": "<code-to-be-executed>"
    }
}
```

The `msg_data` for `code_execution` has the following fields:
* `reverse_path`: It's the name of disque queue where all side effects are published and the `input_request` is sent in the context of this code execution.
* `code`: The code that needs to be executed.

### Stdout / Stderr

Whenever some data is published on stdout or stderr, it is published with `msg_type` as `stdout` or `stderr`. Both message types have the same schema except for the value of `msg_type` field. Here is a sample:

```json
{
    "header": {
        "kernel_id": "<kernel-id>",
        "msg_id": "<msg-id>",
        "msg_type": "stdout",
        "timestamp": "<timestamp>"
    },
    "msg_data": {
        "in_response_to": "<code-execution-msg-id>",
        "content": "<content-on-stdout>"
    }
}
```

The `msg_data` for `stdout` as well as `stderr` has the following fields:
* `in_response_to`: It's the `msg_id` of the `code_execution` message.
* `content`: It's the actual content to be printed on stdout or stderr.

### Matplotlib Drawing

The `matplotlib_drawing` message publishes any drawings generated by matplotlib in the course of code execution. The schema looks as follows:

```json
{
    "header": {
        "kernel_id": "<kernel-id>",
        "msg_id": "<msg-id>",
        "msg_type": "matplotlib_drawing",
        "timestamp": "<timestamp>"
    },
    "msg_data": {
        "in_response_to": "<code-execution-msg-id>",
        "mime_type": "image/png",
        "content": "<base64-encoded-image-data>"
    }
}
```

Here is an explanation of the fields in `msg_data`:
* `in_response_to`: It's the `msg_id` of the original `code_execution` message.
* `mime_type`: It's the mime type of the image. As of now, only `image/png` is supported.
* `content`: Base64 encoded image data. If you convert it back to binary and save it into a file, that's an image file that was generated by matplotlib.

### Completion

The `completion` message type indicates that code execution is complete and all the messages in this context have been published. The schema looks as follows:

```json
{
    "header": {
        "kernel_id": "<kernel-id>",
        "msg_id": "<msg-id>",
        "msg_type": "completion",
        "timestamp": "<timestamp>"
    },
    "msg_data": {
        "in_response_to": "<code-execution-msg-id>",
    }
}
```

The field `in_response_to` in the `msg_data` is the `msg_id` of original `code_execution` message.