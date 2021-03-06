
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

__all__ = [
    'ClientSendError',
    'RPCClient',
    'RPCVersionCapError',
]

import inspect
import logging

from oslo.config import cfg

from oslo.messaging._drivers import base as driver_base
from oslo.messaging import _utils as utils
from oslo.messaging import exceptions
from oslo.messaging import serializer as msg_serializer

_client_opts = [
    cfg.IntOpt('rpc_response_timeout',
               default=60,
               help='Seconds to wait for a response from a call'),
]

_LOG = logging.getLogger(__name__)


class RPCVersionCapError(exceptions.MessagingException):

    def __init__(self, version, version_cap):
        self.version = version
        self.version_cap = version_cap
        msg = ("Specified RPC version cap, %(version_cap)s, is too low. "
               "Needs to be higher than %(version)s." %
               dict(version=self.version, version_cap=self.version_cap))
        super(RPCVersionCapError, self).__init__(msg)


class ClientSendError(exceptions.MessagingException):
    """Raised if we failed to send a message to a target."""

    def __init__(self, target, ex):
        msg = 'Failed to send to target "%s": %s' % (target, ex)
        super(ClientSendError, self).__init__(msg)
        self.target = target
        self.ex = ex


class _CallContext(object):

    _marker = object()

    def __init__(self, transport, target, serializer,
                 timeout=None, check_for_lock=None, version_cap=None):
        self.conf = transport.conf

        self.transport = transport
        self.target = target
        self.serializer = serializer
        self.timeout = timeout
        self.check_for_lock = check_for_lock
        self.version_cap = version_cap

        super(_CallContext, self).__init__()

    def _make_message(self, ctxt, method, args):
        msg = dict(method=method)

        msg['args'] = dict()
        for argname, arg in args.iteritems():
            msg['args'][argname] = self.serializer.serialize_entity(ctxt, arg)

        if self.target.namespace is not None:
            msg['namespace'] = self.target.namespace
        if self.target.version is not None:
            msg['version'] = self.target.version

        return msg

    def _check_version_cap(self, version):
        if not utils.version_is_compatible(self.version_cap, version):
            raise RPCVersionCapError(version=version,
                                     version_cap=self.version_cap)

    def can_send_version(self, version=_marker):
        """Check to see if a version is compatible with the version cap."""
        version = self.target.version if version is self._marker else version
        return (not self.version_cap or
                utils.version_is_compatible(self.version_cap,
                                            self.target.version))

    def cast(self, ctxt, method, **kwargs):
        """Invoke a method and return immediately. See RPCClient.cast()."""
        msg = self._make_message(ctxt, method, kwargs)
        if self.version_cap:
            self._check_version_cap(msg.get('version'))
        try:
            self.transport._send(self.target, ctxt, msg)
        except driver_base.TransportDriverError as ex:
            raise ClientSendError(self.target, ex)

    def _check_for_lock(self):
        locks_held = self.check_for_lock(self.conf)
        if locks_held:
            stack = ' :: '.join([frame[3] for frame in inspect.stack()])
            _LOG.warning('An RPC is being made while holding a lock. The '
                         'locks currently held are %(locks)s. This is '
                         'probably a bug. Please report it. Include the '
                         'following: [%(stack)s].',
                         {'locks': locks_held, 'stack': stack})

    def call(self, ctxt, method, **kwargs):
        """Invoke a method and wait for a reply. See RPCClient.call()."""
        msg = self._make_message(ctxt, method, kwargs)

        timeout = self.timeout
        if self.timeout is None:
            timeout = self.conf.rpc_response_timeout

        if self.check_for_lock:
            self._check_for_lock()
        if self.version_cap:
            self._check_version_cap(msg.get('version'))

        try:
            result = self.transport._send(self.target, ctxt, msg,
                                          wait_for_reply=True, timeout=timeout)
        except driver_base.TransportDriverError as ex:
            raise ClientSendError(self.target, ex)
        return self.serializer.deserialize_entity(ctxt, result)

    @classmethod
    def _prepare(cls, base,
                 exchange=_marker, topic=_marker, namespace=_marker,
                 version=_marker, server=_marker, fanout=_marker,
                 timeout=_marker, check_for_lock=_marker, version_cap=_marker):
        """Prepare a method invocation context. See RPCClient.prepare()."""
        kwargs = dict(
            exchange=exchange,
            topic=topic,
            namespace=namespace,
            version=version,
            server=server,
            fanout=fanout)
        kwargs = dict([(k, v) for k, v in kwargs.items()
                       if v is not cls._marker])
        target = base.target(**kwargs)

        if timeout is cls._marker:
            timeout = base.timeout
        if check_for_lock is cls._marker:
            check_for_lock = base.check_for_lock
        if version_cap is cls._marker:
            version_cap = base.version_cap

        return _CallContext(base.transport, target,
                            base.serializer,
                            timeout, check_for_lock,
                            version_cap)

    def prepare(self, exchange=_marker, topic=_marker, namespace=_marker,
                version=_marker, server=_marker, fanout=_marker,
                timeout=_marker, check_for_lock=_marker, version_cap=_marker):
        """Prepare a method invocation context. See RPCClient.prepare()."""
        return self._prepare(self,
                             exchange, topic, namespace,
                             version, server, fanout,
                             timeout, check_for_lock, version_cap)


