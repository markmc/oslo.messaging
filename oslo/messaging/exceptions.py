
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright 2013 Red Hat, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

__all__ = ['MessagingException', 'MessagingTimeout']


class MessagingException(Exception):
    """Base class for exceptions."""

    def __init__(self, msg=None):
        self.msg = msg

    def __str__(self):
        return self.msg


class MessagingTimeout(MessagingException):
    """Raised if message sending times out."""


import logging
import sys
import traceback

from oslo.config import cfg

from oslo.messaging.openstack.common import importutils
from oslo.messaging.openstack.common import jsonutils

LOG = logging.getLogger(__name__)

_REMOTE_POSTFIX = '_Remote'


_opts = [
    cfg.ListOpt('allowed_rpc_exception_modules',
                default=['openstack.common.exception',
                         'nova.exception',
                         'cinder.exception',
                         'exceptions',
                         ],
                help='Modules of exceptions that are permitted to be recreated'
                     'upon receiving exception data from an rpc call.'),
]


_ = lambda s: s


class RPCException(Exception):

    format = _("An unknown RPC related exception occurred.")

    def __init__(self, message=None, **kwargs):
        self.kwargs = kwargs

        if not message:
            try:
                message = self.format % kwargs

            except Exception:
                # kwargs doesn't match a variable in the message
                # log the issue and the kwargs
                LOG.exception(_('Exception in string format operation'))
                for name, value in kwargs.iteritems():
                    LOG.error("%s: %s" % (name, value))
                # at least get the core message out if something happened
                message = self.format

        super(RPCException, self).__init__(message)


class RemoteError(RPCException):
    """Signifies that a remote class has raised an exception.

    Contains a string representation of the type of the original exception,
    the value of the original exception, and the traceback.  These are
    sent to the parent as a joined string so printing the exception
    contains all of the relevant info.

    """
    format = _("Remote error: %(exc_type)s %(value)s\n%(traceback)s.")

    def __init__(self, exc_type=None, value=None, traceback=None):
        self.exc_type = exc_type
        self.value = value
        self.traceback = traceback
        super(RemoteError, self).__init__(exc_type=exc_type,
                                          value=value,
                                          traceback=traceback)


def serialize_remote_exception(failure_info, log_failure=True):
    """Serializes an exception into JSON for inclusion in a message.

    Exceptions raised by a remote method are serialized by the server, sent
    back to the client, deserialized and re-raised in such a way that the
    exception seen on the client side is largely indistinguishable from the
    exception raised on the server side.

    This method is responsible for the server-side of the process. The
    exception details supplied by the failure_info argument are serialized into
    a JSON representation:

      {
        "class": <name of the exception type>,
        "module": <module containing the exception type>,
        "message": the stringified representation of the exception,
        'tb': the traceback.format_exception() representation of the exception
        'args': the args attribute of the exception
        'kwargs': the kwargs attribute of the exception, if any
      }

    See deserialize_remote_exception() for details about the expected semantics
    of deserialized exceptions. This method takes care to correctly handle the
    case where previously deserialized remote exceptions are serialized again.

    :param failure_info: a sys.exc_info() tuple.
    :type failure_info: tuple
    :param log_failure: whether to log the suppled exception at error level
    :type log_failure: bool
    """
    tb = traceback.format_exception(*failure_info)
    failure = failure_info[1]
    if log_failure:
        LOG.error(_("Returning exception %s to caller"),
                  unicode(failure))
        LOG.error(tb)

    kwargs = {}
    if hasattr(failure, 'kwargs'):
        kwargs = failure.kwargs

    # NOTE(matiu): With cells, it's possible to re-raise remote, remote
    # exceptions. Lets turn it back into the original exception type.
    cls_name = str(failure.__class__.__name__)
    mod_name = str(failure.__class__.__module__)
    if (cls_name.endswith(_REMOTE_POSTFIX) and
            mod_name.endswith(_REMOTE_POSTFIX)):
        cls_name = cls_name[:-len(_REMOTE_POSTFIX)]
        mod_name = mod_name[:-len(_REMOTE_POSTFIX)]

    data = {
        'class': cls_name,
        'module': mod_name,
        'message': unicode(failure),
        'tb': tb,
        'args': failure.args,
        'kwargs': kwargs
    }

    json_data = jsonutils.dumps(data)

    return json_data


