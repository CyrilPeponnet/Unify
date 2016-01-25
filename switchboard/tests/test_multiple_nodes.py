# -*- coding: utf-8 -*-

from unittest import TestCase
import difflib
from switchboard import _generate_conf

class TestMultipleService(TestCase):

    def _assertEquals(self, name, _services, output, expected):
        diff = '\n'.join(difflib.unified_diff(output.strip().splitlines(), expected.strip().splitlines(), fromfile='out', tofile='expected', lineterm=''))
        self.assertEquals(output, expected, msg="TEST NAME: %s\
                                                     \n-------SERVICE------\n%s \
                                                     \n-----------------------\n \
                                                     \n--------OUTPUT--------\n%s \
                                                     \n-------EXPECTED-------\n%s \
                                                     \n-----------------------\n%s" \
                                                    % (name, _services, output, expected, diff))

    def test_two_nodes_bk_443_ft_80_http(self):
        name = "Two nodes ssl backend 443 and ssl port 80 frontend"
        _services = [
            {
                "name": "service-1",
                "ip": "10.0.0.1",
                "port": "1200",
                "id": "node1:443",
                "tags": [
                        "dns=domain.tld",
                        "https=80",
                        "vhost=test",
                        ]
            },
            {
                "name": "service-1",
                "ip": "10.0.0.2",
                "port": "1202",
                "id": "node2:443",
                "tags": [
                        "dns=domain.tld",
                        "https=80",
                        "vhost=test",
                        ]
            }
        ]
        _expected = r"""
frontend http-in
    bind :80
    mode http
    redirect scheme https code 301 if !{ ssl_fc }

backend bk_service-1
    mode http
    balance roundrobin
    option httpchk HEAD / HTTP/1.1\r\nHost:localhost
    server "node1:443" 10.0.0.1:1200 check ssl verify none
    server "node2:443" 10.0.0.2:1202 check ssl verify none

frontend https-in
    bind :80
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
    use_backend bk_service-1 if { hdr(host) -i test.domain.tld }
"""

        self._assertEquals(name, _services, _generate_conf(_services, "tests/test.jinja2"), _expected)

    def test_two_nodes_bk_80_ft_80_detect(self):
        name = "Two nodes http backend port 80 frontend"
        _services = [
            {
                "name": "service-1",
                "ip": "10.0.0.1",
                "port": "1200",
                "id": "node1:80",
                "tags": [
                        "dns=domain.tld",
                        "vhost=test",
                        ]
            },
            {
                "name": "service-1",
                "ip": "10.0.0.2",
                "port": "1202",
                "id": "node2:80",
                "tags": [
                        "dns=domain.tld",
                        "vhost=test",
                        ]
            }
        ]
        _expected = r"""
frontend http-in
    bind :80 name http
    mode http
    reqadd X-Forwarded-Proto:\ http
    use_backend bk_service-1 if { hdr(host) -i test.domain.tld }
    redirect scheme https code 301 if !{ ssl_fc }

backend bk_service-1
    mode http
    balance roundrobin
    option httpchk HEAD / HTTP/1.1\r\nHost:localhost
    server "node1:80" 10.0.0.1:1200 check
    server "node2:80" 10.0.0.2:1202 check
"""

        self._assertEquals(name, _services, _generate_conf(_services, "tests/test.jinja2"), _expected)


    def test_two_nodes_one_80_other_80_ft_80_with_options(self):
        name = "Two nodes 80 frontend port 80 frontend"
        _services = [
            {
                "name": "service-1",
                "ip": "10.0.0.1",
                "port": "1200",
                "id": "node1:80",
                "tags": [
                        "dns=domain.tld",
                        "vhost=test",
                        "http=80"
                        ]
            },
            {
                "name": "service-2",
                "ip": "10.0.0.2",
                "port": "1202",
                "id": "node2:80",
                "tags": [
                        "dns=domain.tld",
                        "vhost=test",
                        "http=80",
                        "url=/api"
                        ]
            }
        ]
        _expected = r"""
frontend http-in
    bind :80 name http
    mode http
    reqadd X-Forwarded-Proto:\ http
    use_backend bk_service-2 if { hdr(host) -i test.domain.tld } { path_beg -i /api }
    use_backend bk_service-1 if { hdr(host) -i test.domain.tld }
    redirect scheme https code 301 if !{ ssl_fc }

backend bk_service-1
    mode http
    balance roundrobin
    option httpchk HEAD / HTTP/1.1\r\nHost:localhost
    server "node1:80" 10.0.0.1:1200 check

backend bk_service-2
    mode http
    balance roundrobin
    option httpchk HEAD / HTTP/1.1\r\nHost:localhost
    server "node2:80" 10.0.0.2:1202 check
"""

        self._assertEquals(name, _services, _generate_conf(_services, "tests/test.jinja2"), _expected)

    def test_two_nodes_one_80_other_80_ft_443_with_options(self):
        name = "Two nodes 80 backend ssl port 443 frontend"
        _services = [
            {
                "name": "service-1",
                "ip": "10.0.0.1",
                "port": "1200",
                "id": "node1:80",
                "tags": [
                        "dns=domain.tld",
                        "vhost=test",
                        "https=443"
                        ]
            },
            {
                "name": "service-2",
                "ip": "10.0.0.2",
                "port": "1202",
                "id": "node2:80",
                "tags": [
                        "dns=domain.tld",
                        "vhost=test",
                        "https=443",
                        "url=/api"
                        ]
            }
        ]
        _expected = r"""
frontend http-in
    bind :80
    mode http
    redirect scheme https code 301 if !{ ssl_fc }

backend bk_service-1
    mode http
    balance roundrobin
    option httpchk HEAD / HTTP/1.1\r\nHost:localhost
    server "node1:80" 10.0.0.1:1200 check

backend bk_service-2
    mode http
    balance roundrobin
    option httpchk HEAD / HTTP/1.1\r\nHost:localhost
    server "node2:80" 10.0.0.2:1202 check

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
    use_backend bk_service-2 if { hdr(host) -i test.domain.tld } { path_beg -i /api }
    use_backend bk_service-1 if { hdr(host) -i test.domain.tld }
"""

        self._assertEquals(name, _services, _generate_conf(_services, "tests/test.jinja2"), _expected)

    def test_two_nodes_one_443_other_443_ft_443_with_options(self):
        name = "Two nodes one 443 other 443 backend port 443 frontend"
        _services = [
            {
                "name": "service-1",
                "ip": "10.0.0.1",
                "port": "1200",
                "id": "node1:443",
                "tags": [
                        "dns=domain.tld",
                        "vhost=test",
                        "https=443"
                        ]
            },
            {
                "name": "service-2",
                "ip": "10.0.0.2",
                "port": "1202",
                "id": "node2:443",
                "tags": [
                        "dns=domain.tld",
                        "vhost=test",
                        "https=443",
                        "url=/api"
                        ]
            }
        ]
        _expected = r"""
frontend http-in
    bind :80
    mode http
    redirect scheme https code 301 if !{ ssl_fc }

backend bk_service-1
    mode http
    balance roundrobin
    option httpchk HEAD / HTTP/1.1\r\nHost:localhost
    server "node1:443" 10.0.0.1:1200 check ssl verify none

backend bk_service-2
    mode http
    balance roundrobin
    option httpchk HEAD / HTTP/1.1\r\nHost:localhost
    server "node2:443" 10.0.0.2:1202 check ssl verify none

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
    use_backend bk_service-2 if { hdr(host) -i test.domain.tld } { path_beg -i /api }
    use_backend bk_service-1 if { hdr(host) -i test.domain.tld }
"""

        self._assertEquals(name, _services, _generate_conf(_services, "tests/test.jinja2"), _expected)

    def test_two_nodes_one_443_other_443_ft_detect_with_options(self):
        name = "Two nodes 443 backend autodetect frontend"
        _services = [
            {
                "name": "service-1",
                "ip": "10.0.0.1",
                "port": "1200",
                "id": "node1:443",
                "tags": [
                        "dns=domain.tld",
                        "vhost=test",
                        ]
            },
            {
                "name": "service-2",
                "ip": "10.0.0.2",
                "port": "1202",
                "id": "node2:443",
                "tags": [
                        "dns=domain.tld",
                        "vhost=test",
                        "url=/api"
                        ]
            }
        ]
        _expected = r"""
frontend http-in
    bind :80
    mode http
    redirect scheme https code 301 if !{ ssl_fc }

backend bk_service-1
    mode http
    balance roundrobin
    option httpchk HEAD / HTTP/1.1\r\nHost:localhost
    server "node1:443" 10.0.0.1:1200 check ssl verify none

backend bk_service-2
    mode http
    balance roundrobin
    option httpchk HEAD / HTTP/1.1\r\nHost:localhost
    server "node2:443" 10.0.0.2:1202 check ssl verify none

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
    use_backend bk_service-2 if { hdr(host) -i test.domain.tld } { path_beg -i /api }
    use_backend bk_service-1 if { hdr(host) -i test.domain.tld }
"""

        self._assertEquals(name, _services, _generate_conf(_services, "tests/test.jinja2"), _expected)

    def test_two_node_tcp_same_server(self):
        name = "Two nodes tcp port 5222"
        _services = [
        {
            "name": "service-1",
            "ip": "10.0.0.1",
            "port": "1200",
            "id": "node1:5222",
            "tags": [
                    "dns=domain.tld",
                    "vhost=test",
                    "tcp=5222",
                    ]
        },
        {
            "name": "service-1",
            "ip": "10.0.0.2",
            "port": "1200",
            "id": "node2:5222",
            "tags": [
                    "dns=domain.tld",
                    "vhost=test",
                    "tcp=5222",
                    ]
        }
        ]
        _expected =r"""
frontend tcp-5222-in:
    mode tcp
    bind :5222
    default_backend bk_tcp_service-1

backend bk_tcp-service-1
    mode tcp
    balance roundrobin
    server "node1:5222" 10.0.0.1:1200
    server "node2:5222" 10.0.0.2:1200
"""
        self._assertEquals(name, _services, _generate_conf(_services, "tests/test.jinja2"), _expected)

    def test_two_node_tcp_different_server(self):
        name = "Two nodes tcp port 5222"
        _services = [
        {
            "name": "service-1",
            "ip": "10.0.0.1",
            "port": "1200",
            "id": "node1:5222",
            "tags": [
                    "dns=domain.tld",
                    "vhost=test",
                    "tcp=5222",
                    ]
        },
        {
            "name": "service-2",
            "ip": "10.0.0.2",
            "port": "1200",
            "id": "node2:5443",
            "tags": [
                    "dns=domain.tld",
                    "vhost=test",
                    "tcp=5433",
                    ]
        }
        ]
        _expected =r"""
frontend tcp-5222-in:
    mode tcp
    bind :5222
    default_backend bk_tcp_service-1

frontend tcp-5433-in:
    mode tcp
    bind :5433
    default_backend bk_tcp_service-2

backend bk_tcp-service-1
    mode tcp
    balance roundrobin
    server "node1:5222" 10.0.0.1:1200

backend bk_tcp-service-2
    mode tcp
    balance roundrobin
    server "node2:5443" 10.0.0.2:1200
"""
        self._assertEquals(name, _services, _generate_conf(_services, "tests/test.jinja2"), _expected)
