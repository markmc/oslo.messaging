
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

__all__ = ['get_rpc_server']

from oslo.messaging.rpc import dispatcher as rpc_dispatcher
from oslo.messaging import server as msg_server

"""
An RPC server exposes a number of endpoints, each of which contain a set of
methods which may be invoked remotely by clients over a given transport.

To create an RPC server, you supply a transport, target and a list of
endpoints.

A transport can be obtained simply by calling the get_transport() method:

    transport = messaging.get_transport(conf)

which will load the appropriate transport driver according to the user's
messaging configuration configuration. See get_transport() for more details.

The target supplied when creating an RPC server expresses the topic, server
name and - optionally - the exchange to listen on. See Target for more details
on these attributes.

Each endpoint object may have a target attribute which may have namespace and
version fields set. By default, we use the 'null namespace' and version 1.0.
Incoming method calls will be dispatched to the first endpoint with the
requested method, a matching namespace and a compatible version number.

RPC servers have start(), stop() and wait() messages to begin handling
requests, stop handling requests and wait for all in-process requests to
complete.

An RPC server class is provided for each supported I/O handling framework.
Currently BlockingRPCServer and eventlet.RPCServer are available.

A simple example of an RPC server with multiple endpoints might be:

    from oslo.config import cfg
    from oslo import messaging

    class ServerControlEndpoint(object):

        target = messaging.Target(namespace='control',
                                  version='2.0')

        def __init__(self, server):
            self.server = server

        def stop(self, ctx):
            self.server.stop()

    class TestEndpoint(object):

        def test(self, ctx, arg):
            return arg

    transport = messaging.get_transport(cfg.CONF)
    target = messaging.Target(topic='test', server='server1')
    endpoints = [
        ServerControlEndpoint(self),
        TestEndpoint(),
    ]
    server = messaging.get_rpc_server(transport, target, endpoints)
    server.start()
    server.wait()

Clients can invoke methods on the server by sending the request to a topic and
it gets sent to one of the servers listening on the topic, or by sending the
request to a specific server listening on the topic, or by sending the request
to all servers listening on the topic (known as fanout). These modes are chosen
via the server and fanout attributes on Target but the mode used is transparent
to the server.

The first parameter to method invocations is always the request context
supplied by the client.

Parameters to the method invocation are primitive types and so must be the
return values from the methods. By supplying a serializer object, a server can
deserialize arguments from - serialize return values to - primitive types.
"""


def get_rpc_server(transport, target, endpoints,
                   executor='blocking', serializer=None):
    """Construct an RPC server.

    The executor parameter controls how incoming messages will be received and
    dispatched. By default, the most simple executor is used - the blocking
    executor.

    :param transport: the messaging transport
    :type transport: Transport
    :param target: the exchange, topic and server to listen on
    :type target: Target
    :param endpoints: a list of endpoint objects
    :type endpoints: list
    :param executor: name of a message executor - e.g. 'eventlet', 'blocking'
    :type executor: str
    :param serializer: an optional entity serializer
    :type serializer: Serializer
    """
    dispatcher = rpc_dispatcher.RPCDispatcher(endpoints, serializer)
    return msg_server.MessageHandlingServer(transport, target,
                                            dispatcher, executor)