def deserialize_remote_exception(conf, data):
    """Deserialize a remote exception into a true exception object.

    Exceptions raised by a remote method are serialized by the server, sent
    back to the client, deserialized and re-raised in such a way that the
    exception seen on the client side is largely indistinguishable from the
    exception raised on the server side.

    This method is responsible for the client-side of the process. The JSON
    representation of the exception is deserialized into an exception object.

    Only Exception sub-classes in the modules included in the
    allowed_rpc_exception_modules configuration option will be deserialized to
    their original type. Any other types will be deserialized to the
    RemoteError type which includes the original type name, the stringified
    representation of the original exception and the original traceback.

    Remote exception types which are unknown to the caller, or perhaps whose
    constructor signatur differs from the remote side, are similarly
    deserialized to RemoteError.

    For exceptions other than core runtime exceptions, the class name of the
    deserialized exception will have '_Remote' appended to its name. This
    allows the client to distinguish between local and remote exceptions.

    As part of the deserialization process, the original traceback is also
    appended to the exception message. The original message is available via
    the first element of the exceptions args list.

    Note that the less you rely on some of the more obscure semantics listed
    above, the better. At least some of them are likely to change in subtle
    was in future.

    :param conf: the user configuration
    :type conf: ConfigOpts
    :param data: a JSON representation of an exception
    :type data: str
    :returns: an exception object
    """
    failure = jsonutils.loads(str(data))

    trace = failure.get('tb', [])
    message = failure.get('message', "") + "\n" + "\n".join(trace)
    name = failure.get('class')
    module = failure.get('module')

    # NOTE(ameade): We DO NOT want to allow just any module to be imported, in
    # order to prevent arbitrary code execution.
    if module not in conf.allowed_rpc_exception_modules:
        return RemoteError(name, failure.get('message'), trace)

    try:
        mod = importutils.import_module(module)
        klass = getattr(mod, name)
        if not issubclass(klass, Exception):
            raise TypeError("Can only deserialize Exceptions")

        failure = klass(*failure.get('args', []), **failure.get('kwargs', {}))
    except (AttributeError, TypeError, ImportError):
        return RemoteError(name, failure.get('message'), trace)

    ex_type = type(failure)
    str_override = lambda self: message
    new_ex_type = type(ex_type.__name__ + _REMOTE_POSTFIX, (ex_type,),
                       {'__str__': str_override, '__unicode__': str_override})
    new_ex_type.__module__ = '%s%s' % (module, _REMOTE_POSTFIX)
    try:
        # NOTE(ameade): Dynamically create a new exception type and swap it in
        # as the new type for the exception. This only works on user defined
        # Exceptions and not core python exceptions. This is important because
        # we cannot necessarily change an exception message so we must override
        # the __str__ method.
        failure.__class__ = new_ex_type
    except TypeError:
        # NOTE(ameade): If a core exception then just add the traceback to the
        # first exception argument.
        failure.args = (message,) + failure.args[1:]
    return failure


class ClientException(Exception):
    """Encapsulates actual exception expected to be hit by a RPC proxy object.

    Merely instantiating it records the current exception information, which
    will be passed back to the RPC client without exceptional logging.
    """
    def __init__(self):
        self._exc_info = sys.exc_info()


def catch_client_exception(exceptions, func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except Exception as e:
        if type(e) in exceptions:
            raise ClientException()
        else:
            raise


def client_exceptions(*exceptions):
    """Decorator for manager methods that raise expected exceptions.

    Marking a Manager method with this decorator allows the declaration
    of expected exceptions that the RPC layer should not consider fatal,
    and not log as if they were generated in a real error scenario. Note
    that this will cause listed exceptions to be wrapped in a
    ClientException, which is used internally by the RPC layer.
    """
    def outer(func):
        def inner(*args, **kwargs):
            return catch_client_exception(exceptions, func, *args, **kwargs)
        return inner
    return outer
