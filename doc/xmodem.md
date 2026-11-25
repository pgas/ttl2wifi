# XMODEM File Transfer (`AT+XMODEM`)

Bootstraps CP/M `.COM` binaries and files onto a system that only has a basic serial terminal (`ZTALK` / `HTALK`) and `XM.COM`.

## 1. Host PC (Local Files)

To serve a local file over HTTP on your LAN:

```sh
./scripts/serve_file.py path/to/MYFILE.COM
```

*(Any remote `http://` or `https://` URL also works directly.)*

## 2. Queue Download in Terminal

Open your CP/M serial terminal on the bridge port (e.g. unit 1) and request the file:

```text
A> ZTALK 01
AT+XMODEM="http://<IP>:8000/MYFILE.COM"
```

*(Optional: pass a second argument `AT+XMODEM="url",500` to set the inter-byte delay in microseconds for slower UARTs.)*

Wait for the prompt:

```text
+XMODEM: Downloaded <N> bytes. Start receiver now (waiting up to 60s for NAK/'C')...
```

Exit the terminal back to CP/M (`Ctrl+[` in `ZTALK` or `Ctrl+C` in `HTALK`).

## 3. Receive in CP/M

Run `XM` on the bridge port within 60 seconds:

```text
A> XM R1 MYFILE.COM
```
