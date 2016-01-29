# -*- coding: utf-8 -*-

from unittest import TestCase
import difflib
from switchboard import _generate_conf

class TestComplexService(TestCase):

    def _assertEquals(self, name, _services, output, expected):
        diff = '\n'.join(difflib.unified_diff(output.strip().splitlines(), expected.strip().splitlines(), fromfile='out', tofile='expected', lineterm=''))
        self.assertEquals(output, expected, msg="TEST NAME: %s\
                                                     \n-------SERVICE------\n%s \
                                                     \n-----------------------\n \
                                                     \n--------OUTPUT--------\n%s \
                                                     \n-------EXPECTED-------\n%s \
                                                     \n-----------------------\n%s" \
                                                    % (name, _services, output, expected, diff))

    def test_application_1(self):
        name = "Application with two backend tcp, one frontend ssl with 2 servers for 2 services"
        _services = [
            {
                "name": "myapplication-frontend",
                "ip": "10.0.0.1",
                "port": "1200",
                "id": "node1:443",
                "tags": [
                        "dns=domain.tld",
                        "https=443",
                        "vhost=myapp",
                        ]
            },
            {
                "name": "myapplication-frontend",
                "ip": "10.0.0.2",
                "port": "1200",
                "id": "node2:443",
                "tags": [
                        "dns=domain.tld",
                        "https=443",
                        "vhost=myapp",
                        ]
            },
            {
                "name": "myapplication-api",
                "ip": "10.0.0.3",
                "port": "1200",
                "id": "node3:443",
                "tags": [
                        "dns=domain.tld",
                        "https=443",
                        "vhost=myapp",
                        "url_prefix=/api"
                        ]
            },
            {
                "name": "myapplication-xmpp",
                "ip": "10.0.0.4",
                "port": "1200",
                "id": "node4:5222",
                "tags": [
                        "dns=domain.tld",
                        "tcp=5222",
                        "vhost=myapp",
                        ]
            },
            {
                "name": "myapplication-xmpp",
                "ip": "10.0.0.5",
                "port": "1200",
                "id": "node5:5222",
                "tags": [
                        "dns=domain.tld",
                        "tcp=5222",
                        "vhost=myapp",
                        ]
            }

        ]
        _expected = r"""
frontend tcp-5222-in:
    mode tcp
    bind :5222
    default_backend bk_tcp_myapplication-xmpp

backend bk_tcp-myapplication-xmpp
    mode tcp
    balance roundrobin
    server "node4:5222" 10.0.0.4:1200
    server "node5:5222" 10.0.0.5:1200

frontend http-in
    bind :80
    mode http
    default_backend https-redirect

backend bk_myapplication-api
    mode http
    balance roundrobin
    option httpchk HEAD / HTTP/1.1\r\nHost:localhost
    server "node3:443" 10.0.0.3:1200 check ssl verify none

backend bk_myapplication-frontend
    mode http
    balance roundrobin
    option httpchk HEAD / HTTP/1.1\r\nHost:localhost
    server "node1:443" 10.0.0.1:1200 check ssl verify none
    server "node2:443" 10.0.0.2:1200 check ssl verify none

backend https-redirect
    mode http
    redirect scheme https code 301 if !{ ssl_fc }

frontend https-in
    bind :443
    mode tcp
    tcp-request content accept if { req_ssl_hello_type 1 }
    default_backend https-no-sni

backend https-no-sni
    mode tcp
    server "https-no-sni-loop" localhost:10443

frontend https-in-no-sni
    mode http
    bind localhost:10443 ssl crt /etc/haproxy/certs/
    reqadd X-Forwarded-Proto:\ https
    use_backend bk_myapplication-api if { hdr(host) -i myapp.domain.tld } { path_beg -i /api }
    use_backend bk_myapplication-frontend if { hdr(host) -i myapp.domain.tld }
"""

        self._assertEquals(name, _services, _generate_conf(_services, "tests/test.jinja2"), _expected)

    def test_application_2(self):
        name = "Application with a SQL cluster database, specific balancing and one service ssl-passthrough"
        _services = [
            {
                "name": "myapplication-db",
                "ip": "10.0.0.1",
                "port": "1200",
                "id": "node1:3306",
                "tags": [
                        "dns=domain.tld",
                        "tcp=3306",
                        "vhost=myapp",
                        "check=mysql-check user root",
                        "balance=source"
                        ]
            },
            {
                "name": "myapplication-db",
                "ip": "10.0.0.2",
                "port": "1200",
                "id": "node2:3306",
                "tags": [
                        "dns=domain.tld",
                        "tcp=3306",
                        "vhost=myapp",
                        "check=mysql-check user root",
                        "balance=source"
                        ]
            },
            {
                "name": "myapplication-service",
                "ip": "10.0.0.3",
                "port": "1200",
                "id": "node3:443",
                "tags": [
                        "dns=domain.tld",
                        "https=443",
                        "vhost=myapp",
                        "ssl=pass-through"
                        ]
            }
        ]
        _expected = r"""
frontend tcp-3306-in:
    mode tcp
    bind :3306
    default_backend bk_tcp_myapplication-db

backend bk_tcp-myapplication-db
    mode tcp
    option mysql-check user root
    balance source
    server "node1:3306" 10.0.0.1:1200 check
    server "node2:3306" 10.0.0.2:1200 check

frontend http-in
    bind :80
    mode http
    default_backend https-redirect

backend bk_myapplication-service
    mode tcp
    server "node3:443" 10.0.0.3:1200 check

backend https-redirect
    mode http
    redirect scheme https code 301 if !{ ssl_fc }

frontend https-in
    bind :443
    mode tcp
    tcp-request content accept if { req_ssl_hello_type 1 }
    use_backend bk_myapplication-service if { req.ssl_sni -i myapp.domain.tld }
    default_backend https-no-sni

backend https-no-sni
    mode tcp
    server "https-no-sni-loop" localhost:10443

frontend https-in-no-sni
    mode http
    bind localhost:10443 ssl crt /etc/haproxy/certs/
    reqadd X-Forwarded-Proto:\ https
"""

        self._assertEquals(name, _services, _generate_conf(_services, "tests/test.jinja2"), _expected)

    def test_application_3(self):
        name = "Application with http frontend and http frontend as well"
        _services = [
            {
                "name": "myapplication-http",
                "ip": "10.0.0.1",
                "port": "80",
                "id": "node1:80",
                "tags": [
                        "dns=domain.tld",
                        "vhost=myapp",
                        "check=disabled",
                        "http=80"
                        ]
            },
            {
                "name": "myapplication-https",
                "ip": "10.0.0.3",
                "port": "443",
                "id": "node3:443",
                "tags": [
                        "dns=domain.tld",
                        "https=443",
                        "vhost=myapp"
                        ]
            }
        ]
        _expected = r"""
frontend http-in
    bind :80 name http
    mode http
    reqadd X-Forwarded-Proto:\ http
    use_backend bk_myapplication-http if { hdr(host) -i myapp.domain.tld }
    default_backend https-redirect

backend bk_myapplication-http
    mode http
    balance roundrobin
    server "node1:80" 10.0.0.1:80

backend bk_myapplication-https
    mode http
    balance roundrobin
    option httpchk HEAD / HTTP/1.1\r\nHost:localhost
    server "node3:443" 10.0.0.3:443 check ssl verify none

backend https-redirect
    mode http
    redirect scheme https code 301 if !{ ssl_fc }

frontend https-in
    bind :443
    mode tcp
    tcp-request content accept if { req_ssl_hello_type 1 }
    default_backend https-no-sni

backend https-no-sni
    mode tcp
    server "https-no-sni-loop" localhost:10443

frontend https-in-no-sni
    mode http
    bind localhost:10443 ssl crt /etc/haproxy/certs/
    reqadd X-Forwarded-Proto:\ https
    use_backend bk_myapplication-https if { hdr(host) -i myapp.domain.tld }
"""

        self._assertEquals(name, _services, _generate_conf(_services, "tests/test.jinja2"), _expected)
