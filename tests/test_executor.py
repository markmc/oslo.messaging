# Copyright 2011 OpenStack Foundation.
# All Rights Reserved.
# Copyright 2013 eNovance
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

import threading

import mock
import testscenarios

from oslo.messaging._executors import impl_blocking
from oslo.messaging._executors import impl_eventlet
from tests import utils as test_utils

load_tests = testscenarios.load_tests_apply_scenarios


class TestExecutor(test_utils.BaseTestCase):

    _scenarios = [
        ('rpc', dict(sender_expects_reply=True)),
        ('notify', dict(sender_expects_reply=False))
    ]

    _impl = [('blocking', dict(executor=impl_blocking.BlockingExecutor,
                               stop_before_return=True)),
             ('eventlet', dict(executor=impl_eventlet.EventletExecutor,
                               stop_before_return=False))]

    @classmethod
    def generate_scenarios(cls):
        cls.scenarios = testscenarios.multiply_scenarios(cls._impl,
                                                         cls._scenarios)

    @staticmethod
    def _run_in_thread(executor):
        def thread():
            executor.start()
            executor.wait()
        thread = threading.Thread(target=thread)
        thread.daemon = True
        thread.start()
        thread.join(timeout=30)

    def test_executor_dispatch(self):
        callback = mock.MagicMock(sender_expects_reply=
                                  self.sender_expects_reply,
                                  return_value='result')
        listener = mock.Mock(spec=['poll'])
        executor = self.executor(self.conf, listener, callback)

        incoming_message = mock.MagicMock(ctxt={},
                                          message={'payload': 'data'})

        def fake_poll():
            if self.stop_before_return:
                executor.stop()
                return incoming_message
            else:
                if listener.poll.call_count == 1:
                    return incoming_message
                executor.stop()

        listener.poll.side_effect = fake_poll

        self._run_in_thread(executor)

        incoming_message.acknowledge.assert_called_once_with()
        callback.assert_called_once_with({}, {'payload': 'data'})
        if self.sender_expects_reply:
            incoming_message.reply.assert_called_once_with('result')
        else:
            self.assertEqual(incoming_message.reply.call_count, 0)

TestExecutor.generate_scenarios()
