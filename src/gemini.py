# gemini.py - Gemini protocol client over TLS with numbered link navigation
import net


def fetch(url, flow_uart, nav=None, max_redirects=5, push_history=True):
    """
    Fetch a Gemini (gemini://) document over TLS 1.2+ and number '=>' links [1], [2], ...
    """
    cur_url = url.strip()
    if not cur_url.startswith("gemini://"):
        cur_url = "gemini://" + cur_url

    flow_uart.reset_pager()
    for _ in range(max_redirects + 1):
        if "/" not in cur_url[9:]:
            cur_url = cur_url + "/"
        _scheme, host, port, _path = net.split_url(cur_url, (("gemini", 1965),))

        raw_sock = net.connect_tcp(host, port, timeout=12.0)
        tls_sock = None
        try:
            tls_sock = net.wrap_tls(raw_sock, server_hostname=host)
            net.sock_send(tls_sock, (cur_url + "\r\n").encode("utf-8"))

            hdr = b""
            while b"\n" not in hdr and len(hdr) < 1024:
                c = net.sock_recv(tls_sock, 1)
                if not c:
                    break
                hdr += c
            hdr_str = hdr.decode("utf-8", "replace").strip()
            flow_uart.write_paced(f"+GEMINI: {hdr_str}\r\n".encode("utf-8"))

            status = hdr_str[:2]
            meta = hdr_str[3:].strip() if len(hdr_str) > 3 else ""

            if status.startswith("3") and meta:
                cur_url = net.resolve_url(cur_url, meta)
                flow_uart.write_paced(f"+REDIRECT: {cur_url}\r\n".encode("utf-8"))
                continue

            if status.startswith("2"):
                if nav is not None:
                    nav.set_page(cur_url, push_history=push_history)
                is_gemtext = meta == "" or "text/gemini" in meta
                for raw_line in net.stream_socket_lines(tls_sock, flow_uart):
                    if flow_uart.check_abort():
                        flow_uart.write(b"\r\n^C Aborted\r\n")
                        break
                    line_s = raw_line.decode("utf-8", "replace")
                    if is_gemtext and line_s.startswith("=>"):
                        rem = line_s[2:].strip()
                        if rem:
                            parts = rem.split(None, 1)
                            ref = parts[0]
                            label = parts[1] if len(parts) > 1 else ref
                            full_link = net.resolve_url(cur_url, ref)
                            idx = nav.add_link(full_link, label, "GMI") if nav is not None else 0
                            line_s = f"[{idx:>2d}] {label} ({ref})" if idx else f"=> {label}"
                    if not flow_uart.write_line_paged(line_s):
                        break
            return
        finally:
            net.close_quiet(tls_sock, raw_sock)

    flow_uart.write_paced(b"ERROR: Too many redirects\r\n")
