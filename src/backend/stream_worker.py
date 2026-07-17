"""
Durable stream reconnect (v1) — decouples turn generation from the SSE consumer.

PROBLEM
-------
Historically the whole turn (context assembly -> Anthropic streaming -> command
continuation -> persistence) ran *inside* the Flask SSE response generator. When
the client disconnected mid-response (mobile tab switch, screen lock, network
blip), Werkzeug threw ``GeneratorExit`` into that generator, killing generation.
The user row was left orphaned and page-load cleanup deleted it — losing the
whole response. Phone-primary users hit this constantly.

SOLUTION
--------
Run the turn generator to completion in a background worker thread, buffering its
events into a thread-safe queue. The SSE endpoint merely *consumes* the queue and
relays events to the client. If the client disconnects, the SSE consumer stops
reading, but the worker thread keeps running to completion — persistence
(which already happens inside ``process_message_stream``) still lands normally.

DISCONNECT vs INTERRUPT
-----------------------
This module makes the distinction explicit:

* **Disconnect** (silent socket death, no abort call): the SSE consumer stops
  iterating. The worker is *unaffected* — it owns its own thread and finishes.
  Nothing touches the DB beyond the turn's own normal persistence.
* **Interrupt** (user presses stop): the frontend explicitly calls
  ``POST /api/chat/cancel`` FIRST (cooperative cancellation — the worker closes
  the turn generator, raising ``GeneratorExit`` inside it, exactly the pre-v1
  kill semantics), then aborts the fetch and calls
  ``/api/messages/save-partial`` or ``/api/messages/cleanup-orphans`` as before.

In other words: only an explicit cancel call is an interrupt. A dropped socket
is never an interrupt.

IN-FLIGHT GUARD
---------------
The registry tracks, per profile, whether a turn is currently generating. Two
consumers rely on this:

* Orphan cleanup (``/api/messages/cleanup-orphans``) protects the trailing turn
  of a profile while it is generating, so it cannot delete the in-flight user
  row (or its pre-allocated empty assistant shell).
* New-message rejection: sending while a turn is in flight for the profile is
  rejected with a clear notice (no double-generation).
"""

import queue
import threading


_SENTINEL = object()


class GenerationInProgress(Exception):
    """Raised when a new turn is started while one is already in flight."""


class TurnWorker:
    """
    Runs an event-producing generator to completion on a daemon thread,
    buffering events for an SSE consumer that may disconnect at any time.

    The worker never blocks on ``put`` (unbounded queue), so a vanished
    consumer cannot stall generation. Persistence is the generator's own
    responsibility and happens regardless of whether anyone is listening.
    """

    def __init__(self, event_source, on_finish=None):
        self._event_source = event_source
        self._on_finish = on_finish
        self._queue = queue.Queue()
        self.done = threading.Event()
        self.cancelled = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def cancel(self):
        """
        Request cooperative cancellation (user pressed stop).

        Sets a flag the worker thread checks between events. The worker then
        closes the turn generator FROM THE WORKER THREAD — raising
        ``GeneratorExit`` inside ``process_message_stream`` at its current
        yield point, restoring exactly the pre-v1 kill semantics that
        save-partial / cleanup-orphans were designed around — and finishes
        normally (done set, sentinel queued, on_finish clears the guard).
        """
        self.cancelled.set()

    def _run(self):
        try:
            while True:
                if self.cancelled.is_set():
                    # Must happen on this thread: a generator can only be
                    # closed from the thread that runs it.
                    self._event_source.close()
                    break
                try:
                    event = next(self._event_source)
                except StopIteration:
                    break
                self._queue.put(event)
        except Exception as e:  # noqa: BLE001 — surface as an SSE error event
            self._queue.put({"type": "error", "data": str(e)})
        finally:
            self.done.set()
            self._queue.put(_SENTINEL)
            if self._on_finish is not None:
                try:
                    self._on_finish()
                except Exception:
                    pass

    def events(self):
        """
        Yield buffered events for the SSE consumer.

        If the consumer stops iterating (client disconnect / GeneratorExit),
        the worker thread keeps running to completion; this generator simply
        stops being pumped. The worker's ``on_finish`` still fires from the
        worker thread, so the in-flight guard is cleared correctly.
        """
        while True:
            event = self._queue.get()
            if event is _SENTINEL:
                break
            yield event


class GenerationRegistry:
    """Tracks the in-flight turn (if any) for each profile."""

    def __init__(self):
        self._lock = threading.Lock()
        self._active = {}  # profile_name -> TurnWorker

    def is_active(self, profile_name):
        with self._lock:
            worker = self._active.get(profile_name)
            return worker is not None and not worker.done.is_set()

    def start(self, profile_name, event_source):
        """
        Start a turn for ``profile_name``. Raises ``GenerationInProgress`` if a
        turn is already running for that profile (no double-generation).
        Returns the started ``TurnWorker``.
        """
        with self._lock:
            existing = self._active.get(profile_name)
            if existing is not None and not existing.done.is_set():
                raise GenerationInProgress(profile_name)

            worker_ref = []
            worker = TurnWorker(
                event_source,
                on_finish=lambda: self._clear(profile_name, worker_ref[0]),
            )
            worker_ref.append(worker)
            self._active[profile_name] = worker

        worker.start()
        return worker

    def cancel(self, profile_name, timeout=5.0):
        """
        Cooperatively cancel the in-flight turn for ``profile_name`` (if any),
        then wait up to ``timeout`` seconds for the worker to finish so callers
        observe the in-flight guard cleared before running save-partial /
        cleanup-orphans.

        Returns True if no turn was active or the worker finished within the
        timeout; False if the worker is still winding down.
        """
        with self._lock:
            worker = self._active.get(profile_name)
        if worker is None or worker.done.is_set():
            return True
        worker.cancel()
        return worker.done.wait(timeout)

    def _clear(self, profile_name, worker):
        with self._lock:
            if self._active.get(profile_name) is worker:
                del self._active[profile_name]
