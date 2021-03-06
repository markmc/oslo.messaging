
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

import urlparse


def parse_url(url, default_exchange=None):
    """Parse an url.

    Assuming a URL takes the form of:

        transport://user:pass@host1:port[,hostN:portN]/exchange[?opt=val]

    then parse the URL and return a dictionary with the following structure:

        {
            'exchange': 'exchange'
            'transport': 'transport',
            'hosts': [{'username': 'username',
                       'password': 'password'
                       'host': 'host1:port1'},
                       ...],
            'parameters': {'option': 'value'}
        }

    Netloc is parsed following the sequence bellow:

    * It is first splitted by ',' in order to support multiple hosts
    * The last parsed username and password will be propagated to the rest
    of hotsts specified:

      user:passwd@host1:port1,host2:port2

      [
       {"username": "user", "password": "passwd", "host": "host1:port1"},
       {"username": "user", "password": "passwd", "host": "host2:port2"}
      ]

    * In order to avoid the above propagation, it is possible to alter the
    order in which the hosts are specified or specify a set of fake credentials
    using ",:@host2:port2"


      user:passwd@host1:port1,:@host2:port2

      [
       {"username": "user", "password": "passwd", "host": "host1:port1"},
       {"username": "", "password": "", "host": "host2:port2"}
      ]

    :param url: The URL to parse
    :type url: str
    :param default_exchange: what to return if no exchange found in URL
    :type default_exchange: str
    :returns: A dictionary with the parsed data
    """
    if not url:
        return dict(exchange=default_exchange)

    # NOTE(flaper87): Not PY3K compliant
    if not isinstance(url, basestring):
        raise TypeError("Wrong URL type")

    url = urlparse.urlparse(url)

    parsed = dict(transport=url.scheme)

    exchange = None
    if url.path.startswith('/'):
        exchange = url.path[1:].split('/')[0]
    if not exchange:
        exchange = default_exchange
    parsed["exchange"] = exchange

    # NOTE(flaper87): Parse netloc.
    hosts = []
    username = password = ''
    for host in url.netloc.split(","):
        if not host:
            continue

        if "@" in host:
            username, host = host.split("@", 1)
            if ":" in username:
                username, password = username.split(":", 1)

        hosts.append({
            "host": host,
            "username": username,
            "password": password,
        })

    parsed["hosts"] = hosts

    parameters = {}
    if url.query:
        # NOTE(flaper87): This returns a dict with
        # key -> [value], those values need to be
        # normalized
        parameters = urlparse.parse_qs(url.query)
    parsed['parameters'] = parameters

    return parsed


def exchange_from_url(url, default_exchange=None):
    """Parse an exchange name from a URL.

    Assuming a URL takes the form of:

      transport:///myexchange

    then parse the URL and return the exchange name.

    :param url: the URL to parse
    :type url: str
    :param default_exchange: what to return if no exchange found in URL
    :type default_exchange: str
    """
    return parse_url(url, default_exchange)['exchange']
