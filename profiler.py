import psutil
import time
import threading
from agent_simulation import run_mass_simulation

def monitor_hardware(stop_event, stats):
    """
    Runs in the background, polling the OS for hardware metrics every 0.1 seconds.
    """
    # Get the specific OS process running this Python script
    process = psutil.Process()
    
    while not stop_event.is_set():
        # 1. CPU Usage (Percentage)
        cpu_percent = psutil.cpu_percent(interval=None)
        if cpu_percent > stats['max_cpu']:
            stats['max_cpu'] = cpu_percent
            
        # 2. Memory Usage (Physical/RSS and Virtual/VMS in Bytes)
        mem_info = process.memory_info()
        
        # Convert bytes to Megabytes (MB)
        physical_mb = mem_info.rss / (1024 * 1024)
        virtual_mb = mem_info.vms / (1024 * 1024)
        
        if physical_mb > stats['max_physical_mem']:
            stats['max_physical_mem'] = physical_mb
            
        if virtual_mb > stats['max_virtual_mem']:
            stats['max_virtual_mem'] = virtual_mb
            
        time.sleep(0.1)

if __name__ == "__main__":
    print("Starting Hardware Profiler...")
    
    # Dictionary to store our highest recorded metrics
    system_stats = {
        'max_cpu': 0.0,
        'max_physical_mem': 0.0,
        'max_virtual_mem': 0.0
    }
    
    # Record baseline CPU times before the test
    cpu_times_start = psutil.cpu_times()
    
    stop_event = threading.Event()
    
    # Start the monitoring thread
    monitor_thread = threading.Thread(target=monitor_hardware, args=(stop_event, system_stats))
    monitor_thread.start()
    
    # --- RUN THE MASS SIMULATION ---
    # Running 100 agents to really push the CPU and Memory
    run_mass_simulation(total_agents=100)
    # -------------------------------
    
    # Stop the monitor
    stop_event.set()
    monitor_thread.join()
    
    # Calculate CPU Idle Time during the run
    cpu_times_end = psutil.cpu_times()
    idle_time_seconds = cpu_times_end.idle - cpu_times_start.idle
    
    # Print the Final Report
    print("\n" + "="*50)
    print("FINAL HARDWARE PROFILING REPORT")
    print("="*50)
    print(f"Maximum CPU Usage:       {system_stats['max_cpu']}%")
    print(f"Total CPU Idle Time:     {idle_time_seconds:.2f} seconds")
    print(f"Max Physical Memory:     {system_stats['max_physical_mem']:.2f} MB")
    print(f"Max Virtual Memory:      {system_stats['max_virtual_mem']:.2f} MB")
    print("="*50)