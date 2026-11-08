# gopher.py - RFC 1436 Gopher client with numbered link navigation
import net

GOPHER_TYPES = {
    "0": "TXT",
    "1": "DIR",
    "2": "CSO",
    "3": "ERR",
    "4": "HEX",
    "5": "DOS",
    "6": "UUE",
    "7": "QRY",
    "8": "TEL",
    "9": "BIN",
    "g": "GIF",
    "I": "IMG",
    "h": "HTM",
    "i": "   ",
    "s": "SND",
}


def fetch(target, flow_uart, nav=None, query=None, push_history=True):
    """
    Fetch a Gopher menu or document and number selectable links [1], [2], ...
    """
    url = target.strip()
    if url.startswith("gopher://"):
        url = url[9:]

    item_type = "1"
    if "/" in url:
        hostport, selector = url.split("/", 1)
        if len(selector) >= 1 and selector[0] in GOPHER_TYPES and (len(selector) == 1 or selector[1] == "/"):
            item_type = selector[0]
            selector = selector[1:]
        elif not selector.startswith("/"):
            selector = "/" + selector
    else:
        hostport = url
        selector = ""

    canon_url = f"gopher://{hostport}/{item_type}{selector}"
    if nav is not None:
        nav.set_page(canon_url, push_history=push_history)

    host, port = net.parse_host_port(hostport, 70)
    flow_uart.reset_pager()
    sock = net.connect_tcp(host, port, timeout=10.0)
    try:
        req_sel = f"{selector}\t{query}" if query else selector
        sock.sendall((req_sel + "\r\n").encode("utf-8"))

        for raw_line in net.stream_socket_lines(sock, flow_uart):
            if flow_uart.check_abort():
                flow_uart.write(b"\r\n^C Aborted\r\n")
                break
            if raw_line == b".":
                break
            if b"\t" in raw_line and item_type in ("1", "7"):
                parts = raw_line.decode("utf-8", "replace").split("\t")
                if parts and len(parts[0]) >= 1:
                    t_ch = parts[0][0]
                    display = parts[0][1:]
                    sel = parts[1] if len(parts) > 1 else ""
                    h = parts[2] if len(parts) > 2 else host
                    p = parts[3] if len(parts) > 3 else "70"
                    if t_ch == "i":
                        if not flow_uart.write_line_paged("       " + display):
                            break
                    else:
                        tag = GOPHER_TYPES.get(t_ch, t_ch)
                        hp = f"{h}:{p}" if p != "70" else h
                        if sel.startswith("URL:"):
                            link_url = sel[4:]
                        elif t_ch == "8":
                            link_url = f"telnet://{hp}"
                        else:
                            if not sel.startswith("/"):
                                sel = "/" + sel
                            link_url = f"gopher://{hp}/{t_ch}{sel}"
                        idx = nav.add_link(link_url, display, t_ch) if nav is not None else 0
                        prefix = f"[{idx:>2d}:{tag}] " if idx else f"[{tag}] "
                        if not flow_uart.write_line_paged(f"{prefix}{display}"):
                            break
                    continue
            if not flow_uart.write_line_paged(raw_line.decode("utf-8", "replace")):
                break
    finally:
        sock.close()