class RPCClient(object):

    """A class for invoking methods on remote servers.

    The RPCClient class is responsible for sending method invocations to remote
    servers via a messaging transport.

    A default target is supplied to the RPCClient constructor, but target
    attributes can be overridden for individual method invocations using the
    prepare() method.

    A method invocation consists of a request context dictionary, a method name
    and a dictionary of arguments. A cast() invocation just sends the request
    and returns immediately. A call() invocation waits for the server to send
    a return value.

    This class is intended to be used by wrapping it in another class which
    provides methods on the subclass to perform the remote invocation using
    call() or cast()::

        class TestClient(object):

            def __init__(self, transport):
                target = messaging.Target(topic='testtopic', version='2.0')
                self._client = messaging.RPCClient(transport, target)

            def test(self, ctxt, arg):
                return self._client.call(ctxt, 'test', arg=arg)

    An example of using the prepare() method to override some attributes of the
    default target::

        def test(self, ctxt, arg):
            cctxt = self._client.prepare(version='2.5')
            return cctxt.call(ctxt, 'test', arg=arg)

    RPCClient have a number of other properties - timeout, check_for_lock and
    version_cap - which may make sense to override for some method invocations,
    so they too can be passed to prepare()::

        def test(self, ctxt, arg):
            cctxt = self._client.prepare(check_for_lock=None, timeout=10)
            return cctxt.call(ctxt, 'test', arg=arg)

    However, this class can be used directly without wrapping it another class.
    For example:

        transport = messaging.get_transport(cfg.CONF)
        target = messaging.Target(topic='testtopic', version='2.0')
        client = messaging.RPCClient(transport, target)
        client.call(ctxt, 'test', arg=arg)

    but this is probably only useful in limited circumstances as a wrapper
    class will usually help to make the code much more obvious.
    """

    def __init__(self, transport, target,
                 timeout=None, check_for_lock=None,
                 version_cap=None, serializer=None):
        """Construct an RPC client.

        :param transport: a messaging transport handle
        :type transport: Transport
        :param target: the default target for invocations
        :type target: Target
        :param timeout: an optional default timeout (in seconds) for call()s
        :type timeout: int or float
        :param check_for_lock: a callable that given conf returns held locks
        :type check_for_lock: bool
        :param version_cap: raise a RPCVersionCapError version exceeds this cap
        :type version_cap: str
        :param serializer: an optional entity serializer
        :type serializer: Serializer
        """
        self.conf = transport.conf
        self.conf.register_opts(_client_opts)

        self.transport = transport
        self.target = target
        self.timeout = timeout
        self.check_for_lock = check_for_lock
        self.version_cap = version_cap
        self.serializer = serializer or msg_serializer.NoOpSerializer()

        super(RPCClient, self).__init__()

    _marker = _CallContext._marker

    def prepare(self, exchange=_marker, topic=_marker, namespace=_marker,
                version=_marker, server=_marker, fanout=_marker,
                timeout=_marker, check_for_lock=_marker, version_cap=_marker):
        """Prepare a method invocation context.

        Use this method to override client properties for an individual method
        invocation. For example::

            def test(self, ctxt, arg):
                cctxt = self.prepare(version='2.5')
                return cctxt.call(ctxt, 'test', arg=arg)

        :param exchange: see Target.exchange
        :type exchange: str
        :param topic: see Target.topic
        :type topic: str
        :param namespace: see Target.namespace
        :type namespace: str
        :param version: requirement the server must support, see Target.version
        :type version: str
        :param server: send to a specific server, see Target.server
        :type server: str
        :param fanout: send to all servers on topic, see Target.fanout
        :type fanout: bool
        :param timeout: an optional default timeout (in seconds) for call()s
        :type timeout: int or float
        :param check_for_lock: a callable that given conf returns held locks
        :type check_for_lock: bool
        :param version_cap: raise a RPCVersionCapError version exceeds this cap
        :type version_cap: str
        """
        return _CallContext._prepare(self,
                                     exchange, topic, namespace,
                                     version, server, fanout,
                                     timeout, check_for_lock, version_cap)

    def cast(self, ctxt, method, **kwargs):
        """Invoke a method and return immediately.

        Method arguments must either be primitive types or types supported by
        the client's serializer (if any).

        :param ctxt: a request context dict
        :type ctxt: dict
        :param method: the method name
        :type method: str
        :param kwargs: a dict of method arguments
        :param kwargs: dict
        """
        self.prepare().cast(ctxt, method, **kwargs)

    def call(self, ctxt, method, **kwargs):
        """Invoke a method and wait for a reply.

        Method arguments must either be primitive types or types supported by
        the client's serializer (if any).

        :param ctxt: a request context dict
        :type ctxt: dict
        :param method: the method name
        :type method: str
        :param kwargs: a dict of method arguments
        :param kwargs: dict
        :raises: MessagingTimeout
        """
        return self.prepare().call(ctxt, method, **kwargs)

    def can_send_version(self, version=_marker):
        """Check to see if a version is compatible with the version cap."""
        return self.prepare(version=version).can_send_version()
