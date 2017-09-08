# plutoid-kernel

`plutoid-kernel` builds upon the `plutiod` library and provides the capabilities of running a standalone python kernel. It's equivalent to `ipykernel` from the Jupyter eco-system. It has a messaging interface and via that interface, it accepts code execution commands, publishes side effects, responds to heartbeat and asks for input.