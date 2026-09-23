"""Incremental reading of a trace that is still being recorded.

The live marker view used to copy the whole on-device trace over adb and parse
all of it on every poll. Both costs grow with the session: at the original
capture config a poll took ~30s four minutes in, and it only gets worse. This
keeps a running position instead, and each poll reads and parses only what was
written since the last one, so a poll costs the same at minute one and minute
forty.

Two details make a standalone chunk parse correctly, and both were measured on
real 81MB and 273MB manual traces replayed in 8MB polls:

* **Cut on packet boundaries.** A trace file is a sequence of length-prefixed
  `TracePacket`s, and the recorder may be mid-write when we read. Only whole
  packets are parsed; the partial tail is held for the next poll.
* **Overlap the windows.** Parsed standalone, a chunk loses ftrace events near
  its own start (5 of 84 markers were dropped, all at chunk starts), because
  the parser discards early events until it has seen data from every CPU. Each
  chunk is parsed with the last LEAD_BYTES of the previous one in front of it,
  and markers are de-duplicated by (name, timestamp): 84 of 84 recovered.
"""
import os
import tempfile

LEAD_BYTES = 4 * 1024 * 1024


def _varint(buf, i):
    r = s = 0
    while i < len(buf):
        b = buf[i]
        i += 1
        r |= (b & 0x7F) << s
        s += 7
        if not b & 0x80:
            return r, i
    return None, i


def packet_starts(buf):
    """Offsets where each whole `Trace.packet` (field 1, length-delimited) begins,
    and the length of the prefix those whole packets cover."""
    starts, i = [], 0
    while i < len(buf):
        if buf[i] != 0x0A:
            raise ValueError(f"trace is not packet-aligned at byte {i}")
        n, j = _varint(buf, i + 1)
        if n is None or j + n > len(buf):
            break  # the recorder is mid-write; this packet arrives next poll
        starts.append(i)
        i = j + n
    return starts, i


class LiveTrace:
    """Accumulates marker rows from a growing trace, one new chunk at a time.

    `read_from(offset)` returns the bytes appended at or after `offset`, and
    `parse(path)` returns marker rows `(name, ts, dur)` for a trace file. Both
    are injected so the logic can be tested against a real trace replayed as if
    it were still being written.
    """

    def __init__(self, read_from, parse, lead_bytes=LEAD_BYTES):
        self._read_from = read_from
        self._parse = parse
        self._lead = lead_bytes
        self.reset()

    def reset(self):
        self.offset = 0          # bytes of the remote file consumed so far
        self._pending = b""      # a partial packet awaiting its remainder
        self._tail = b""         # packet-aligned lead-in for the next parse
        self.rows = {}           # (name, ts) -> dur

    def poll(self):
        """Read and parse whatever was appended; return all rows seen so far."""
        new = self._read_from(self.offset)
        if new:
            self.offset += len(new)
            buf = self._pending + new
            starts, cut = packet_starts(buf)
            chunk, self._pending = buf[:cut], buf[cut:]
            if chunk:
                self._ingest(self._tail + chunk)
                self._tail = self._lead_in(chunk, starts)
        return sorted(((n, ts, d) for (n, ts), d in self.rows.items()), key=lambda r: r[1])

    def _lead_in(self, chunk, starts):
        want = len(chunk) - self._lead
        s0 = next((s for s in starts if s >= want), len(chunk))
        return chunk[s0:]

    def _ingest(self, data):
        fd, path = tempfile.mkstemp(suffix=".pftrace")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            for name, ts, dur in self._parse(path):
                key = (name, ts)
                prev = self.rows.get(key)
                # A slice cut by a chunk edge reads as open (dur < 0) in one
                # window and closed in the next; keep the closed reading.
                if prev is None or (prev < 0 <= (dur or 0)):
                    self.rows[key] = dur or 0
        finally:
            os.unlink(path)
