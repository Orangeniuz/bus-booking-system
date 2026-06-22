import threading
import queue
import time

class AsyncBatchLogger:
    def __init__(self, filepath="archive.log", batch_size=10, flush_interval=2.0):
        self.filepath = filepath
        self.batch_size = batch_size
        self.flush_interval = flush_interval

        # A thread-safe FIFO queue buffer.
        self.log_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.io_ops = 0

        # Lock to prevent a shutdown race while the writer is flushing.
        self.flush_lock = threading.Lock()

        # Keep the file open for repeated appends to reduce open/close overhead.
        self.file = open(self.filepath, 'a', encoding='utf-8')

        self.writer_thread = threading.Thread(target=self._process_logs, daemon=True)
        self.writer_thread.start()

    def log(self, message):
        """
        Enqueue a log message. This is non-blocking for the caller.
        """
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        formatted_message = f"[{timestamp}] {message}\n"
        self.log_queue.put(formatted_message)

    def _process_logs(self):
        """
        Background writer thread: batch entries then write them to disk.
        """
        while not self.stop_event.is_set() or not self.log_queue.empty():
            batch = []
            try:
                item = self.log_queue.get(timeout=self.flush_interval)
                batch.append(item)
                while len(batch) < self.batch_size:
                    try:
                        batch.append(self.log_queue.get_nowait())
                    except queue.Empty:
                        break
            except queue.Empty:
                pass

            with self.flush_lock:
                if batch:
                    self._write_to_disk(batch)
                    for _ in range(len(batch)):
                        self.log_queue.task_done()

    def _write_to_disk(self, batch):
        """
        Write the entire batch to the open file in a single I/O operation.
        """
        try:
            self.file.writelines(batch)
            self.file.flush()
            self.io_ops += 1
        except Exception as e:
            print(f"Failed to write to log file: {e}")

    def shutdown(self):
        """
        Stop the logger and flush any remaining entries.
        """
        with self.flush_lock:
            self.stop_event.set()
        self.writer_thread.join()
        try:
            self.file.close()
        except Exception:
            pass
