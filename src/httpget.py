# httpget.py - Minimal HTTP/1.0 and HTTPS client
import net

HTTP_SCHEMES = (("http", 80), ("https", 443))


def fetch(url, flow_uart):
    """Fetch an HTTP or HTTPS URL and stream response headers + body."""
    scheme, host, port, path = net.split_url(url, HTTP_SCHEMES)
    flow_uart.reset_pager()
    raw_sock = net.connect_tcp(host, port, timeout=12.0)
    sock = raw_sock
    try:
        if scheme == "https":
            sock = net.wrap_tls(raw_sock, server_hostname=host)
        net.sock_send(sock, net.http_request(host, path))

        for raw_line in net.stream_socket_lines(sock, flow_uart):
            if flow_uart.check_abort():
                flow_uart.write(b"\r\n^C Aborted\r\n")
                break
            if not flow_uart.write_line_paged(raw_line.decode("utf-8", "replace")):
                break
    finally:
        net.close_quiet(sock, raw_sock)
