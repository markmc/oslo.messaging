# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack Foundation
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

import json
import threading
import time

from six import moves

from oslo import messaging
from oslo.messaging._drivers import base


class FakeIncomingMessage(base.IncomingMessage):
    def __init__(self, listener, ctxt, message, topic, server, fanout,
                 reply_q):
        super(FakeIncomingMessage, self).__init__(listener, ctxt, message)
        self._topic = topic
        self._server = server
        self._fanout = fanout
        self._reply_q = reply_q

    def reply(self, reply=None, failure=None, log_failure=True):
        if self._reply_q:
            failure = failure[1] if failure else None
            self._reply_q.put((reply, failure))

    def requeue(self):
        self.listener._exchange.deliver_message(
            self._topic, self.ctxt, self.message,
            server=self._server, fanout=self._fanout,
            reply_q=self._reply_q)


class FakeListener(base.Listener):

    def __init__(self, driver, exchange, targets):
        super(FakeListener, self).__init__(driver)
        self._exchange = exchange
        self._targets = targets

    def poll(self):
        while True:
            for target in self._targets:
                (ctxt, message, server, fanout, reply_q) = \
                    self._exchange.poll(target)
                if message is not None:
                    message = FakeIncomingMessage(self, ctxt, message,
                                                  target.topic,
                                                  server, fanout, reply_q)
                    message.acknowledge()
                    return message
            time.sleep(.05)


class FakeExchange(object):

    def __init__(self, name):
        self.name = name
        self._queues_lock = threading.Lock()
        self._topic_queues = {}
        self._server_queues = {}

    def _get_topic_queue(self, topic):
        return self._topic_queues.setdefault(topic, [])

    def _get_server_queue(self, topic, server):
        return self._server_queues.setdefault((topic, server), [])

    def deliver_message(self, topic, ctxt, message,
                        server=None, fanout=False, reply_q=None):
        with self._queues_lock:
            if fanout:
                queues = [q for t, q in self._server_queues.items()
                          if t[0] == topic]
            elif server is not None:
                queues = [self._get_server_queue(topic, server)]
            else:
                queues = [self._get_topic_queue(topic)]
            for queue in queues:
                queue.append((ctxt, message, server, fanout, reply_q))

    def poll(self, target):
        with self._queues_lock:
            if target.server:
                queue = self._get_server_queue(target.topic, target.server)
            else:
                queue = self._get_topic_queue(target.topic)
            return queue.pop(0) if queue else (None, None, None, None, None)


class FakeDriver(base.BaseDriver):

    def __init__(self, conf, url, default_exchange=None,
                 allowed_remote_exmods=[]):
        super(FakeDriver, self).__init__(conf, url, default_exchange,
                                         allowed_remote_exmods=[])

        self._default_exchange = default_exchange

        self._exchanges_lock = threading.Lock()
        self._exchanges = {}

    @staticmethod
    def _check_serialize(message):
        """Make sure a message intended for rpc can be serialized.

        We specifically want to use json, not our own jsonutils because
        jsonutils has some extra logic to automatically convert objects to
        primitive types so that they can be serialized.  We want to catch all
        cases where non-primitive types make it into this code and treat it as
        an error.
        """
        json.dumps(message)

    def _get_exchange(self, name):
        while self._exchanges_lock:
            return self._exchanges.setdefault(name, FakeExchange(name))

    def _send(self, target, ctxt, message, wait_for_reply=None, timeout=None):
        self._check_serialize(message)

        exchange = self._get_exchange(target.exchange or
                                      self._default_exchange)

        reply_q = None
        if wait_for_reply:
            reply_q = moves.queue.Queue()

        exchange.deliver_message(target.topic, ctxt, message,
                                 server=target.server,
                                 fanout=target.fanout,
                                 reply_q=reply_q)

        if wait_for_reply:
            try:
                reply, failure = reply_q.get(timeout=timeout)
                if failure:
                    raise failure
                else:
                    return reply
            except moves.queue.Empty:
                raise messaging.MessagingTimeout(
                    'No reply on topic %s' % target.topic)

        return None

    def send(self, target, ctxt, message, wait_for_reply=None, timeout=None):
        return self._send(target, ctxt, message, wait_for_reply, timeout)

    def send_notification(self, target, ctxt, message, version):
        self._send(target, ctxt, message)

    def listen(self, target):
        exchange = self._get_exchange(target.exchange or
                                      self._default_exchange)

        listener = FakeListener(self, exchange,
                                [messaging.Target(topic=target.topic,
                                                  server=target.server),
                                 messaging.Target(topic=target.topic)])
        return listener

    def listen_for_notifications(self, targets_and_priorities):
        # TODO(sileht): Handle the target.exchange
        exchange = self._get_exchange(self._default_exchange)

        targets = [messaging.Target(topic='%s.%s' % (target.topic, priority))
                   for target, priority in targets_and_priorities]
        listener = FakeListener(self, exchange, targets)

        return listener

    def cleanup(self):
        pass
