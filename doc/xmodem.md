# XMODEM File Transfer

Allows transfering files using only the "standard" HTALK an XM commands

## 1. On Host PC: Serve File

Run `serve_file.py` pointing to the file to transfer:

```sh
./scripts/serve_file.py path/to/MYFILE.COM
```

The script starts an HTTP server and prints the exact commands to run.

---

## 2. In CP/M: Queue Download

Assuming, the bridge is connected on Port 1 (port B), initiate the transfer, and return to CP/M:

```text
B> HTALK 1
AT+XMODEM="http://<IP>:8000/MYFILE.COM"
```

Optional: `AT+XMODEM` supports an optional microsecond inter-byte delay (e.g. `AT+XMODEM="url",250`, default: `250` µs) to prevent UART buffer overruns on serial systems without hardware flow control. 

Slower 4 MHz Z80 systems can specify a higher delay (e.g. `500` or `800`).

When you see:
```text
+XMODEM: Start receiver now (waiting up to 60s for NAK/'C')...
```

Press **`Ctrl+C`** to exit `HTALK`.

---

## 3. In CP/M: Receive File

Immediately start RomWBW's receiver on Port 1 (`R1`):

```text
B> XM R1 MYFILE.COM
```

> **Note:** RomWBW's `XM` remains silent during download and prints `Thanks for the upload` upon completion.
