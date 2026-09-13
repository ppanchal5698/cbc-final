"""The composition root: where the process is assembled, and nothing else.

Modules hold the behaviour; this package wires them into the two processes - the
API (`main`) and the worker (`worker`) - and holds the migrations that run first.
"""
