from . import monitor

mon = None


def start_monitor():
    global mon
    mon = monitor.Monitor()
    mon.start()
    return mon


def dashboard():
    d = monitor.system_info()
    hist = mon.history() if mon else []
    d.update(mem=monitor.meminfo(), disks=monitor.disks(), load=monitor.loadavg(),
             now=hist[-1] if hist else None, processes=monitor.processes(8))
    return d
