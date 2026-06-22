import threading
import queue
import time
import os

class AsyncBatchLogger:
    def __init__(self, filepath="archive.log", batch_size=10, flush_interval=2.0):
        self.filepath = filepath
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        
        # A thread-safe FIFO (First-In-First-Out) queue
        self.log_queue = queue.Queue()
        self.stop_event = threading.Event()
        
        # Start the dedicated background writer thread
        self.writer_thread = threading.Thread(target=self._process_logs, daemon=True)
        self.writer_thread.start()

    def log(self, message):
        """
        Clients and worker threads call this. 
        It is instantaneous because it only writes to RAM (the queue), not the disk.
        """
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        formatted_message = f"[{timestamp}] {message}\n"
        self.log_queue.put(formatted_message)

    def _process_logs(self):
        """
        The background loop that actually talks to the hard drive.
        """
        while not self.stop_event.is_set() or not self.log_queue.empty():
            batch = []
            try:
                # Try to grab the first item, wait up to flush_interval seconds
                item = self.log_queue.get(timeout=self.flush_interval)
                batch.append(item)
                
                # Grab more items quickly until we hit the batch limit
                while len(batch) < self.batch_size:
                    try:
                        next_item = self.log_queue.get_nowait()
                        batch.append(next_item)
                    except queue.Empty:
                        break # No more items right now
                        
            except queue.Empty:
                pass # The timeout triggered, time to flush whatever we have

            # If we collected anything, perform ONE single disk write
            if batch:
                self._write_to_disk(batch)
                for _ in range(len(batch)):
                    self.log_queue.task_done()

    def _write_to_disk(self, batch):
        """
        Opens the file, dumps the whole batch, and closes it.
        """
        try:
            # 'a' mode appends to the file safely
            with open(self.filepath, 'a', encoding='utf-8') as f:
                f.writelines(batch)
        except Exception as e:
            print(f"Failed to write to log file: {e}")

    def shutdown(self):
        """
        Gracefully stops the logger, ensuring everything in RAM is saved to disk before closing.
        """
        self.stop_event.set()
        self.writer_thread.join()