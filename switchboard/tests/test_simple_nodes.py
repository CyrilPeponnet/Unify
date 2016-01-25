# -*- coding: utf-8 -*-

from unittest import TestCase
import difflib
from switchboard import _generate_conf

class TestSimpleService(TestCase):

    def _assertEquals(self, name, _services, output, expected):
        diff = '\n'.join(difflib.unified_diff(output.strip().splitlines(), expected.strip().splitlines(), fromfile='out', tofile='expected', lineterm=''))
        self.assertEquals(output, expected, msg="TEST NAME: %s\
                                                     \n-------SERVICE------\n%s \
                                                     \n-----------------------\n \
                                                     \n--------OUTPUT--------\n%s \
                                                     \n-------EXPECTED-------\n%s \
                                                     \n-----------------------\n%s" \
                                                    % (name, _services, output, expected, diff))

    def test_one_node_bk_443_ft_80_http(self):
        name = "One node ssl backend 443 and ssl port 80 frontend"
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

    def test_one_node_bk_443_ft_80_http_multiple_domains(self):
        name = "One node ssl backend 443 and ssl port 80 frontend"
        _services = [
            {
                "name": "service-1",
                "ip": "10.0.0.1",
                "port": "1200",
                "id": "node1:443",
                "tags": [
                        "dns=bla.tld",
                        "dns=coin.tld",
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
    use_backend bk_service-1 if { hdr(host) -i test.bla.tld }
    use_backend bk_service-1 if { hdr(host) -i test.coin.tld }
"""

        self._assertEquals(name, _services, _generate_conf(_services, "tests/test.jinja2"), _expected)

    def test_one_node_bk_443_ft_detect(self):
        name = "One node ssl backend 443, autodiscover for frontend"
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
        }
        ]
        _expected =r"""
frontend http-in
    bind :80
    mode http
    redirect scheme https code 301 if !{ ssl_fc }

backend bk_service-1
    mode http
    balance roundrobin
    option httpchk HEAD / HTTP/1.1\r\nHost:localhost
    server "node1:443" 10.0.0.1:1200 check ssl verify none

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
    use_backend bk_service-1 if { hdr(host) -i test.domain.tld }
"""
        self._assertEquals(name, _services, _generate_conf(_services, "tests/test.jinja2"), _expected)

    def test_one_node_bk_80_ft_detect(self):
        name = "One node backend 80, autodiscover for frontend"
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
        }
        ]
        _expected =r"""
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
"""
        self._assertEquals(name, _services, _generate_conf(_services, "tests/test.jinja2"), _expected)

    def test_one_node_bk_80_ft_offloading(self):
        name = "One node backend 80, offloading frontend to 443"
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
        }
        ]
        _expected =r"""
frontend http-in
    bind :80
    mode http
    redirect scheme https code 301 if !{ ssl_fc }

backend bk_service-1
    mode http
    balance roundrobin
    option httpchk HEAD / HTTP/1.1\r\nHost:localhost
    server "node1:80" 10.0.0.1:1200 check

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
    use_backend bk_service-1 if { hdr(host) -i test.domain.tld }
"""
        self._assertEquals(name, _services, _generate_conf(_services, "tests/test.jinja2"), _expected)

    def test_one_node_bk_80_ft_80_with_api_and_check(self):
        name = "One node backend 80, frontend 80 with options"
        _services = [
        {
            "name": "service-1",
            "ip": "10.0.0.1",
            "port": "1200",
            "id": "node1:80",
            "tags": [
                    "dns=domain.tld",
                    "vhost=test",
                    "http=80",
                    "url=/api",
                    r"check=OPTIONS \r\n/api/events"
                    ]
        }
        ]
        _expected =r"""
frontend http-in
    bind :80 name http
    mode http
    reqadd X-Forwarded-Proto:\ http
    use_backend bk_service-1 if { hdr(host) -i test.domain.tld } { path_beg -i /api }
    redirect scheme https code 301 if !{ ssl_fc }

backend bk_service-1
    mode http
    balance roundrobin
    option httpchk OPTIONS \r\n/api/events
    server "node1:80" 10.0.0.1:1200 check
"""
        self._assertEquals(name, _services, _generate_conf(_services, "tests/test.jinja2"), _expected)

    def test_one_node_bk_443_ft_443_ssl_pass_through(self):
        name = "One node backend 443, frontend 443 ssl-passthrough"
        _services = [
        {
            "name": "service-1",
            "ip": "10.0.0.1",
            "port": "1200",
            "id": "node1:443",
            "tags": [
                    "dns=domain.tld",
                    "vhost=test",
                    "https=443",
                    "ssl=pass-through"
                    ]
        }
        ]
        _expected =r"""
frontend http-in
    bind :80
    mode http
    redirect scheme https code 301 if !{ ssl_fc }

backend bk_service-1
    mode tcp
    server "node1:443" 10.0.0.1:1200 check

frontend https-in
    bind :443
    mode tcp
    tcp-request content accept if { req_ssl_hello_type 1 }
    use_backend bk_service-1 if { req.ssl_sni -i test.domain.tld }
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


    def test_one_node_tcp(self):
        name = "One node tcp port 5222"
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
"""
        self._assertEquals(name, _services, _generate_conf(_services, "tests/test.jinja2"), _expected)

