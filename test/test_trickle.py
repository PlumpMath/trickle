import re
import socket

from tornado import gen
from tornado.concurrent import Future
from tornado.netutil import Resolver
from tornado.tcpserver import TCPServer
from tornado.testing import AsyncTestCase, AsyncHTTPTestCase
from tornado.testing import gen_test, bind_unused_port
from tornado.web import RequestHandler, Application

from trickle import Trickle


class TestTCPServer(TCPServer):
    def __init__(self, *args, **kwargs):
        super(TestTCPServer, self).__init__(*args, **kwargs)
        self.test_stream = Future()

    def handle_stream(self, stream, address):
        self.test_stream.set_result(stream)


class TrickleTCPTest(AsyncTestCase):
    # Tests with a TCPServer.

    def setUp(self):
        super(TrickleTCPTest, self).setUp()
        sock, port = bind_unused_port()
        self.port = port
        self.server = TestTCPServer(self.io_loop)
        self.server.add_socket(sock)
        self.resolver = Resolver()

    @gen.coroutine
    def connect(self):
        client_trickle = Trickle(
            socket.socket(socket.AF_INET),
            io_loop=self.io_loop)

        addr_info = yield self.resolver.resolve(
            'localhost', self.port, socket.AF_INET)

        sock_addr = addr_info[0][1]
        yield client_trickle.connect(sock_addr)

        # Wait for server to handle connection.
        server_stream = yield self.server.test_stream
        server_trickle = Trickle(server_stream)

        raise gen.Return((client_trickle, server_trickle))

    @gen_test
    def test_read_bytes(self):
        client_trickle, server_trickle = yield self.connect()
        data = b'a' * 10
        yield server_trickle.write(data)
        self.assertEqual(data, (yield client_trickle.read_bytes(10)))

    @gen_test
    def test_read_timeout(self):
        client_trickle, server_trickle = yield self.connect()

        try:
            yield client_trickle.read_bytes(10, timeout=0.01)
        except socket.timeout:
            pass
        else:
            self.fail('socket.timeout not raised')


class TrickleTestHandler(RequestHandler):
    def get(self):
        self.finish('hello')


class TrickleHTTPTest(AsyncHTTPTestCase):
    # Tests with an HTTPServer.

    def setUp(self):
        super(TrickleHTTPTest, self).setUp()
        self.resolver = Resolver()

    def get_app(self):
        return Application([('/', TrickleTestHandler)])

    @gen_test
    def test_http(self):
        addr_info = yield self.resolver.resolve(
            'localhost',
            self.get_http_port(),
            socket.AF_INET)

        sock_addr = addr_info[0][1]
        trick = Trickle(
            socket.socket(socket.AF_INET),
            io_loop=self.io_loop)

        yield trick.connect(sock_addr)
        yield trick.write(b'GET / HTTP/1.1\r\n\r\n')

        headers = yield trick.read_until(b'\r\n\r\n')
        match = re.search(br'Content-Length: (\d+)\r\n', headers)
        content_length = int(match.group(1))
        body = yield trick.read_bytes(content_length)
        self.assertEqual('hello', body)
