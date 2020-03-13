#!/usr/bin/python
#
# Copyright (c) 2017-2019 NVIDIA CORPORATION. All rights reserved.
# This file is part of the WebDataset library.
# See the LICENSE file for licensing terms (BSD-style).
#


"""Train PyTorch models directly from POSIX tar archive, locally
or over HTTP connections.
"""

__all__ = "WebDataset tariterator default_handlers imagehandler".split()

import random
from functools import reduce, wraps

from .checks import checktype
from . import autodecode


def reraise_exception(exn):
    raise exn


def curried(f):
    """A decorator for currying functions in the first argument."""

    @wraps(f)
    def wrapper(*args, **kw):
        def g(x):
            return f(x, *args, **kw)

        return g

    return wrapper


def compose2(f, g):
    """Compose two functions, g(f(x))"""
    return lambda x: g(f(x))


def compose(*args):
    """Compose a sequence of functions (left-to-right)"""
    return reduce(compose2, args)


def pipeline(source, *args):
    """Write an input pipeline; first argument is source, rest are filters."""
    if len(args) == 0:
        return source
    return compose(*args)(source)


def getfirst(a, keys, default=None):
    if isinstance(keys, str):
        keys = keys.split(";")
    for k in keys:
        result = a.get(k)
        if result is not None:
            return result
    return default


def parse_field_spec(fields):
    if isinstance(fields, str):
        fields = fields.split()
    return [field.split(";") for field in fields]


def transform_with(sample, transformers):
    """Transform a list of values using a list of functions.

    sample: list of values
    transformers: list of functions

    """
    checktype(sample, (tuple, list))
    if transformers is None or len(transformers) == 0:
        return sample
    result = list(sample)
    ntransformers = len(transformers)
    for i in range(len(sample)):  # skipcq: PYL-C0200
        f = transformers[i % ntransformers]
        if f is not None:
            result[i] = f(sample[i])
    return result


def transformer(transformers):
    """Curried version of `transform_with`.

    transformers :

    """

    def f(x):
        return transform_with(x, transformers)

    return f


# @curried
# def associate(data, associator):
#     """Extract the given fields and return a tuple.
#     """
#     for sample in data:
#         if callable(associator):
#             extra = associator(sample["__key__"])
#         else:
#             extra = associator.get(sample["__key__"], {})
#         sample.update(extra)
#         yield sample


# @curried
# def extract(data, *fields):
#     """Extract the given fields and return a tuple.
#     """
#     for sample in data:
#         if fields is None:
#             yield sample
#         else:
#             yield [getfirst(sample, f) for f in fields]


@curried
def map_stream(data, f=None, handler=reraise_exception):
    """Map entire samples using the given function.

    data: iterator
    f: function from samples to samples
    returns: iterator over transformed samples

    """

    if f is None:

        def f(x):  # skipcq: PYL-E0102
            return x

    for sample in data:
        try:
            result = f(sample)
        except Exception as exn:
            if handler(exn):
                continue
            else:
                break
        if isinstance(sample, dict) and isinstance(result, dict):
            result["__key__"] = sample.get("__key__")
        yield result


@curried
def shuffle(data, bufsize=1000, initial=100):
    """Shuffle the data in the stream.

    This uses a buffer of size `bufsize`. Shuffling at
    startup is less random; this is traded off against
    yielding samples quickly.

    data: iterator
    bufsize: buffer size for shuffling
    returns: iterator

    """
    initial = min(initial, bufsize)
    buf = []
    startup = True
    for sample in data:
        if len(buf) < bufsize:
            try:
                buf.append(next(data))  # skipcq: PYL-R1708
            except StopIteration:
                pass
        k = random.randint(0, len(buf) - 1)
        sample, buf[k] = buf[k], sample
        if startup and len(buf) < initial:
            buf.append(sample)
            continue
        startup = False
        yield sample
    for sample in buf:
        yield sample


def decode(decoder="rgb", handler=reraise_exception):
    f = autodecode.make_decoder(decoder)

    def stage(data):
        for sample in data:
            assert isinstance(sample, dict), sample
            try:
                decoded = f(sample)
            except Exception as exn:  # skipcq: PYL-W0703
                if handler(exn):
                    continue
                else:
                    break
            yield decoded

    return stage


def map(f, handler=reraise_exception):
    def stage(data):
        for sample in data:
            try:
                result = f(sample)
            except Exception as exn:
                if handler(exn):
                    continue
                else:
                    break
            if isinstance(sample, dict) and isinstance(result, dict):
                result["__key__"] = sample.get("__key__")
            yield result

    return stage


def rename(handler=reraise_exception, **kw):
    def stage(data):
        for sample in data:
            try:
                yield {k: getfirst(sample, v) for k, v in kw.items()}
            except Exception as exn:
                if handler(exn):
                    continue
                else:
                    break

    return stage


def associate(associator, **kw):
    def stage(data):
        for sample in data:
            if callable(associator):
                extra = associator(sample["__key__"])
            else:
                extra = associator.get(sample["__key__"], {})
            sample.update(extra)  # destructive
            yield sample

    return stage


def transform(handler=reraise_exception, **kw):
    assert len(list(kw.keys())) > 0
    for f in kw.values():
        assert callable(f)

    def stage(data):
        for sample in data:
            assert isinstance(sample, dict)
            try:
                for k, f in kw:
                    sample[k] = f(sample[k])
            except Exception as exn:
                if handler(exn):
                    continue
                else:
                    break
            yield sample

    return stage


def extract(*args, handler=reraise_exception):
    def stage(data):
        for sample in data:
            try:
                yield [getfirst(sample, f) for f in args]
            except Exception as exn:
                if handler(exn):
                    continue
                else:
                    break

    return stage


def apply(*args, handler=reraise_exception):
    def stage(data):
        for f in args:
            assert callable(f)
        for sample in data:
            assert isinstance(sample, (list, tuple))
            assert len(args) == len(sample)
            sample = list(sample)
            try:
                for i in range(min(len(args), len(sample))):
                    sample[i] = args[i](sample[i])
            except Exception as exn:
                if handler(exn):
                    continue
                else:
                    break
            yield sample

    return stage
