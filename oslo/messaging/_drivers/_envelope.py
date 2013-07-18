# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from oslo.messaging.openstack.common import jsonutils

'''RPC Envelope Version.

This version number applies to the top level structure of messages sent out.
It does *not* apply to the message payload, which must be versioned
independently.  For example, when using rpc APIs, a version number is applied
for changes to the API being exposed over rpc.  This version number is handled
in the rpc proxy and dispatcher modules.

This version number applies to the message envelope that is used in the
serialization done inside the rpc layer.  See serialize_msg() and
deserialize_msg().

The current message format (version 2.0) is very simple.  It is:

    {
        'oslo.version': <RPC Envelope Version as a String>,
        'oslo.message': <Application Message Payload, JSON encoded>
    }

Message format version '1.0' is just considered to be the messages we sent
without a message envelope.

So, the current message envelope just includes the envelope version.  It may
eventually contain additional information, such as a signature for the message
payload.

We will JSON encode the application message payload.  The message envelope,
which includes the JSON encoded application message body, will be passed down
to the messaging libraries as a dict.
'''
_RPC_ENVELOPE_VERSION = '2.0'

_VERSION_KEY = 'oslo.version'
_MESSAGE_KEY = 'oslo.message'

def serialize_msg(raw_msg):
    # NOTE(russellb) See the docstring for _RPC_ENVELOPE_VERSION for more
    # information about this format.
    msg = {_VERSION_KEY: _RPC_ENVELOPE_VERSION,
           _MESSAGE_KEY: jsonutils.dumps(raw_msg)}

    return msg
